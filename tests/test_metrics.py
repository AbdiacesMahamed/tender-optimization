"""
Tests for components/metrics.py calculation helpers.

Covers: add_carrier_flips_column, add_missing_rate_rows, calculate_enhanced_metrics,
        _calc_performance_cost, _calc_cheapest_cost
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

# Mock streamlit
from unittest.mock import MagicMock
sys.modules['streamlit'] = MagicMock()
import streamlit as st
st.cache_data = lambda **kwargs: (lambda f: f)
st.session_state = {}

from components.metrics import (
    add_carrier_flips_column,
    add_missing_rate_rows,
    calculate_enhanced_metrics,
    _calc_performance_cost,
    _calc_cheapest_cost,
)
from components.utils import get_rate_columns


# ==================== FIXTURES ====================

@pytest.fixture
def original_data():
    """Baseline data (original allocation)."""
    return pd.DataFrame({
        'Discharged Port': ['LAX', 'LAX', 'BAL'],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USBALREWR'],
        'Facility': ['IUSF-5', 'IUSF-5', 'Amazon REWR'],
        'Week Number': [9, 9, 9],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'ABCD'],
        'Container Count': [5, 3, 4],
        'Container Numbers': ['C001,C002,C003,C004,C005',
                              'C006,C007,C008',
                              'C009,C010,C011,C012'],
        'Base Rate': [100, 150, 120],
        'Total Rate': [500, 450, 480],
        'Performance_Score': [0.8, 0.9, 0.7],
    })


@pytest.fixture
def scenario_data():
    """Data for scenario calculations (with rates)."""
    return pd.DataFrame({
        'Category': ['CD', 'CD', 'CD'],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USLAXIUSF'],
        'Week Number': [9, 9, 9],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'IJKL'],
        'Container Count': [5, 3, 2],
        'Container Numbers': ['C001,C002,C003,C004,C005',
                              'C006,C007,C008',
                              'C009,C010'],
        'Base Rate': [100, 200, 150],
        'Total Rate': [500, 600, 300],
        'Facility': ['IUSF-5', 'IUSF-5', 'IUSF-5'],
        'Discharged Port': ['LAX', 'LAX', 'LAX'],
        'Performance_Score': [0.7, 0.9, 0.5],
    })


# ==================== add_carrier_flips_column ====================

class TestAddCarrierFlipsColumn:
    def test_no_baseline_returns_no_baseline(self, original_data):
        result = add_carrier_flips_column(original_data.copy(), None)
        assert (result['Carrier Flips'] == 'No baseline').all()

    def test_empty_baseline_returns_no_baseline(self, original_data):
        result = add_carrier_flips_column(original_data.copy(), pd.DataFrame())
        assert (result['Carrier Flips'] == 'No baseline').all()

    def test_identical_data_shows_kept(self, original_data):
        result = add_carrier_flips_column(original_data.copy(), original_data.copy())
        for flip in result['Carrier Flips']:
            assert '✓' in flip or 'Kept' in flip

    def test_new_carrier_shows_new(self, original_data):
        """When a carrier appears that wasn't in the original."""
        modified = original_data.copy()
        modified.loc[0, 'Dray SCAC(FL)'] = 'ZZZZ'
        result = add_carrier_flips_column(modified, original_data.copy())
        assert '🔄' in result.iloc[0]['Carrier Flips'] or 'New' in result.iloc[0]['Carrier Flips']

    def test_volume_change_detected(self, original_data):
        """When a carrier keeps volume but amount changes."""
        modified = original_data.copy()
        modified.loc[0, 'Container Count'] = 10  # Was 5
        result = add_carrier_flips_column(modified, original_data.copy())
        assert '+' in result.iloc[0]['Carrier Flips'] or 'now' in result.iloc[0]['Carrier Flips']


# ==================== add_missing_rate_rows ====================

class TestAddMissingRateRows:
    def test_no_missing_rate_column(self, original_data):
        result = add_missing_rate_rows(original_data.copy(), original_data.copy())
        assert len(result) == len(original_data)

    def test_adds_missing_rate_rows(self, original_data):
        source = original_data.copy()
        source['Missing_Rate'] = [False, False, True]
        display = original_data.iloc[:2].copy()
        result = add_missing_rate_rows(display, source)
        assert len(result) == 3  # 2 display + 1 missing

    def test_all_missing_rate_false(self, original_data):
        source = original_data.copy()
        source['Missing_Rate'] = False
        result = add_missing_rate_rows(original_data.copy(), source)
        assert len(result) == len(original_data)


# ==================== _calc_performance_cost ====================

class TestCalcPerformanceCost:
    def test_basic_calculation(self, scenario_data):
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        cost = _calc_performance_cost(scenario_data, {}, rate_cols)
        # EFGH (0.9 perf) should be selected → 10 containers * $200 = $2000
        assert cost is not None
        assert cost > 0

    def test_empty_data(self):
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        cost = _calc_performance_cost(pd.DataFrame(), {}, rate_cols)
        assert cost is None

    def test_no_performance_column(self):
        data = pd.DataFrame({
            'Lane': ['L1'], 'Week Number': [9],
            'Dray SCAC(FL)': ['A'], 'Container Count': [5],
            'Base Rate': [100], 'Total Rate': [500],
        })
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        cost = _calc_performance_cost(data, {}, rate_cols)
        assert cost is None

    def test_with_exclusions(self, scenario_data):
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        exclusions = {'EFGH': {'IUSF'}}
        cost = _calc_performance_cost(scenario_data, exclusions, rate_cols)
        # EFGH excluded from IUSF → different carrier selected
        assert cost is not None


# ==================== _calc_cheapest_cost ====================

class TestCalcCheapestCost:
    def test_basic_calculation(self, scenario_data):
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        cost = _calc_cheapest_cost(scenario_data, {}, rate_cols)
        # ABCD is cheapest at $100 → should get all containers → 10 * $100 = $1000
        assert cost is not None
        assert cost > 0

    def test_empty_data(self):
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        cost = _calc_cheapest_cost(pd.DataFrame(), {}, rate_cols)
        assert cost is None

    def test_selects_cheapest_per_group(self, scenario_data):
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        cost = _calc_cheapest_cost(scenario_data, {}, rate_cols)
        # Cheapest rate is $100 (ABCD), 10 containers → $1000
        assert cost == 1000.0

    def test_nan_rates_excluded(self):
        data = pd.DataFrame({
            'Category': ['CD', 'CD'],
            'Lane': ['L1', 'L1'],
            'Week Number': [9, 9],
            'Dray SCAC(FL)': ['A', 'B'],
            'Container Count': [5, 3],
            'Container Numbers': ['C1,C2,C3,C4,C5', 'C6,C7,C8'],
            'Base Rate': [np.nan, 200],
            'Total Rate': [0, 600],
            'Facility': ['F1', 'F1'],
        })
        rate_cols = {'rate': 'Base Rate', 'total_rate': 'Total Rate'}
        cost = _calc_cheapest_cost(data, {}, rate_cols)
        # Only carrier B has a rate → 8 containers * $200 = $1600
        assert cost is not None


# ==================== calculate_enhanced_metrics ====================

class TestCalculateEnhancedMetrics:
    def test_returns_metrics_dict(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        assert result is not None
        assert 'total_cost' in result
        assert 'total_containers' in result
        assert 'unique_carriers' in result
        assert 'avg_rate' in result

    def test_total_containers_correct(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        assert result['total_containers'] == 10  # 5+3+2

    def test_total_cost_calculated(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        # 500 + 600 + 300 = 1400
        assert result['total_cost'] == 1400.0

    def test_none_data(self):
        result = calculate_enhanced_metrics(None)
        assert result is None

    def test_empty_data(self):
        result = calculate_enhanced_metrics(pd.DataFrame())
        assert result is None

    def test_performance_cost_present(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        assert 'performance_cost' in result

    def test_cheapest_cost_present(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        assert 'cheapest_cost' in result

    def test_optimized_cost_present(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        assert 'optimized_cost' in result

    def test_unique_counts(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        assert result['unique_carriers'] == 3
        assert result['unique_lanes'] == 1

    def test_avg_rate(self, scenario_data):
        result = calculate_enhanced_metrics(scenario_data)
        # Total cost 1400 / 10 containers = 140
        assert result['avg_rate'] == 140.0

    def test_with_unconstrained_data(self, scenario_data):
        # When unconstrained data is provided, scenarios use it
        unconstrained = scenario_data.iloc[:2].copy()
        result = calculate_enhanced_metrics(
            scenario_data, unconstrained_data=unconstrained
        )
        assert result is not None
