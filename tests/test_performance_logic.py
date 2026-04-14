"""
Tests for optimization/performance_logic.py.

Covers: allocate_to_highest_performance, _prepare_group_columns
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

from optimization.performance_logic import (
    allocate_to_highest_performance,
    _prepare_group_columns,
)


# ==================== FIXTURES ====================

@pytest.fixture
def multi_carrier_data():
    """Data with multiple carriers per lane/week."""
    return pd.DataFrame({
        'Category': ['CD', 'CD', 'CD'],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USLAXIUSF'],
        'Week Number': [9, 9, 9],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'IJKL'],
        'Container Count': [5, 3, 2],
        'Container Numbers': ['C001, C002, C003, C004, C005',
                              'C006, C007, C008',
                              'C009, C010'],
        'Base Rate': [100, 150, 200],
        'Total Rate': [500, 450, 400],
        'Performance_Score': [0.7, 0.9, 0.85],
    })


@pytest.fixture
def multi_group_data():
    """Data with multiple lane/week groups."""
    return pd.DataFrame({
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USBALREWR', 'USBALREWR'],
        'Week Number': [9, 9, 9, 9],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'ABCD', 'IJKL'],
        'Container Count': [5, 3, 4, 6],
        'Container Numbers': ['C001, C002, C003, C004, C005',
                              'C006, C007, C008',
                              'C009, C010, C011, C012',
                              'C013, C014, C015, C016, C017, C018'],
        'Base Rate': [100, 150, 120, 180],
        'Total Rate': [500, 450, 480, 1080],
        'Performance_Score': [0.7, 0.9, 0.85, 0.6],
    })


@pytest.fixture
def tied_performance_data():
    """Data where carriers have the same performance score."""
    return pd.DataFrame({
        'Lane': ['USLAXIUSF', 'USLAXIUSF'],
        'Week Number': [9, 9],
        'Dray SCAC(FL)': ['ABCD', 'EFGH'],
        'Container Count': [5, 3],
        'Container Numbers': ['C001, C002, C003, C004, C005',
                              'C006, C007, C008'],
        'Base Rate': [100, 200],
        'Total Rate': [500, 600],
        'Performance_Score': [0.8, 0.8],
    })


# ==================== _prepare_group_columns ====================

class TestPrepareGroupColumns:
    def test_all_columns_present(self):
        df = pd.DataFrame(columns=['Lane', 'Week Number', 'Extra'])
        result = _prepare_group_columns(df)
        assert result == ['Lane', 'Week Number']

    def test_only_lane(self):
        df = pd.DataFrame(columns=['Lane'])
        result = _prepare_group_columns(df)
        assert result == ['Lane']

    def test_with_extras(self):
        df = pd.DataFrame(columns=['Lane', 'Week Number', 'Dray SCAC(FL)'])
        result = _prepare_group_columns(df, extras=['Dray SCAC(FL)'])
        assert 'Dray SCAC(FL)' in result

    def test_missing_all_raises(self):
        df = pd.DataFrame(columns=['Unrelated'])
        with pytest.raises(ValueError, match="at least one of the grouping columns"):
            _prepare_group_columns(df)


# ==================== allocate_to_highest_performance ====================

class TestAllocateToHighestPerformance:
    def test_empty_data(self):
        result = allocate_to_highest_performance(pd.DataFrame())
        assert result.empty

    def test_none_data(self):
        result = allocate_to_highest_performance(None)
        assert result.empty

    def test_picks_highest_performance(self, multi_carrier_data):
        result = allocate_to_highest_performance(multi_carrier_data)
        # EFGH has 0.9 performance → should be selected
        assert len(result) == 1
        assert result.iloc[0]['Dray SCAC(FL)'] == 'EFGH'

    def test_assigns_all_containers(self, multi_carrier_data):
        total_before = multi_carrier_data['Container Count'].sum()
        result = allocate_to_highest_performance(multi_carrier_data)
        # Container count based on deduplicated container IDs
        total_after = result['Container Count'].sum()
        assert total_after == total_before

    def test_recalculates_total_rate(self, multi_carrier_data):
        result = allocate_to_highest_performance(multi_carrier_data)
        expected = result.iloc[0]['Base Rate'] * result.iloc[0]['Container Count']
        assert result.iloc[0]['Total Rate'] == expected

    def test_one_row_per_group(self, multi_group_data):
        result = allocate_to_highest_performance(multi_group_data)
        # Two groups (USLAXIUSF week 9, USBALREWR week 9)
        assert len(result) == 2

    def test_each_group_gets_best_performer(self, multi_group_data):
        result = allocate_to_highest_performance(multi_group_data)
        # USLAXIUSF: EFGH (0.9) wins;  USBALREWR: ABCD (0.85) wins
        lax_row = result[result['Lane'] == 'USLAXIUSF'].iloc[0]
        bal_row = result[result['Lane'] == 'USBALREWR'].iloc[0]
        assert lax_row['Dray SCAC(FL)'] == 'EFGH'
        assert bal_row['Dray SCAC(FL)'] == 'ABCD'

    def test_tie_broken_by_cost(self, tied_performance_data):
        result = allocate_to_highest_performance(tied_performance_data)
        # Same performance → cheaper carrier (ABCD at 100) wins
        assert result.iloc[0]['Dray SCAC(FL)'] == 'ABCD'

    def test_allocation_strategy_label(self, multi_carrier_data):
        result = allocate_to_highest_performance(multi_carrier_data)
        assert 'Allocation Strategy' in result.columns
        assert result.iloc[0]['Allocation Strategy'] == 'Highest Performance Carrier'

    def test_container_numbers_concatenated(self, multi_carrier_data):
        result = allocate_to_highest_performance(multi_carrier_data)
        container_str = result.iloc[0]['Container Numbers']
        # All 10 containers should be in the string
        ids = [c.strip() for c in container_str.split(',') if c.strip()]
        assert len(ids) == 10

    def test_container_deduplication(self):
        """Same container ID appearing under two carriers should only be counted once."""
        data = pd.DataFrame({
            'Lane': ['USLAXIUSF', 'USLAXIUSF'],
            'Week Number': [9, 9],
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Container Count': [3, 2],
            'Container Numbers': ['C001, C002, C003', 'C001, C004'],
            'Base Rate': [100, 200],
            'Total Rate': [300, 400],
            'Performance_Score': [0.7, 0.9],
        })
        result = allocate_to_highest_performance(data)
        # C001 duplicated → should become 4 unique containers
        assert result.iloc[0]['Container Count'] == 4

    def test_missing_performance_column_raises(self):
        data = pd.DataFrame({
            'Lane': ['USLAXIUSF'],
            'Week Number': [9],
            'Dray SCAC(FL)': ['ABCD'],
            'Container Count': [5],
        })
        with pytest.raises(ValueError, match="Performance_Score"):
            allocate_to_highest_performance(data)

    def test_missing_carrier_column_raises(self):
        data = pd.DataFrame({
            'Lane': ['USLAXIUSF'],
            'Week Number': [9],
            'Container Count': [5],
            'Performance_Score': [0.8],
        })
        with pytest.raises(ValueError, match="Dray SCAC"):
            allocate_to_highest_performance(data)

    def test_cpc_recalculated(self):
        data = pd.DataFrame({
            'Lane': ['USLAXIUSF', 'USLAXIUSF'],
            'Week Number': [9, 9],
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Container Count': [5, 3],
            'Container Numbers': ['C001, C002, C003, C004, C005', 'C006, C007, C008'],
            'CPC': [50, 80],
            'Total CPC': [250, 240],
            'Performance_Score': [0.7, 0.9],
        })
        result = allocate_to_highest_performance(data)
        expected_total_cpc = result.iloc[0]['CPC'] * result.iloc[0]['Container Count']
        assert result.iloc[0]['Total CPC'] == expected_total_cpc
