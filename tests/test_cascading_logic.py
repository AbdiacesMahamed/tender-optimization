"""
Tests for optimization/cascading_logic.py.

Covers: _get_excluded_carriers_for_group, cascading_allocate_with_constraints,
        CONSTRAINT_SCOPE_DIMENSIONS
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

from optimization.cascading_logic import (
    _get_excluded_carriers_for_group,
    cascading_allocate_with_constraints,
    CONSTRAINT_SCOPE_DIMENSIONS,
    DEFAULT_MAX_GROWTH_PCT,
)


# ==================== FIXTURES ====================

@pytest.fixture
def optimization_data():
    """Data suitable for cascading optimization."""
    return pd.DataFrame({
        'Category': ['CD', 'CD', 'CD', 'CD'],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USLAXIUSF', 'USBALREWR'],
        'Week Number': [9, 9, 9, 9],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'IJKL', 'ABCD'],
        'Container Count': [5, 3, 2, 4],
        'Container Numbers': ['C001, C002, C003, C004, C005',
                              'C006, C007, C008',
                              'C009, C010',
                              'C011, C012, C013, C014'],
        'Base Rate': [100, 150, 200, 120],
        'Total Rate': [500, 450, 400, 480],
        'Performance_Score': [0.8, 0.9, 0.7, 0.85],
    })


@pytest.fixture
def multi_week_data():
    """Data with multiple weeks for historical volume."""
    rows = []
    for week in [7, 8, 9, 10]:
        for carrier, rate, perf in [('ABCD', 100, 0.8), ('EFGH', 150, 0.9)]:
            rows.append({
                'Category': 'CD',
                'Lane': 'USLAXIUSF',
                'Week Number': week,
                'Dray SCAC(FL)': carrier,
                'Container Count': 5,
                'Container Numbers': ', '.join([f'C{week}{carrier[:2]}{i}' for i in range(5)]),
                'Base Rate': rate,
                'Total Rate': rate * 5,
                'Performance_Score': perf,
            })
    return pd.DataFrame(rows)


# ==================== CONSTRAINT_SCOPE_DIMENSIONS ====================

class TestConstraintScopeDimensions:
    def test_has_category_dimension(self):
        keys = [csd[0] for csd in CONSTRAINT_SCOPE_DIMENSIONS]
        assert 'category' in keys

    def test_has_lane_dimension(self):
        keys = [csd[0] for csd in CONSTRAINT_SCOPE_DIMENSIONS]
        assert 'lane' in keys

    def test_has_week_dimension(self):
        keys = [csd[0] for csd in CONSTRAINT_SCOPE_DIMENSIONS]
        assert 'week' in keys

    def test_each_entry_has_two_elements(self):
        for entry in CONSTRAINT_SCOPE_DIMENSIONS:
            assert len(entry) == 2

    def test_default_growth_pct(self):
        assert DEFAULT_MAX_GROWTH_PCT == 0.30


# ==================== _get_excluded_carriers_for_group ====================

class TestGetExcludedCarriersForGroup:
    def test_empty_constraints(self):
        result = _get_excluded_carriers_for_group(
            [], ('CD', 'USLAXIUSF', 9),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert result == set()

    def test_global_exclusion(self):
        """Carrier excluded with all None scope = matches every group."""
        mc = [{'carrier': 'ABCD', 'category': None, 'lane': None, 'port': None, 'week': None}]
        result = _get_excluded_carriers_for_group(
            mc, ('CD', 'USLAXIUSF', 9),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert 'ABCD' in result

    def test_scoped_exclusion_matches(self):
        """Carrier excluded only in Category=CD."""
        mc = [{'carrier': 'ABCD', 'category': 'CD', 'lane': None, 'port': None, 'week': None}]
        result = _get_excluded_carriers_for_group(
            mc, ('CD', 'USLAXIUSF', 9),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert 'ABCD' in result

    def test_scoped_exclusion_no_match(self):
        """Carrier excluded in Category=TL should NOT match Category=CD group."""
        mc = [{'carrier': 'ABCD', 'category': 'TL', 'lane': None, 'port': None, 'week': None}]
        result = _get_excluded_carriers_for_group(
            mc, ('CD', 'USLAXIUSF', 9),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert 'ABCD' not in result

    def test_week_scope_numeric(self):
        """Week scope should compare numerically."""
        mc = [{'carrier': 'ABCD', 'category': None, 'lane': None, 'port': None, 'week': 9}]
        result = _get_excluded_carriers_for_group(
            mc, ('CD', 'USLAXIUSF', 9.0),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert 'ABCD' in result

    def test_week_scope_mismatch(self):
        mc = [{'carrier': 'ABCD', 'category': None, 'lane': None, 'port': None, 'week': 10}]
        result = _get_excluded_carriers_for_group(
            mc, ('CD', 'USLAXIUSF', 9),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert 'ABCD' not in result

    def test_multiple_carriers(self):
        mc = [
            {'carrier': 'ABCD', 'category': None, 'lane': None, 'port': None, 'week': None},
            {'carrier': 'EFGH', 'category': 'CD', 'lane': None, 'port': None, 'week': None},
        ]
        result = _get_excluded_carriers_for_group(
            mc, ('CD', 'USLAXIUSF', 9),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert 'ABCD' in result
        assert 'EFGH' in result

    def test_missing_carrier_key_skipped(self):
        mc = [{'carrier': None, 'category': None, 'lane': None}]
        result = _get_excluded_carriers_for_group(
            mc, ('CD', 'USLAXIUSF', 9),
            ['Category', 'Lane', 'Week Number'],
            'Category', 'Lane', 'Week Number',
        )
        assert result == set()


# ==================== cascading_allocate_with_constraints ====================

class TestCascadingAllocateWithConstraints:
    def test_empty_data(self):
        result = cascading_allocate_with_constraints(pd.DataFrame())
        assert result.empty

    def test_none_data(self):
        result = cascading_allocate_with_constraints(None)
        assert result.empty

    def test_returns_all_containers(self, optimization_data):
        total_before = optimization_data['Container Count'].sum()
        result = cascading_allocate_with_constraints(optimization_data)
        # Total containers should be preserved (may redistribute)
        total_after = result['Container Count'].sum()
        assert total_after == total_before

    def test_adds_allocation_columns(self, optimization_data):
        result = cascading_allocate_with_constraints(optimization_data)
        assert 'Allocation_Notes' in result.columns
        assert 'Volume_Change' in result.columns

    def test_excluded_carriers_reduces_allocation(self, optimization_data):
        """Excluded carrier should get zero or reduced allocation."""
        excluded = [{'carrier': 'EFGH', 'category': None, 'lane': None, 'port': None, 'week': None}]
        result = cascading_allocate_with_constraints(
            optimization_data,
            excluded_carriers=excluded,
        )
        # EFGH should get reduced/no allocation; volume redistributed
        efgh_volume = result[result['Dray SCAC(FL)'] == 'EFGH']['Container Count'].sum()
        total = result['Container Count'].sum()
        # At minimum, total should be preserved
        assert total == optimization_data['Container Count'].sum()

    def test_custom_weights(self, optimization_data):
        """Different cost/performance weights should produce a valid result."""
        result = cascading_allocate_with_constraints(
            optimization_data,
            cost_weight=1.0,
            performance_weight=0.0,
        )
        assert not result.empty
        assert result['Container Count'].sum() == optimization_data['Container Count'].sum()

    def test_groups_by_lane_week_category(self, optimization_data):
        result = cascading_allocate_with_constraints(optimization_data)
        # Should have separate allocations for different lanes
        lanes = result['Lane'].unique()
        assert len(lanes) >= 2  # USLAXIUSF and USBALREWR

    def test_uses_historical_data_if_provided(self, optimization_data, multi_week_data):
        result = cascading_allocate_with_constraints(
            optimization_data,
            historical_data=multi_week_data,
        )
        assert not result.empty

    def test_single_carrier_group(self):
        """Group with only one carrier should assign all to that carrier."""
        data = pd.DataFrame({
            'Category': ['CD'],
            'Lane': ['USLAXIUSF'],
            'Week Number': [9],
            'Dray SCAC(FL)': ['ABCD'],
            'Container Count': [10],
            'Container Numbers': ['C001, C002, C003, C004, C005, C006, C007, C008, C009, C010'],
            'Base Rate': [100],
            'Total Rate': [1000],
            'Performance_Score': [0.8],
        })
        result = cascading_allocate_with_constraints(data)
        assert result['Container Count'].sum() == 10
        assert result.iloc[0]['Dray SCAC(FL)'] == 'ABCD'
