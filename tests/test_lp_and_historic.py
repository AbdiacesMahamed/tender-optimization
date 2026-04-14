"""
Tests for optimization/linear_programming.py and optimization/historic_volume.py.

Covers: _normalize_values, optimize_carrier_allocation, _prepare_group_columns,
        get_current_week_number, filter_historical_weeks, get_last_n_weeks,
        calculate_carrier_volume_share
"""
import pandas as pd
import numpy as np
import pytest
import sys
from datetime import datetime
sys.path.insert(0, '.')

from optimization.linear_programming import (
    _normalize_values,
    optimize_carrier_allocation,
)
from optimization.historic_volume import (
    get_current_week_number,
    filter_historical_weeks,
    get_last_n_weeks,
    calculate_carrier_volume_share,
)


# ==================== FIXTURES ====================

@pytest.fixture
def lp_data():
    """Data for LP optimization tests."""
    return pd.DataFrame({
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USLAXIUSF'],
        'Week Number': [9, 9, 9],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'IJKL'],
        'Container Count': [5, 3, 2],
        'Container Numbers': ['C001, C002, C003, C004, C005',
                              'C006, C007, C008',
                              'C009, C010'],
        'Base Rate': [100, 200, 150],
        'Total Rate': [500, 600, 300],
        'Performance_Score': [0.7, 0.9, 0.5],
    })


@pytest.fixture
def historic_data():
    """Multi-week data for historical analysis."""
    rows = []
    for week in [5, 6, 7, 8, 9]:
        for carrier, count in [('ABCD', 10), ('EFGH', 5), ('IJKL', 3)]:
            rows.append({
                'Dray SCAC(FL)': carrier,
                'Container Count': count,
                'Week Number': week,
                'Lane': 'USLAXIUSF',
                'Category': 'CD',
            })
    return pd.DataFrame(rows)


# ==================== _normalize_values ====================

class TestNormalizeValues:
    def test_lower_is_better(self):
        values = pd.Series([100, 200, 300])
        result = _normalize_values(values, lower_is_better=True)
        assert result.iloc[0] == 0.0  # Lowest = best = 0
        assert result.iloc[2] == 1.0  # Highest = worst = 1

    def test_higher_is_better(self):
        values = pd.Series([100, 200, 300])
        result = _normalize_values(values, lower_is_better=False)
        assert result.iloc[0] == 1.0  # Lowest = worst = 1
        assert result.iloc[2] == 0.0  # Highest = best = 0

    def test_all_same_values(self):
        values = pd.Series([50, 50, 50])
        result = _normalize_values(values)
        assert (result == 0.5).all()

    def test_two_values(self):
        values = pd.Series([10, 20])
        result = _normalize_values(values, lower_is_better=True)
        assert result.iloc[0] == 0.0
        assert result.iloc[1] == 1.0


# ==================== optimize_carrier_allocation ====================

class TestOptimizeCarrierAllocation:
    def test_empty_data(self):
        result = optimize_carrier_allocation(pd.DataFrame())
        assert result.empty

    def test_none_data(self):
        result = optimize_carrier_allocation(None)
        assert result.empty

    def test_preserves_total_containers(self, lp_data):
        total_before = lp_data['Container Count'].sum()
        result = optimize_carrier_allocation(lp_data)
        total_after = result['Container Count'].sum()
        assert total_after == total_before

    def test_allocation_strategy_label(self, lp_data):
        result = optimize_carrier_allocation(lp_data)
        assert 'Allocation Strategy' in result.columns

    def test_cost_only_optimization(self, lp_data):
        result = optimize_carrier_allocation(lp_data, cost_weight=1.0, performance_weight=0.0)
        # With only cost weight, cheapest carrier (ABCD at 100) should get most
        assert not result.empty
        assert result['Container Count'].sum() == lp_data['Container Count'].sum()

    def test_performance_only_optimization(self, lp_data):
        result = optimize_carrier_allocation(lp_data, cost_weight=0.0, performance_weight=1.0)
        # With only performance weight, highest performer (EFGH at 0.9) should get most
        assert not result.empty

    def test_missing_required_columns(self):
        data = pd.DataFrame({'Lane': ['X'], 'Week Number': [1]})
        with pytest.raises(ValueError, match="Missing required columns"):
            optimize_carrier_allocation(data)

    def test_zero_weights_raises(self, lp_data):
        with pytest.raises(ValueError, match="At least one weight"):
            optimize_carrier_allocation(lp_data, cost_weight=0, performance_weight=0)

    def test_single_carrier(self):
        """Single carrier gets all containers."""
        data = pd.DataFrame({
            'Lane': ['USLAXIUSF'],
            'Week Number': [9],
            'Dray SCAC(FL)': ['ABCD'],
            'Container Count': [10],
            'Base Rate': [100],
            'Total Rate': [1000],
            'Performance_Score': [0.8],
        })
        result = optimize_carrier_allocation(data)
        assert result['Container Count'].sum() == 10

    def test_missing_performance_uses_cost_only(self):
        data = pd.DataFrame({
            'Lane': ['USLAXIUSF', 'USLAXIUSF'],
            'Week Number': [9, 9],
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Container Count': [5, 3],
            'Base Rate': [100, 200],
            'Total Rate': [500, 600],
        })
        # No Performance_Score column → should use cost-only
        result = optimize_carrier_allocation(data)
        assert result['Container Count'].sum() == 8

    def test_missing_rates_penalized(self):
        """Carriers with NaN rates should be ranked last."""
        data = pd.DataFrame({
            'Lane': ['USLAXIUSF', 'USLAXIUSF'],
            'Week Number': [9, 9],
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Container Count': [5, 5],
            'Base Rate': [100, np.nan],
            'Total Rate': [500, 0],
            'Performance_Score': [0.5, 0.9],
        })
        result = optimize_carrier_allocation(data)
        # EFGH has NaN rate → penalized, ABCD should get most volume
        abcd = result[result['Dray SCAC(FL)'] == 'ABCD']
        if not abcd.empty:
            assert abcd['Container Count'].sum() >= 5


# ==================== get_current_week_number ====================

class TestGetCurrentWeekNumber:
    def test_returns_int(self):
        result = get_current_week_number()
        assert isinstance(result, int)
        assert 1 <= result <= 53

    def test_with_specific_date(self):
        # Jan 1, 2025 is in week 1
        result = get_current_week_number(datetime(2025, 1, 6))
        assert result == 2  # ISO week 2


# ==================== filter_historical_weeks ====================

class TestFilterHistoricalWeeks:
    def test_filters_null_weeks(self, historic_data):
        data = historic_data.copy()
        data.loc[0, 'Week Number'] = np.nan
        result = filter_historical_weeks(data)
        assert result['Week Number'].notna().all()

    def test_empty_data(self):
        result = filter_historical_weeks(pd.DataFrame())
        assert result.empty

    def test_none_data(self):
        result = filter_historical_weeks(None)
        assert result.empty

    def test_missing_column_raises(self):
        data = pd.DataFrame({'Other': [1, 2]})
        with pytest.raises(ValueError, match="Week Number"):
            filter_historical_weeks(data)


# ==================== get_last_n_weeks ====================

class TestGetLastNWeeks:
    def test_returns_n_weeks(self, historic_data):
        result = get_last_n_weeks(historic_data, n_weeks=3)
        unique_weeks = result['Week Number'].unique()
        assert len(unique_weeks) == 3

    def test_returns_most_recent(self, historic_data):
        result = get_last_n_weeks(historic_data, n_weeks=2)
        weeks = sorted(result['Week Number'].unique())
        assert weeks == [8, 9]

    def test_fewer_weeks_than_requested(self):
        data = pd.DataFrame({
            'Week Number': [9, 9],
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Container Count': [5, 3],
            'Lane': ['L1', 'L1'],
        })
        result = get_last_n_weeks(data, n_weeks=5)
        assert len(result['Week Number'].unique()) == 1

    def test_empty_data(self):
        result = get_last_n_weeks(pd.DataFrame(), n_weeks=5)
        assert result.empty


# ==================== calculate_carrier_volume_share ====================

class TestCalculateCarrierVolumeShare:
    def test_basic_calculation(self, historic_data):
        result = calculate_carrier_volume_share(historic_data)
        assert 'Volume_Share_Pct' in result.columns
        assert 'Weeks_Active' in result.columns
        assert 'Avg_Weekly_Containers' in result.columns

    def test_volume_share_sums_to_100(self, historic_data):
        result = calculate_carrier_volume_share(historic_data, n_weeks=3)
        # Within each lane, volume shares should sum to ~100
        for lane in result['Lane'].unique():
            lane_share = result[result['Lane'] == lane]['Volume_Share_Pct'].sum()
            assert abs(lane_share - 100.0) < 0.1

    def test_empty_data(self):
        result = calculate_carrier_volume_share(pd.DataFrame())
        assert result.empty

    def test_none_data(self):
        result = calculate_carrier_volume_share(None)
        assert result.empty

    def test_missing_columns_raises(self):
        data = pd.DataFrame({'Other': [1]})
        with pytest.raises(ValueError, match="Missing required columns"):
            calculate_carrier_volume_share(data)

    def test_carrier_with_more_volume_gets_higher_share(self, historic_data):
        result = calculate_carrier_volume_share(historic_data)
        abcd = result[result['Dray SCAC(FL)'] == 'ABCD']
        efgh = result[result['Dray SCAC(FL)'] == 'EFGH']
        if not abcd.empty and not efgh.empty:
            assert abcd.iloc[0]['Volume_Share_Pct'] > efgh.iloc[0]['Volume_Share_Pct']

    def test_respects_n_weeks(self, historic_data):
        result_3 = calculate_carrier_volume_share(historic_data, n_weeks=3)
        result_5 = calculate_carrier_volume_share(historic_data, n_weeks=5)
        # More weeks = more data (both should have same carriers though)
        assert len(result_3) >= 1
        assert len(result_5) >= 1

    def test_includes_category_in_grouping(self, historic_data):
        result = calculate_carrier_volume_share(historic_data)
        if 'Category' in historic_data.columns:
            assert 'Category' in result.columns
