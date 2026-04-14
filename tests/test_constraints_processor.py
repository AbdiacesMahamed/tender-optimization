"""
Tests for components/constraints_processor.py.

Covers: allocate_specific_containers, process_constraints_file, apply_constraints_to_data
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

# Mock streamlit before importing
from unittest.mock import MagicMock, patch
sys.modules['streamlit'] = MagicMock()
import streamlit as st
st.cache_data = lambda **kwargs: (lambda f: f)

from components.constraints_processor import (
    allocate_specific_containers,
    apply_constraints_to_data,
)


# ==================== FIXTURES ====================

@pytest.fixture
def sample_data():
    """Sample comprehensive data for constraint testing."""
    return pd.DataFrame({
        'Category': ['CD', 'CD', 'CD', 'TL', 'TL'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'ABCD', 'EFGH', 'IJKL'],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USBALREWR', 'USLAXIUSF', 'USBALREWR'],
        'Discharged Port': ['LAX', 'LAX', 'BAL', 'LAX', 'BAL'],
        'Week Number': [9, 9, 9, 9, 10],
        'Facility': ['IUSF-5', 'IUSF-5', 'Amazon REWR', 'IUSF-5', 'Amazon REWR'],
        'Container Numbers': ['C001, C002, C003', 'C004, C005', 'C006, C007', 'C008, C009', 'C010'],
        'Container Count': [3, 2, 2, 2, 1],
        'Base Rate': [100, 200, 150, 200, 180],
        'Total Rate': [300, 400, 300, 400, 180],
    })


@pytest.fixture
def max_constraint():
    """Simple maximum container count constraint."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['ABCD'],
        'Maximum Container Count': [2],
        'Minimum Container Count': [None],
        'Percent Allocation': [None],
        'Category': [None],
        'Lane': [None],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': [None],
    })


@pytest.fixture
def scoped_max_constraint():
    """Maximum constraint scoped to a specific category and lane."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['ABCD'],
        'Maximum Container Count': [1],
        'Minimum Container Count': [None],
        'Percent Allocation': [None],
        'Category': ['CD'],
        'Lane': ['USLAXIUSF'],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': [None],
    })


@pytest.fixture
def percent_constraint():
    """Percent allocation constraint."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['EFGH'],
        'Maximum Container Count': [None],
        'Minimum Container Count': [None],
        'Percent Allocation': [50],  # 50%
        'Category': [None],
        'Lane': [None],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': [None],
    })


@pytest.fixture
def excluded_fc_constraint():
    """Excluded facility constraint."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['ABCD'],
        'Maximum Container Count': [None],
        'Minimum Container Count': [None],
        'Percent Allocation': [None],
        'Category': [None],
        'Lane': [None],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': ['IUSF'],
    })


# ==================== allocate_specific_containers ====================

class TestAllocateSpecificContainers:
    def test_allocate_subset(self):
        row = pd.Series({'Container Numbers': 'C001, C002, C003'})
        tracker = {}
        allocated, remaining = allocate_specific_containers(row, 2, tracker, 'ABCD', 9)
        assert len(allocated) == 2
        assert len(remaining) == 1
        assert 'C001' in tracker
        assert 'C002' in tracker

    def test_allocate_all(self):
        row = pd.Series({'Container Numbers': 'C001, C002'})
        tracker = {}
        allocated, remaining = allocate_specific_containers(row, 5, tracker, 'ABCD', 9)
        assert len(allocated) == 2
        assert len(remaining) == 0

    def test_skip_already_allocated(self):
        row = pd.Series({'Container Numbers': 'C001, C002, C003'})
        tracker = {'C001': {'carrier': 'EFGH', 'week': 9, 'row_idx': None}}
        allocated, remaining = allocate_specific_containers(row, 2, tracker, 'ABCD', 9)
        assert 'C001' not in allocated
        assert len(allocated) == 2  # C002 and C003

    def test_empty_container_string(self):
        row = pd.Series({'Container Numbers': ''})
        tracker = {}
        allocated, remaining = allocate_specific_containers(row, 2, tracker, 'ABCD', 9)
        assert len(allocated) == 0
        assert len(remaining) == 0

    def test_tracker_records_metadata(self):
        row = pd.Series({'Container Numbers': 'C001'})
        tracker = {}
        allocate_specific_containers(row, 1, tracker, 'ABCD', 9)
        assert tracker['C001']['carrier'] == 'ABCD'
        assert tracker['C001']['week'] == 9


# ==================== apply_constraints_to_data ====================

class TestApplyConstraintsToData:
    def test_no_constraints(self, sample_data):
        constrained, unconstrained, summary, max_carriers, exclusions, logs = \
            apply_constraints_to_data(sample_data, None)
        assert len(constrained) == 0
        assert len(unconstrained) == len(sample_data)

    def test_max_constraint_allocates_correct_count(self, sample_data, max_constraint):
        constrained, unconstrained, summary, max_carriers, exclusions, logs = \
            apply_constraints_to_data(sample_data, max_constraint)
        assert constrained['Container Count'].sum() == 2
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'ABCD'

    def test_max_constraint_adds_to_exclusion_list(self, sample_data, max_constraint):
        _, _, _, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, max_constraint)
        assert len(max_carriers) == 1
        assert max_carriers[0]['carrier'] == 'ABCD'

    def test_max_constraint_scope_stored(self, sample_data, scoped_max_constraint):
        _, _, _, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, scoped_max_constraint)
        assert max_carriers[0]['category'] == 'CD'
        assert max_carriers[0]['lane'] == 'USLAXIUSF'
        assert max_carriers[0]['week'] is None  # wildcard

    def test_containers_preserved_after_constraints(self, sample_data, max_constraint):
        original_total = sample_data['Container Count'].sum()
        constrained, unconstrained, _, _, _, _ = \
            apply_constraints_to_data(sample_data, max_constraint)
        after_total = constrained['Container Count'].sum() + unconstrained['Container Count'].sum()
        assert after_total == original_total

    def test_percent_allocation(self, sample_data, percent_constraint):
        constrained, unconstrained, summary, _, _, _ = \
            apply_constraints_to_data(sample_data, percent_constraint)
        total = sample_data['Container Count'].sum()
        assert constrained['Container Count'].sum() >= 1
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'EFGH'

    def test_excluded_fc_creates_exclusion_dict(self, sample_data, excluded_fc_constraint):
        _, _, _, _, exclusions, _ = \
            apply_constraints_to_data(sample_data, excluded_fc_constraint)
        assert 'ABCD' in exclusions
        assert 'IUSF' in exclusions['ABCD']

    def test_multiple_constraints_priority_order(self, sample_data):
        constraints = pd.DataFrame({
            'Priority Score': [10, 5],
            'Carrier': ['ABCD', 'EFGH'],
            'Maximum Container Count': [2, 1],
            'Minimum Container Count': [None, None],
            'Percent Allocation': [None, None],
            'Category': [None, None],
            'Lane': [None, None],
            'Port': [None, None],
            'Week Number': [None, None],
            'Terminal': [None, None],
            'SSL': [None, None],
            'Vessel': [None, None],
            'Excluded FC': [None, None],
        })
        constrained, _, summary, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, constraints)
        # Higher priority constraint (10) processed first
        assert summary[0]['priority'] == 10

    def test_empty_constraints_df(self, sample_data):
        empty_constraints = pd.DataFrame()
        constrained, unconstrained, _, _, _, _ = \
            apply_constraints_to_data(sample_data, empty_constraints)
        assert len(constrained) == 0
        assert len(unconstrained) == len(sample_data)

    def test_minimum_constraint(self, sample_data):
        constraints = pd.DataFrame({
            'Priority Score': [10],
            'Carrier': ['EFGH'],
            'Maximum Container Count': [None],
            'Minimum Container Count': [3],
            'Percent Allocation': [None],
            'Category': [None],
            'Lane': [None],
            'Port': [None],
            'Week Number': [None],
            'Terminal': [None],
            'SSL': [None],
            'Vessel': [None],
            'Excluded FC': [None],
        })
        constrained, _, summary, _, _, _ = \
            apply_constraints_to_data(sample_data, constraints)
        assert constrained['Container Count'].sum() == 3
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'EFGH'
