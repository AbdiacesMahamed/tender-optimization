"""
Tests for components/filters.py — week-filter parsing and apply_filters_to_data.

Regression coverage for the bug where Week Number, being float-typed,
produced display strings like "5.0" that int() could not parse.
"""
import pandas as pd
import numpy as np
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

# Streamlit is stubbed centrally in tests/conftest.py. This test patches the `st`
# object inside the filters module directly via the fixture below.

from components.ui import filters as filters_module
from components.ui.filters import (
    build_week_options,
    parse_selected_weeks,
    apply_filters_to_data,
)


# ==================== build_week_options ====================

class TestBuildWeekOptions:
    def test_float_weeks_become_ints(self):
        """Reproduces the original bug: float Week Number column."""
        s = pd.Series([1.0, 2.0, 3.0], dtype='float64')
        assert build_week_options(s) == [1, 2, 3]

    def test_int_weeks_stay_ints(self):
        s = pd.Series([5, 7, 9], dtype='int64')
        assert build_week_options(s) == [5, 7, 9]

    def test_nullable_int_weeks(self):
        """Int64 with NaN is what data_processor produces from 'WK num'."""
        s = pd.Series([9, 10, pd.NA], dtype='Int64')
        assert build_week_options(s) == [9, 10]

    def test_drops_nan(self):
        s = pd.Series([1.0, np.nan, 2.0])
        assert build_week_options(s) == [1, 2]

    def test_dedupes(self):
        s = pd.Series([1.0, 1.0, 2.0, 2.0, 3.0])
        assert build_week_options(s) == [1, 2, 3]

    def test_sorted_ascending(self):
        s = pd.Series([12.0, 3.0, 8.0])
        assert build_week_options(s) == [3, 8, 12]

    def test_empty_series(self):
        assert build_week_options(pd.Series([], dtype='float64')) == []

    def test_all_nan_series(self):
        s = pd.Series([np.nan, np.nan])
        assert build_week_options(s) == []

    def test_display_strings_have_no_decimal(self):
        """The actual symptom: str(week) must not produce '5.0'."""
        s = pd.Series([5.0, 6.0])
        opts = build_week_options(s)
        assert [str(w) for w in opts] == ['5', '6']


# ==================== parse_selected_weeks ====================

class TestParseSelectedWeeks:
    def test_parses_int_strings(self):
        assert parse_selected_weeks(['5', '6', '7']) == [5, 6, 7]

    def test_strips_all_sentinel(self):
        assert parse_selected_weeks(['All', '5']) == [5]

    def test_only_all_returns_empty(self):
        assert parse_selected_weeks(['All']) == []

    def test_empty_returns_empty(self):
        assert parse_selected_weeks([]) == []

    def test_handles_legacy_decimal_strings(self):
        """Defends against any caller that still passes '5.0'-style values."""
        assert parse_selected_weeks(['5.0', '6.0']) == [5, 6]

    def test_invalid_string_raises(self):
        """Not a number → still surface the error rather than silently dropping."""
        with pytest.raises(ValueError):
            parse_selected_weeks(['not-a-number'])


# ==================== apply_filters_to_data ====================

@pytest.fixture
def comprehensive_data():
    return pd.DataFrame({
        'Discharged Port': ['LAX', 'LAX', 'BAL', 'NYC'],
        'Facility': ['IUSF-5', 'HGR6-5', 'IUSF-5', 'REWR-5'],
        'Week Number': [9, 10, 9, 11],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'ABCD', 'IJKL'],
    })


@pytest.fixture(autouse=True)
def _patched_st(monkeypatch):
    """Replace filters_module.st with a stub that has a SimpleNamespace
    session_state — works regardless of whether the real streamlit is loaded.
    """
    stub = MagicMock()
    stub.session_state = SimpleNamespace(
        filter_ports=[], filter_fcs=[], filter_weeks=[], filter_scacs=[],
    )
    monkeypatch.setattr(filters_module, 'st', stub)
    yield stub


def _set_session(_patched_st, **filters):
    """Reset session_state to a SimpleNamespace with the given filter values."""
    _patched_st.session_state = SimpleNamespace(
        filter_ports=filters.get('filter_ports', []),
        filter_fcs=filters.get('filter_fcs', []),
        filter_weeks=filters.get('filter_weeks', []),
        filter_scacs=filters.get('filter_scacs', []),
    )


class TestApplyFiltersToData:
    def test_no_filters_returns_full_data(self, comprehensive_data, _patched_st):
        _set_session(_patched_st)
        result, p, f, w, s = apply_filters_to_data(comprehensive_data)
        assert len(result) == 4
        assert (p, f, w, s) == ("All Ports", "All FCs", "All Weeks", "All SCACs")

    def test_port_filter(self, comprehensive_data, _patched_st):
        _set_session(_patched_st, filter_ports=['LAX'])
        result, *_ = apply_filters_to_data(comprehensive_data)
        assert len(result) == 2
        assert set(result['Discharged Port']) == {'LAX'}

    def test_week_filter_with_int(self, comprehensive_data, _patched_st):
        """Round-trip: parse_selected_weeks output (ints) is what gets stored."""
        _set_session(_patched_st, filter_weeks=[9])
        result, *_ = apply_filters_to_data(comprehensive_data)
        assert len(result) == 2
        assert set(result['Week Number']) == {9}

    def test_week_filter_with_int_against_float_column(self, _patched_st):
        """The pipeline produces float Week Numbers post-merge; isin must still match."""
        df = pd.DataFrame({
            'Discharged Port': ['LAX', 'LAX'],
            'Facility': ['IUSF-5', 'HGR6-5'],
            'Week Number': pd.Series([9.0, 10.0], dtype='float64'),
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
        })
        _set_session(_patched_st, filter_weeks=[9])
        result, *_ = apply_filters_to_data(df)
        assert len(result) == 1
        assert result['Week Number'].iloc[0] == 9.0

    def test_facility_filter_uses_normalized_codes(self, comprehensive_data, _patched_st):
        """Filter values are 4-char normalized codes; raw column has '-5' suffix."""
        _set_session(_patched_st, filter_fcs=['IUSF'])
        result, *_ = apply_filters_to_data(comprehensive_data)
        assert len(result) == 2
        assert all(result['Facility'].str.startswith('IUSF'))

    def test_combined_filters(self, comprehensive_data, _patched_st):
        _set_session(_patched_st, filter_ports=['LAX'], filter_weeks=[9])
        result, *_ = apply_filters_to_data(comprehensive_data)
        assert len(result) == 1
        assert result.iloc[0]['Discharged Port'] == 'LAX'
        assert result.iloc[0]['Week Number'] == 9

    def test_filter_with_no_matches_returns_empty(self, comprehensive_data, _patched_st):
        _set_session(_patched_st, filter_weeks=[999])
        result, *_ = apply_filters_to_data(comprehensive_data)
        assert len(result) == 0

    def test_returns_copy_when_filtered(self, comprehensive_data, _patched_st):
        """Mutating the filtered frame must not affect the source."""
        _set_session(_patched_st, filter_ports=['LAX'])
        result, *_ = apply_filters_to_data(comprehensive_data)
        result.loc[result.index[0], 'Discharged Port'] = 'XXX'
        assert 'XXX' not in comprehensive_data['Discharged Port'].values

    def test_scac_filter(self, comprehensive_data, _patched_st):
        """SCAC dimension — the dashboard reuses apply_filters_to_data to scope the
        per-container GVT handed to the Carrier Flip Analysis, so all four filter
        dimensions (incl. SCAC) must narrow a GVT-shaped frame identically."""
        _set_session(_patched_st, filter_scacs=['ABCD'])
        result, *_ = apply_filters_to_data(comprehensive_data)
        assert len(result) == 2
        assert set(result['Dray SCAC(FL)']) == {'ABCD'}
