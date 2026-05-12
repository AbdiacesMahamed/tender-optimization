"""
Tests for optimization/constraint_allocator.py

Covers: load_and_normalize_constraints, sort_constraints, allocate_with_hierarchy
"""
import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimization.constraint_allocator import (
    load_and_normalize_constraints,
    sort_constraints,
    allocate_with_hierarchy,
    _compute_specificity,
    _compute_target,
    _is_filled,
)


# ==================== Fixtures ====================

@pytest.fixture
def sample_data():
    """Sample container data for EWR CD with multiple carriers and lanes."""
    rows = []
    lanes = ['ABE4', 'ABE8', 'IUSL', 'HEA2', 'TEB9']
    carriers = ['ATMI', 'ARVY', 'FRQT', 'PGLT']

    for lane in lanes:
        for carrier in carriers:
            n = 10
            ids = [f'C-{lane}-{carrier}-{i}' for i in range(n)]
            rows.append({
                'Discharged Port': 'EWR',
                'Category': 'CD',
                'Lane': lane,
                'Dray SCAC(FL)': carrier,
                'Carrier': carrier,
                'Facility': lane,
                'Week Number': 20,
                'Container Count': n,
                'Container Numbers': ', '.join(ids),
            })

    return pd.DataFrame(rows)


@pytest.fixture
def simple_constraints():
    """Constraints covering priority 10, 9, and 8 scenarios."""
    return pd.DataFrame([
        # Priority 10: ATMI gets 100% of IUSL
        {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'ATMI', 'Lane': 'IUSL',
         'Percent Allocation': 100, 'Priority Score': 10,
         'Maximum Container Count': None, 'Minimum Container Count': None,
         'Excluded FC': None, 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
        # Priority 10: FRQT gets 60% of ABE4
        {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'FRQT', 'Lane': 'ABE4',
         'Percent Allocation': 60, 'Priority Score': 10,
         'Maximum Container Count': None, 'Minimum Container Count': None,
         'Excluded FC': None, 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
        # Priority 9: ATMI gets 30% of EWR CD (no lane), max 500
        {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'ATMI', 'Lane': None,
         'Percent Allocation': 30, 'Priority Score': 9,
         'Maximum Container Count': 500, 'Minimum Container Count': None,
         'Excluded FC': None, 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
        # Priority 8: PGLT blocked (pct=0, max=0)
        {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'PGLT', 'Lane': None,
         'Percent Allocation': 0, 'Priority Score': 8,
         'Maximum Container Count': 0, 'Minimum Container Count': None,
         'Excluded FC': None, 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
        # Priority 8: ARVY capped at 20 (overflow only)
        {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'ARVY', 'Lane': None,
         'Percent Allocation': 0, 'Priority Score': 8,
         'Maximum Container Count': 20, 'Minimum Container Count': None,
         'Excluded FC': None, 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
    ])


# ==================== load_and_normalize_constraints ====================

class TestLoadAndNormalize:
    def test_percent_scale_conversion(self):
        """Values in 0-1 range should be converted to 0-100."""
        df = pd.DataFrame({
            'Port': ['EWR'], 'Carrier': ['ATMI'], ' Lane': ['ABE4'],
            'Percent Allocation': [0.6], 'Priority Score': [10],
            'Maximum container number': [None], 'minimum container number': [None],
        })
        result = load_and_normalize_constraints(df)
        assert result['Percent Allocation'].iloc[0] == 60.0

    def test_column_rename_with_spaces(self):
        """Leading space in ' Lane' should be handled."""
        df = pd.DataFrame({
            ' Lane': ['ABE4'], 'Priority Score': [10],
            'Maximum container number': [100.0], 'Carrier': ['ATMI'],
        })
        result = load_and_normalize_constraints(df)
        assert 'Lane' in result.columns
        assert 'Maximum Container Count' in result.columns
        assert result['Maximum Container Count'].iloc[0] == 100.0

    def test_drops_rows_without_priority(self):
        df = pd.DataFrame({
            'Carrier': ['ATMI', 'FRQT'], 'Priority Score': [10, None],
        })
        result = load_and_normalize_constraints(df)
        assert len(result) == 1


# ==================== sort_constraints ====================

class TestSortConstraints:
    def test_priority_ordering(self, simple_constraints):
        sorted_df = sort_constraints(simple_constraints)
        priorities = sorted_df['Priority Score'].tolist()
        assert priorities == sorted(priorities, reverse=True)

    def test_specificity_within_same_priority(self):
        """More specific (with lane) should come before less specific (no lane)."""
        df = pd.DataFrame([
            {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'ATMI', 'Lane': None,
             'Percent Allocation': 50, 'Priority Score': 9,
             'Maximum Container Count': None, 'Minimum Container Count': None,
             'Excluded FC': None, 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
            {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'ATMI', 'Lane': 'ABE4',
             'Percent Allocation': 50, 'Priority Score': 9,
             'Maximum Container Count': None, 'Minimum Container Count': None,
             'Excluded FC': None, 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
        ])
        sorted_df = sort_constraints(df)
        # Lane-specific row should be first
        assert sorted_df.iloc[0]['Lane'] == 'ABE4'
        assert pd.isna(sorted_df.iloc[1]['Lane']) or sorted_df.iloc[1]['Lane'] is None


# ==================== allocate_with_hierarchy ====================

class TestAllocateWithHierarchy:
    def test_priority_10_lane_lock(self, sample_data, simple_constraints):
        constrained, unconstrained, summary, _, _, _ = allocate_with_hierarchy(
            sample_data, simple_constraints
        )
        # ATMI should get 100% of IUSL (40 containers across 4 carrier rows)
        atmi_iusl = constrained[
            (constrained['Dray SCAC(FL)'] == 'ATMI') & (constrained['Lane'] == 'IUSL')
        ]
        assert atmi_iusl['Container Count'].sum() == 40

    def test_priority_10_partial_allocation(self, sample_data, simple_constraints):
        constrained, _, _, _, _, _ = allocate_with_hierarchy(
            sample_data, simple_constraints
        )
        # FRQT gets 60% of ABE4 (40 total containers → 24)
        frqt_abe4 = constrained[
            (constrained['Dray SCAC(FL)'] == 'FRQT') & (constrained['Lane'] == 'ABE4')
        ]
        assert frqt_abe4['Container Count'].sum() == 24

    def test_max_cap_inclusive_of_lane_locks(self, sample_data, simple_constraints):
        constrained, _, _, _, _, _ = allocate_with_hierarchy(
            sample_data, simple_constraints
        )
        # ATMI has max=500 total. Lane lock already gave ~40. Flexible row adds more
        # but total should not exceed 500
        atmi_total = constrained[constrained['Dray SCAC(FL)'] == 'ATMI']['Container Count'].sum()
        assert atmi_total <= 500

    def test_priority_8_block(self, sample_data, simple_constraints):
        _, _, _, max_carriers, _, _ = allocate_with_hierarchy(
            sample_data, simple_constraints
        )
        # PGLT should be in max_constrained (blocked)
        blocked = [m['carrier'] for m in max_carriers]
        assert 'PGLT' in blocked

    def test_priority_8_cap(self, sample_data, simple_constraints):
        _, _, _, max_carriers, _, _ = allocate_with_hierarchy(
            sample_data, simple_constraints
        )
        # ARVY should be capped
        assert 'ARVY' in [m['carrier'] for m in max_carriers]

    def test_container_balance(self, sample_data, simple_constraints):
        constrained, unconstrained, _, _, _, _ = allocate_with_hierarchy(
            sample_data, simple_constraints
        )
        original = sample_data['Container Count'].sum()
        final = (
            (constrained['Container Count'].sum() if len(constrained) > 0 else 0) +
            unconstrained['Container Count'].sum()
        )
        assert original == final

    def test_no_duplicate_container_ids(self, sample_data, simple_constraints):
        constrained, unconstrained, _, _, _, _ = allocate_with_hierarchy(
            sample_data, simple_constraints
        )
        # Collect all container IDs from both tables
        all_constrained_ids = set()
        if len(constrained) > 0:
            for _, row in constrained.iterrows():
                ids = row.get('Container Numbers', '')
                if ids:
                    for cid in ids.split(', '):
                        assert cid not in all_constrained_ids, f"Duplicate in constrained: {cid}"
                        all_constrained_ids.add(cid)

        all_unconstrained_ids = set()
        for _, row in unconstrained.iterrows():
            ids = row.get('Container Numbers', '')
            if ids:
                for cid in ids.split(', '):
                    all_unconstrained_ids.add(cid)

        # No overlap between constrained and unconstrained
        overlap = all_constrained_ids & all_unconstrained_ids
        assert len(overlap) == 0, f"Containers in both tables: {overlap}"

    def test_facility_exclusion(self, sample_data):
        """Carrier with Excluded FC should not receive containers at that facility."""
        constraints = pd.DataFrame([
            {'Port': 'EWR', 'Category': 'CD', 'Carrier': 'ATMI', 'Lane': None,
             'Percent Allocation': 50, 'Priority Score': 9,
             'Maximum Container Count': 100, 'Minimum Container Count': None,
             'Excluded FC': 'HEA2', 'Week Number': None, 'SSL': None, 'Terminal': None, 'Vessel': None},
        ])
        constrained, _, _, _, excl, _ = allocate_with_hierarchy(sample_data, constraints)

        assert 'ATMI' in excl
        assert 'HEA2' in excl['ATMI']

        # No constrained ATMI row should be at HEA2
        if len(constrained) > 0:
            atmi_hea2 = constrained[
                (constrained['Dray SCAC(FL)'] == 'ATMI') & (constrained['Facility'] == 'HEA2')
            ]
            assert len(atmi_hea2) == 0

    def test_empty_constraints(self, sample_data):
        """Empty constraints should pass everything to unconstrained."""
        empty = pd.DataFrame(columns=[
            'Port', 'Category', 'Carrier', 'Lane', 'Percent Allocation',
            'Priority Score', 'Maximum Container Count', 'Minimum Container Count',
            'Excluded FC', 'Week Number', 'SSL', 'Terminal', 'Vessel'
        ])
        constrained, unconstrained, _, _, _, _ = allocate_with_hierarchy(sample_data, empty)
        assert len(constrained) == 0
        assert unconstrained['Container Count'].sum() == sample_data['Container Count'].sum()


# ==================== _compute_target ====================

class TestComputeTarget:
    def test_block_pct0_max0(self):
        result = _compute_target(
            pct_alloc=0, max_count=0, min_count=None,
            total_available=100, already_allocated=0, priority=8
        )
        assert result is None

    def test_percentage_allocation(self):
        result = _compute_target(
            pct_alloc=30, max_count=None, min_count=None,
            total_available=100, already_allocated=0, priority=9
        )
        assert result == 30

    def test_max_cap_reduces_target(self):
        result = _compute_target(
            pct_alloc=50, max_count=20, min_count=None,
            total_available=100, already_allocated=0, priority=9
        )
        assert result == 20

    def test_max_cap_inclusive_of_already_allocated(self):
        result = _compute_target(
            pct_alloc=50, max_count=100, min_count=None,
            total_available=200, already_allocated=80, priority=9
        )
        # 50% of 200 = 100, but max cap remaining = 100-80 = 20
        assert result == 20

    def test_min_floor(self):
        result = _compute_target(
            pct_alloc=5, max_count=None, min_count=20,
            total_available=100, already_allocated=0, priority=9
        )
        # 5% of 100 = 5, but min=20
        assert result == 20

    def test_overflow_only_pct0_with_max(self):
        result = _compute_target(
            pct_alloc=0, max_count=75, min_count=None,
            total_available=100, already_allocated=0, priority=8
        )
        # pct=0 means no proactive allocation → target=0
        assert result == 0

    def test_priority8_pct0_no_max_is_block(self):
        result = _compute_target(
            pct_alloc=0, max_count=None, min_count=None,
            total_available=100, already_allocated=0, priority=8
        )
        assert result is None


# ==================== _is_filled ====================

class TestIsFilled:
    def test_none(self):
        assert _is_filled(None) is False

    def test_nan(self):
        assert _is_filled(float('nan')) is False

    def test_empty_string(self):
        assert _is_filled('') is False
        assert _is_filled('  ') is False

    def test_valid(self):
        assert _is_filled('EWR') is True
        assert _is_filled(10) is True
        assert _is_filled(0) is True
        assert _is_filled(0.0) is True
