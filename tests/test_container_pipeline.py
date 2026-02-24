"""
Tests for container count preservation through the data pipeline.

Verifies that no containers are lost during groupby, dedup, and scenario calculations.
Run with: python -m pytest tests/test_container_pipeline.py -v
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

from components.utils import (
    count_containers,
    deduplicate_containers_per_lane_week,
    parse_container_ids,
    concat_and_dedupe_containers,
)


# ==================== FIXTURES ====================

@pytest.fixture
def simple_data():
    """Simple dataset with no duplicates."""
    return pd.DataFrame({
        'Week Number': [9, 9, 9, 10, 10],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USBALHGR6', 'USLAXIUSF', 'USBALHGR6'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'ABCD', 'ABCD', 'EFGH'],
        'Container Numbers': ['C001, C002, C003', 'C004, C005', 'C006, C007', 'C008', 'C009, C010'],
        'Container Count': [3, 2, 2, 1, 2],
        'Base Rate': [100, 200, 150, 100, 200],
        'Total Rate': [300, 400, 300, 100, 400],
    })


@pytest.fixture
def duplicate_data():
    """Dataset where same container appears under 2 carriers in same lane/week."""
    return pd.DataFrame({
        'Week Number': [9, 9, 9],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USLAXIUSF'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'IJKL'],
        'Container Numbers': ['C001, C002, C003', 'C001, C004', 'C005'],
        'Container Count': [3, 2, 1],
        'Base Rate': [100, 200, 150],
        'Total Rate': [300, 400, 150],
    })


@pytest.fixture
def cross_week_data():
    """Same container in different weeks (legitimate, should NOT be deduped)."""
    return pd.DataFrame({
        'Week Number': [9, 10],
        'Lane': ['USLAXIUSF', 'USLAXIUSF'],
        'Dray SCAC(FL)': ['ABCD', 'ABCD'],
        'Container Numbers': ['C001, C002', 'C001, C003'],
        'Container Count': [2, 2],
        'Base Rate': [100, 100],
        'Total Rate': [200, 200],
    })


@pytest.fixture
def cross_lane_data():
    """Same container in different lanes same week (legitimate, should NOT be deduped)."""
    return pd.DataFrame({
        'Week Number': [9, 9],
        'Lane': ['USLAXIUSF', 'USBALHGR6'],
        'Dray SCAC(FL)': ['ABCD', 'ABCD'],
        'Container Numbers': ['C001, C002', 'C001, C003'],
        'Container Count': [2, 2],
        'Base Rate': [100, 100],
        'Total Rate': [200, 200],
    })


@pytest.fixture
def gvt_file_data():
    """Load real GVT data if available, skip if not."""
    path = r'C:\Users\maabdiac\Downloads\Tender optimization data\gvt data 2-11.xlsx'
    try:
        df = pd.read_excel(path)
    except FileNotFoundError:
        pytest.skip("GVT test file not available")
    df['Ocean ETA'] = pd.to_datetime(df['Ocean ETA'], errors='coerce')
    df['Week Number'] = df['Ocean ETA'].apply(
        lambda x: int(x.strftime('%U')) + 1 if pd.notna(x) else None
    )
    df = df[~df['Market'].str.upper().str.contains('CANADA', na=False)]
    df = df.dropna(subset=['Ocean ETA'])
    return df


# ==================== count_containers TESTS ====================

class TestCountContainers:
    def test_normal(self):
        assert count_containers('C001, C002, C003') == 3

    def test_single(self):
        assert count_containers('C001') == 1

    def test_empty(self):
        assert count_containers('') == 0

    def test_nan(self):
        assert count_containers(np.nan) == 0

    def test_whitespace(self):
        assert count_containers('  C001 , C002 ,  C003  ') == 3

    def test_trailing_comma(self):
        assert count_containers('C001, C002,') == 2


# ==================== deduplicate_containers_per_lane_week TESTS ====================

class TestDeduplicateContainers:
    def test_no_duplicates_unchanged(self, simple_data):
        result = deduplicate_containers_per_lane_week(simple_data)
        assert int(result['Container Count'].sum()) == 10
        assert len(result) == 5

    def test_cross_carrier_dedup(self, duplicate_data):
        """C001 appears under ABCD and EFGH in same lane/week — should be kept only once."""
        result = deduplicate_containers_per_lane_week(duplicate_data)
        total = int(result['Container Count'].sum())
        # C001 counted once (under ABCD), C002, C003, C004, C005 = 5 unique
        assert total == 5

    def test_cross_carrier_dedup_ids(self, duplicate_data):
        """Verify the actual container IDs after dedup."""
        result = deduplicate_containers_per_lane_week(duplicate_data)
        all_ids = set()
        for cn in result['Container Numbers']:
            all_ids.update(parse_container_ids(cn))
        assert all_ids == {'C001', 'C002', 'C003', 'C004', 'C005'}

    def test_cross_week_preserved(self, cross_week_data):
        """Same container in different weeks should NOT be deduped."""
        result = deduplicate_containers_per_lane_week(cross_week_data)
        assert int(result['Container Count'].sum()) == 4  # C001 counted in both weeks

    def test_cross_lane_preserved(self, cross_lane_data):
        """Same container in different lanes same week should NOT be deduped."""
        result = deduplicate_containers_per_lane_week(cross_lane_data)
        assert int(result['Container Count'].sum()) == 4  # C001 counted in both lanes

    def test_total_rate_recalculated(self, duplicate_data):
        """Total Rate should be recalculated after dedup."""
        result = deduplicate_containers_per_lane_week(duplicate_data)
        for _, row in result.iterrows():
            expected = row['Base Rate'] * row['Container Count']
            assert row['Total Rate'] == expected

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=['Week Number', 'Lane', 'Container Numbers', 'Container Count'])
        result = deduplicate_containers_per_lane_week(df)
        assert len(result) == 0

    def test_no_container_numbers_column(self):
        df = pd.DataFrame({'Week Number': [9], 'Container Count': [5]})
        result = deduplicate_containers_per_lane_week(df)
        assert int(result['Container Count'].sum()) == 5  # Unchanged


# ==================== REAL DATA TESTS ====================

class TestRealGVTData:
    def test_week9_container_count(self, gvt_file_data):
        """Week 9 should have exactly 2264 containers (excluding Canada)."""
        wk9 = gvt_file_data[gvt_file_data['Week Number'] == 9]
        assert wk9['Container'].nunique() == 2264

    def test_groupby_preserves_containers(self, gvt_file_data):
        """Groupby should not lose any containers."""
        df = gvt_file_data.copy()
        df['Discharged Port'] = df['Discharged Port'].astype(str)
        df['Facility'] = df['Facility'].astype(str)
        df['Lane'] = df['Discharged Port'] + df['Facility'].str[:4]

        group_cols = ['Week Number', 'Discharged Port', 'Dray SCAC(FL)', 'Facility', 'Lane']
        for opt_col in ['Category', 'SSL', 'Vessel', 'Terminal']:
            if opt_col in df.columns:
                group_cols.append(opt_col)

        def combine_unique(x):
            seen = set()
            result = []
            for v in x.astype(str):
                v = v.strip()
                if v and v.lower() != 'nan' and v not in seen:
                    result.append(v)
                    seen.add(v)
            return ', '.join(result)

        grouped = df.groupby(group_cols, dropna=False).agg(
            {'Container': combine_unique}
        ).reset_index()
        grouped['Container Count'] = grouped['Container'].apply(count_containers)

        wk9_raw = df[df['Week Number'] == 9]['Container'].nunique()
        wk9_grouped = int(grouped[grouped['Week Number'] == 9]['Container Count'].sum())
        assert wk9_grouped == wk9_raw

    def test_dedup_preserves_week9(self, gvt_file_data):
        """Dedup should not lose week 9 containers (no cross-carrier dupes expected)."""
        df = gvt_file_data.copy()
        df['Discharged Port'] = df['Discharged Port'].astype(str)
        df['Facility'] = df['Facility'].astype(str)
        df['Lane'] = df['Discharged Port'] + df['Facility'].str[:4]

        group_cols = ['Week Number', 'Discharged Port', 'Dray SCAC(FL)', 'Facility', 'Lane']
        for opt_col in ['Category', 'SSL', 'Vessel', 'Terminal']:
            if opt_col in df.columns:
                group_cols.append(opt_col)

        def combine_unique(x):
            seen = set()
            result = []
            for v in x.astype(str):
                v = v.strip()
                if v and v.lower() != 'nan' and v not in seen:
                    result.append(v)
                    seen.add(v)
            return ', '.join(result)

        grouped = df.groupby(group_cols, dropna=False).agg(
            {'Container': combine_unique}
        ).reset_index()
        grouped = grouped.rename(columns={'Container': 'Container Numbers'})
        grouped['Container Count'] = grouped['Container Numbers'].apply(count_containers)
        grouped['Base Rate'] = 0
        grouped['Total Rate'] = 0

        deduped = deduplicate_containers_per_lane_week(grouped)
        wk9 = deduped[deduped['Week Number'] == 9]
        assert int(wk9['Container Count'].sum()) == 2264


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
