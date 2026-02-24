"""
Tests for carrier flips logic.
Verifies that Current Selection shows 'No Flip' for all rows.
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

from components.container_tracer import (
    build_container_origin_map,
    trace_container_movements,
    format_flip_details,
    add_detailed_carrier_flips_column,
)


@pytest.fixture
def sample_data():
    """Simulate data as it appears in the detailed analysis table."""
    return pd.DataFrame({
        'Discharged Port': ['LAX', 'LAX', 'LAX'],
        'Category': ['FBA FCL', 'FBA FCL', 'FBA FCL'],
        'SSL': ['CMDU', 'CMDU', 'CMDU'],
        'Vessel': ['CMA CGM ARGENTINA', 'CMA CGM ARGENTINA', 'CMA CGM SWORDFISH'],
        'Dray SCAC(FL)': ['USLAXUSP', 'USLAXPOC1', 'USLAXLAR9'],
        'Lane': ['USLAXIUSP', 'USLAXPOC1', 'USLAXLAR9'],
        'Facility': ['IUSP-5', 'POC1-5', 'LAX9-5'],
        'Terminal': [None, None, None],
        'Week Number': [9, 9, 9],
        'Container Numbers': ['SEKU3242155', 'APHU7288126, CMAU6320826', 'ECMU57L1851, TCNU2832S0'],
        'Container Count': [1, 2, 2],
        'Base Rate': [0, 0, 0],
        'Total Rate': [0, 0, 0],
    })


class TestOriginMap:
    def test_origin_map_has_week(self, sample_data):
        """Origin map should store week as int under 'week' key."""
        origin_map = build_container_origin_map(sample_data, carrier_col='Dray SCAC(FL)')
        for cid, info in origin_map.items():
            assert 'week' in info, f"Container {cid} missing 'week' key"
            assert info['week'] == 9, f"Container {cid} has week={info['week']}, expected 9"

    def test_origin_map_has_carrier(self, sample_data):
        """Origin map should have correct carrier for each container."""
        origin_map = build_container_origin_map(sample_data, carrier_col='Dray SCAC(FL)')
        assert origin_map['SEKU3242155']['original_carrier'] == 'USLAXUSP'
        assert origin_map['APHU7288126']['original_carrier'] == 'USLAXPOC1'

    def test_origin_map_nan_carrier(self):
        """NaN carrier should become 'Unknown'."""
        df = pd.DataFrame({
            'Dray SCAC(FL)': [np.nan],
            'Week Number': [9],
            'Container Numbers': ['C001'],
        })
        origin_map = build_container_origin_map(df, carrier_col='Dray SCAC(FL)')
        assert origin_map['C001']['original_carrier'] == 'Unknown'


class TestTraceMovements:
    def test_same_data_all_kept(self, sample_data):
        """When current == baseline, all containers should be 'kept'."""
        origin_map = build_container_origin_map(sample_data, carrier_col='Dray SCAC(FL)')
        results, destinations = trace_container_movements(sample_data, origin_map, carrier_col='Dray SCAC(FL)')
        
        for i, result in enumerate(results):
            assert result['total_flipped'] == 0, f"Row {i}: expected 0 flipped, got {result['total_flipped']}"
            assert result['total_unknown'] == 0, f"Row {i}: expected 0 unknown, got {result['total_unknown']}"
            assert result['total_kept'] == result['current_count'], (
                f"Row {i}: kept={result['total_kept']} != current={result['current_count']}"
            )
            assert result['original_count'] == result['current_count'], (
                f"Row {i}: original_count={result['original_count']} != current_count={result['current_count']}"
            )

    def test_group_key_week_matching(self, sample_data):
        """Group keys should match between origin map and current data."""
        origin_map = build_container_origin_map(sample_data, carrier_col='Dray SCAC(FL)')
        results, _ = trace_container_movements(sample_data, origin_map, carrier_col='Dray SCAC(FL)')
        
        # If group keys match, original_count should be > 0 for rows with containers
        for i, result in enumerate(results):
            if result['current_count'] > 0:
                assert result['original_count'] > 0, (
                    f"Row {i}: original_count=0 but current_count={result['current_count']}. "
                    f"Group key mismatch between origin map and current data."
                )


class TestFormatFlipDetails:
    def test_no_flip_when_kept_all(self):
        """Should return 'No Flip' when all containers kept."""
        result = {
            'total_kept': 3,
            'total_flipped': 0,
            'total_unknown': 0,
            'flip_summary': {},
            'original_count': 3,
            'current_count': 3,
            'kept_containers': ['C1', 'C2', 'C3'],
            'all_original_containers': ['C1', 'C2', 'C3'],
            'flip_containers_by_source': {},
            'flipped_containers': [],
        }
        assert format_flip_details(result) == "No Flip"

    def test_no_flip_when_zero(self):
        """Should return 'No Flip' when 0 containers."""
        result = {
            'total_kept': 0,
            'total_flipped': 0,
            'total_unknown': 0,
            'flip_summary': {},
            'original_count': 0,
            'current_count': 0,
            'kept_containers': [],
            'all_original_containers': [],
            'flip_containers_by_source': {},
            'flipped_containers': [],
        }
        assert format_flip_details(result) == "No Flip"

    def test_flip_shown_when_containers_moved(self):
        """Should NOT return 'No Flip' when containers moved."""
        result = {
            'total_kept': 2,
            'total_flipped': 1,
            'total_unknown': 0,
            'flip_summary': {'ABCD': 1},
            'original_count': 2,
            'current_count': 3,
            'kept_containers': ['C1', 'C2'],
            'all_original_containers': ['C1', 'C2'],
            'flip_containers_by_source': {'ABCD': ['C3']},
            'flipped_containers': [('C3', 'ABCD')],
        }
        formatted = format_flip_details(result)
        assert formatted != "No Flip"
        assert "From ABCD" in formatted


class TestAddDetailedCarrierFlipsColumn:
    def test_current_selection_all_no_flip(self, sample_data):
        """Current Selection: comparing data against itself should produce all 'No Flip'."""
        baseline = sample_data.copy()
        current = sample_data.copy()
        result = add_detailed_carrier_flips_column(current, baseline, carrier_col='Dray SCAC(FL)')
        
        flips = result['Carrier Flips (Detailed)'].tolist()
        for i, flip in enumerate(flips):
            assert flip == "No Flip", f"Row {i}: expected 'No Flip', got '{flip}'"

    def test_with_float_week_number(self):
        """Week Number as float (9.0) should still match int (9) in origin map."""
        df_int = pd.DataFrame({
            'Dray SCAC(FL)': ['ABCD'],
            'Week Number': [9],  # int
            'Lane': ['USLAXIUSF'],
            'Discharged Port': ['LAX'],
            'Facility': ['IUSF'],
            'Container Numbers': ['C001, C002'],
            'Container Count': [2],
        })
        df_float = pd.DataFrame({
            'Dray SCAC(FL)': ['ABCD'],
            'Week Number': [9.0],  # float
            'Lane': ['USLAXIUSF'],
            'Discharged Port': ['LAX'],
            'Facility': ['IUSF'],
            'Container Numbers': ['C001, C002'],
            'Container Count': [2],
        })
        result = add_detailed_carrier_flips_column(df_float, df_int, carrier_col='Dray SCAC(FL)')
        assert result['Carrier Flips (Detailed)'].iloc[0] == "No Flip"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
