"""
Tests for components/peel_pile.py.

Covers: _peel_pile_key, apply_peel_pile_as_constraints
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

from unittest.mock import MagicMock, patch

from components.peel_pile import _peel_pile_key, apply_peel_pile_as_constraints
import components.peel_pile as peel_pile_module


# ==================== FIXTURES ====================

@pytest.fixture
def peel_data():
    """Unconstrained data mimicking peel pile rows."""
    return pd.DataFrame({
        'Vessel': ['SHIP_A'] * 6,
        'Category': ['CD'] * 6,
        'Week Number': [9.0] * 6,
        'Discharged Port': ['LAX'] * 6,
        'Terminal': ['T1'] * 6,
        'Dray SCAC(FL)': ['ABCD', 'ABCD', 'EFGH', 'EFGH', 'IJKL', 'IJKL'],
        'Container Count': [5, 5, 5, 5, 5, 5],
        'Container Numbers': ['C001,C002,C003,C004,C005',
                              'C006,C007,C008,C009,C010',
                              'C011,C012,C013,C014,C015',
                              'C016,C017,C018,C019,C020',
                              'C021,C022,C023,C024,C025',
                              'C026,C027,C028,C029,C030'],
        'Base Rate': [100, 100, 150, 150, 200, 200],
        'Total Rate': [500, 500, 750, 750, 1000, 1000],
    })


# ==================== _peel_pile_key ====================

class TestPeelPileKey:
    def test_basic_key(self):
        row = pd.Series({'Vessel': 'SHIP_A', 'Week Number': 9, 'Discharged Port': 'LAX'})
        group_cols = ['Vessel', 'Week Number', 'Discharged Port']
        key = _peel_pile_key(row, group_cols)
        assert key == (('Vessel', 'SHIP_A'), ('Week Number', '9'), ('Discharged Port', 'LAX'))

    def test_key_is_hashable(self):
        row = pd.Series({'Vessel': 'X', 'Week Number': 1})
        key = _peel_pile_key(row, ['Vessel', 'Week Number'])
        # Should be usable as dict key
        d = {key: 'value'}
        assert d[key] == 'value'

    def test_missing_column_uses_empty_string(self):
        row = pd.Series({'Vessel': 'X'})
        key = _peel_pile_key(row, ['Vessel', 'MissingCol'])
        assert key == (('Vessel', 'X'), ('MissingCol', ''))


# ==================== apply_peel_pile_as_constraints ====================

class TestApplyPeelPileAsConstraints:
    def _make_st_mock(self, session_data):
        """Create a streamlit mock with given session_state data."""
        mock_st = MagicMock()
        mock_st.session_state = session_data
        return mock_st

    def test_no_allocations(self, peel_data):
        with patch.object(peel_pile_module, 'st', self._make_st_mock({})):
            constrained, unconstrained, summary, carriers = apply_peel_pile_as_constraints(
                peel_data, pd.DataFrame(), peel_data.copy(), []
            )
        assert len(unconstrained) == len(peel_data)
        assert carriers == set()

    def test_single_carrier_allocation(self, peel_data):
        """Assign entire peel pile group to one carrier."""
        key = (('Vessel', 'SHIP_A'), ('Category', 'CD'), ('Week Number', '9.0'),
               ('Discharged Port', 'LAX'), ('Terminal', 'T1'))
        with patch.object(peel_pile_module, 'st', self._make_st_mock({'peel_pile_allocations': {key: ['NEWC']}})):
            constrained, unconstrained, summary, carriers = apply_peel_pile_as_constraints(
                peel_data, pd.DataFrame(), peel_data.copy(), []
            )
        # All 6 rows matched and moved to constrained
        assert len(constrained) == 6
        assert len(unconstrained) == 0
        assert 'NEWC' in carriers
        # All constrained rows should have carrier = NEWC
        assert (constrained['Dray SCAC(FL)'] == 'NEWC').all()

    def test_multi_carrier_split(self, peel_data):
        """Split peel pile across two carriers."""
        key = (('Vessel', 'SHIP_A'), ('Category', 'CD'), ('Week Number', '9.0'),
               ('Discharged Port', 'LAX'), ('Terminal', 'T1'))
        with patch.object(peel_pile_module, 'st', self._make_st_mock({'peel_pile_allocations': {key: ['CAR1', 'CAR2']}})):
            constrained, unconstrained, summary, carriers = apply_peel_pile_as_constraints(
                peel_data, pd.DataFrame(), peel_data.copy(), []
            )
        assert len(constrained) == 6  # 3 + 3 split
        assert len(unconstrained) == 0
        assert 'CAR1' in carriers
        assert 'CAR2' in carriers
        # Each carrier should get 3 rows
        assert (constrained['Dray SCAC(FL)'] == 'CAR1').sum() == 3
        assert (constrained['Dray SCAC(FL)'] == 'CAR2').sum() == 3

    def test_uneven_split(self):
        """Odd number of rows split across 2 carriers — remainder stays unconstrained."""
        data = pd.DataFrame({
            'Vessel': ['SHIP_A'] * 5,
            'Week Number': [9.0] * 5,
            'Discharged Port': ['LAX'] * 5,
            'Dray SCAC(FL)': ['X'] * 5,
            'Container Count': [2] * 5,
            'Container Numbers': ['CA, CB'] * 5,
            'Base Rate': [100] * 5,
            'Total Rate': [200] * 5,
        })
        key = (('Vessel', 'SHIP_A'), ('Week Number', '9.0'), ('Discharged Port', 'LAX'))
        with patch.object(peel_pile_module, 'st', self._make_st_mock({'peel_pile_allocations': {key: ['A', 'B']}})):
            constrained, unconstrained, summary, carriers = apply_peel_pile_as_constraints(
                data, pd.DataFrame(), data.copy(), []
            )
        # 5 rows: 3+2 or 2+3 split → one carrier gets 3, other gets 2
        total = len(constrained)
        assert total == 5
        a_count = (constrained['Dray SCAC(FL)'] == 'A').sum()
        b_count = (constrained['Dray SCAC(FL)'] == 'B').sum()
        assert a_count == 3  # First carrier gets the extra
        assert b_count == 2

    def test_constraint_summary_populated(self, peel_data):
        key = (('Vessel', 'SHIP_A'), ('Category', 'CD'), ('Week Number', '9.0'),
               ('Discharged Port', 'LAX'), ('Terminal', 'T1'))
        with patch.object(peel_pile_module, 'st', self._make_st_mock({'peel_pile_allocations': {key: ['NEWC']}})):
            _, _, summary, _ = apply_peel_pile_as_constraints(
                peel_data, pd.DataFrame(), peel_data.copy(), []
            )
        assert len(summary) == 1
        assert summary[0]['status'] == 'Applied'
        assert summary[0]['containers_allocated'] > 0

    def test_legacy_string_carrier_normalized(self, peel_data):
        """Legacy format where carrier is a string, not a list."""
        key = (('Vessel', 'SHIP_A'), ('Category', 'CD'), ('Week Number', '9.0'),
               ('Discharged Port', 'LAX'), ('Terminal', 'T1'))
        with patch.object(peel_pile_module, 'st', self._make_st_mock({'peel_pile_allocations': {key: 'OLDSTYLE'}})):
            constrained, unconstrained, summary, carriers = apply_peel_pile_as_constraints(
                peel_data, pd.DataFrame(), peel_data.copy(), []
            )
        assert 'OLDSTYLE' in carriers
        assert (constrained['Dray SCAC(FL)'] == 'OLDSTYLE').all()

    def test_no_match_does_nothing(self, peel_data):
        """Key that doesn't match any rows."""
        key = (('Vessel', 'NO_SHIP'), ('Week Number', '99'))
        with patch.object(peel_pile_module, 'st', self._make_st_mock({'peel_pile_allocations': {key: ['X']}})):
            constrained, unconstrained, summary, carriers = apply_peel_pile_as_constraints(
                peel_data, pd.DataFrame(), peel_data.copy(), []
            )
        assert len(unconstrained) == len(peel_data)
        assert carriers == set()
