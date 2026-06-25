"""
Tests for components/peel_pile.py.

Covers: _peel_pile_key, apply_peel_pile_as_constraints
"""
import pandas as pd
import numpy as np
import pytest

from unittest.mock import MagicMock, patch

# Streamlit is stubbed centrally in tests/conftest.py before any first-party import.

from components.constraints.peel_pile import _peel_pile_key, apply_peel_pile_as_constraints
import components.constraints.peel_pile as peel_pile_module


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


class TestPeelPileRespectsMaxCeilings:
    """A peel pile assignment must NOT bust a max cap the user already set via a file
    constraint. The dashboard pre-computes scoped_max_ceilings (with file-constrained
    volume pre-credited) and passes them in; the peel pile clamps to the headroom and
    leaves over-cap volume unconstrained."""

    def _make_st_mock(self, session_data):
        m = MagicMock()
        m.session_state = session_data
        return m

    def _data(self):
        # 6 rows × 5 containers = 30 on one peel pile group, all currently 'OLD'.
        return pd.DataFrame({
            'Vessel': ['SHIP_A'] * 6,
            'Category': ['CD'] * 6,
            'Week Number': [9.0] * 6,
            'Discharged Port': ['LAX'] * 6,
            'Terminal': ['T1'] * 6,
            'Dray SCAC(FL)': ['OLD'] * 6,
            'Container Count': [5] * 6,
            'Container Numbers': [','.join(f"C{r*5+j:03d}" for j in range(5)) for r in range(6)],
            'Base Rate': [100] * 6,
            'Total Rate': [500] * 6,
        })

    def _ceilings(self, data, carrier, cap, **scope):
        from components.constraints.processor import compute_scoped_max_ceilings
        base = dict(zip(['Priority Score', 'Carrier', 'Maximum Container Count',
                         'Minimum Container Count', 'Percent Allocation', 'Category',
                         'Lane', 'Port', 'Week Number', 'Terminal', 'SSL', 'Vessel',
                         'Excluded FC'],
                        [10, carrier, cap, None, None, None, None, None, None, None,
                         None, None, None]))
        base.update(scope)
        return compute_scoped_max_ceilings(pd.DataFrame([base]), data)

    def test_clamps_assignment_to_cap(self):
        data = self._data()
        # Cap NEWC at 12 containers on SHIP_A; peel pile assigns the whole 30-container
        # group to NEWC. Only 12 may be locked; the rest stay unconstrained.
        ceilings = self._ceilings(data, 'NEWC', 12, Vessel='SHIP_A')
        key = (('Vessel', 'SHIP_A'), ('Category', 'CD'), ('Week Number', '9.0'),
               ('Discharged Port', 'LAX'), ('Terminal', 'T1'))
        with patch.object(peel_pile_module, 'st',
                          self._make_st_mock({'peel_pile_allocations': {key: ['NEWC']}})):
            con, unc, summary, carriers = apply_peel_pile_as_constraints(
                data, pd.DataFrame(), data.copy(), [], scoped_max_ceilings=ceilings)
        newc = con[con['Dray SCAC(FL)'] == 'NEWC']['Container Count'].sum() if len(con) else 0
        assert newc == 12, f"peel pile busted the cap: {newc}"
        # Conservation: the other 18 containers stay unconstrained.
        tot = (con['Container Count'].sum() if len(con) else 0) + \
              (unc['Container Count'].sum() if len(unc) else 0)
        assert tot == 30

    def test_no_ceiling_assigns_all(self):
        # Without a conflicting cap, the whole group is assigned (regression guard that
        # the clamp path doesn't drop volume when no ceiling binds).
        data = self._data()
        key = (('Vessel', 'SHIP_A'), ('Category', 'CD'), ('Week Number', '9.0'),
               ('Discharged Port', 'LAX'), ('Terminal', 'T1'))
        with patch.object(peel_pile_module, 'st',
                          self._make_st_mock({'peel_pile_allocations': {key: ['NEWC']}})):
            con, unc, summary, carriers = apply_peel_pile_as_constraints(
                data, pd.DataFrame(), data.copy(), [], scoped_max_ceilings=[])
        assert con[con['Dray SCAC(FL)'] == 'NEWC']['Container Count'].sum() == 30

    def test_cap_already_full_leaves_all_unconstrained(self):
        # If the file pass already used the entire cap, peel pile gets zero headroom.
        data = self._data()
        ceilings = self._ceilings(data, 'NEWC', 12, Vessel='SHIP_A')
        for c in ceilings:
            c['allocated'] = 12  # cap fully consumed by the file pass
        key = (('Vessel', 'SHIP_A'), ('Category', 'CD'), ('Week Number', '9.0'),
               ('Discharged Port', 'LAX'), ('Terminal', 'T1'))
        with patch.object(peel_pile_module, 'st',
                          self._make_st_mock({'peel_pile_allocations': {key: ['NEWC']}})):
            con, unc, summary, carriers = apply_peel_pile_as_constraints(
                data, pd.DataFrame(), data.copy(), [], scoped_max_ceilings=ceilings)
        newc = con[con['Dray SCAC(FL)'] == 'NEWC']['Container Count'].sum() if len(con) else 0
        assert newc == 0
        assert unc['Container Count'].sum() == 30
