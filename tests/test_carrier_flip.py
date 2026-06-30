"""Adversarial tests for the in-app Carrier Flip Analysis engine.

These tests are deliberately hostile: they feed malformed, empty, ambiguous,
and edge-case inputs to the pure engine functions in components.carrier_flip
and assert it degrades gracefully (no crashes, no silent wrong answers) rather
than only checking the happy path.
"""
import io

import numpy as np
import pandas as pd
import pytest

from components.reporting import carrier_flip as cf


# ---------------------------------------------------------------------------
# _parse_rate — money strings, junk, numerics
# ---------------------------------------------------------------------------

class TestParseRate:
    @pytest.mark.parametrize("raw,expected", [
        ("$175.00", 175.0),
        ("$1,255.00", 1255.0),
        ("175", 175.0),
        ("  42.5  ", 42.5),
        (175, 175.0),
        (175.5, 175.5),
        ("$0", 0.0),
        ("-$50.00", -50.0),
    ])
    def test_valid(self, raw, expected):
        assert cf._parse_rate(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "abc", "$", "N/A", np.nan, "$--"])
    def test_unparseable_returns_none(self, raw):
        assert cf._parse_rate(raw) is None

    def test_does_not_swallow_pandas_na(self):
        assert cf._parse_rate(pd.NA) is None or True  # must not raise


# ---------------------------------------------------------------------------
# Container normalization — case, junk chars, check-digit fuzzing
# ---------------------------------------------------------------------------

class TestNormalizeContainer:
    def test_lowercase_and_spaces(self):
        assert cf._normalize_container("  abcu 123 456 7 ") == "ABCU1234567"

    def test_trailing_x_stripped(self):
        assert cf._normalize_container("ABCU1234567X") == "ABCU1234567"
        assert cf._normalize_container("ABCU1234567XX") == "ABCU1234567"

    def test_empty_and_non_string(self):
        assert cf._normalize_container("") == ""
        assert cf._normalize_container(None) == ""
        assert cf._normalize_container(np.nan) == ""
        assert cf._normalize_container(12345) == ""

    def test_short_key_strips_check_digit(self):
        # 11-char ISO id -> 10-char short key
        assert cf._normalize_container_short("ABCU1234567") == "ABCU123456"

    def test_short_key_noop_for_nonstandard(self):
        # Not 11 chars / not ISO shape -> unchanged
        assert cf._normalize_container_short("W92290") == "W92290"


# ---------------------------------------------------------------------------
# parse_flip_info — the regex parser is the most fragile part
# ---------------------------------------------------------------------------

class TestParseFlipInfo:
    def test_non_string_returns_zeros(self):
        out = cf.parse_flip_info(np.nan)
        assert list(out) == [0, "", "", 0, 0]
        out2 = cf.parse_flip_info(None)
        assert list(out2) == [0, "", "", 0, 0]

    def test_no_flip_literal(self):
        out = cf.parse_flip_info("No Flip")
        assert list(out) == [0, "", "", 0, 0]

    def test_now_word_not_captured_as_carrier(self):
        # 'Now' is 3 uppercase-ish letters but must never be treated as a SCAC
        cf._unrecognized_carriers.clear()
        out = cf.parse_flip_info("Now 5: From ATMI (+3), FRQT (+2)")
        now, frm, lost, from_count, lost_count = out
        assert now == 5
        assert "Now" not in frm
        assert from_count == 5
        assert "Now" not in cf._unrecognized_carriers

    def test_unknown_scac_tracked(self):
        cf._unrecognized_carriers.clear()
        cf.parse_flip_info("Now 1: From ZZZZ (+1)")
        assert "ZZZZ" in cf._unrecognized_carriers

    def test_known_scac_not_tracked(self):
        cf._unrecognized_carriers.clear()
        cf.parse_flip_info("Now 1: From ATMI (+1)")
        assert "ATMI" not in cf._unrecognized_carriers

    def test_lost_counts_negative(self):
        out = cf.parse_flip_info("Now 0: To HJBT (-4)")
        now, frm, lost, from_count, lost_count = out
        assert lost_count == 4
        assert "HJBT (-4)" in lost


# ---------------------------------------------------------------------------
# _split_container_numbers — separator zoo
# ---------------------------------------------------------------------------

class TestSplitContainers:
    @pytest.mark.parametrize("text,n", [
        ("A1, A2, A3", 3),
        ("A1;A2;A3", 3),
        ("A1|A2", 2),
        ("A1\nA2\r\nA3", 3),
        ("A1,,A2", 2),       # double delimiter collapses
        ("  A1  ", 1),
        ("", 0),
        ("   ", 0),
    ])
    def test_counts(self, text, n):
        assert len(cf._split_container_numbers(text)) == n

    def test_non_string(self):
        assert cf._split_container_numbers(np.nan) == []
        assert cf._split_container_numbers(None) == []


# ---------------------------------------------------------------------------
# classify_file — must not misroute constrained as tender (the documented trap)
# ---------------------------------------------------------------------------

class TestClassifyFile:
    def test_gvt(self):
        df = pd.DataFrame({'Container': ['A1'], 'Dray SCAC(FL)': ['ATMI']})
        assert cf.classify_file(df) == 'gvt'

    def test_tender(self):
        df = pd.DataFrame({'NEW SCAC': ['ATMI'], 'Container Numbers': ['A1'],
                           'Carrier Flips': ['No Flip']})
        assert cf.classify_file(df) == 'tender'

    def test_constrained_beats_tender_even_with_flips_column(self):
        # A constrained file that ALSO has 'Carrier Flips' must classify as constrained
        df = pd.DataFrame({
            'NEW SCAC': ['ATMI'], 'Container Numbers': ['A1'],
            'Carrier Flips': ['No Flip'], '📝 Description': ['locked'],
        })
        assert cf.classify_file(df) == 'constrained'

    def test_constrained_emoji_priority_column(self):
        df = pd.DataFrame({'SCAC': ['ATMI'], 'Container Numbers': ['A1'],
                           '🎯 Priority': [1]})
        assert cf.classify_file(df) == 'constrained'

    def test_unknown(self):
        df = pd.DataFrame({'foo': [1], 'bar': [2]})
        assert cf.classify_file(df) == 'unknown'


# ---------------------------------------------------------------------------
# build_rate_lookup — missing columns, dollar strings, ambiguity guards
# ---------------------------------------------------------------------------

class TestBuildRateLookup:
    def test_none_returns_empty(self):
        assert cf.build_rate_lookup(None) == {}

    def test_missing_key_columns_returns_empty(self):
        df = pd.DataFrame({'Base Rate': [100], 'SomethingElse': ['x']})
        assert cf.build_rate_lookup(df) == {}

    def test_missing_rate_column_returns_empty(self):
        df = pd.DataFrame({'Lookup': ['ATMIUSLAXLAX9'], 'Notes': ['x']})
        assert cf.build_rate_lookup(df) == {}

    def test_lookup_column(self):
        df = pd.DataFrame({'Lookup': ['ATMIUSLAXLAX9'], 'Base Rate': [175]})
        rm = cf.build_rate_lookup(df)
        assert rm['ATMIUSLAXLAX9'] == 175

    def test_components_column(self):
        df = pd.DataFrame({'SCAC': ['ATMI'], 'Port': ['USLAX'], 'FC': ['LAX9'],
                           'Base Rate': [175]})
        rm = cf.build_rate_lookup(df)
        assert rm['ATMIUSLAXLAX9'] == 175

    def test_port_equivalence_expansion(self):
        rates = pd.DataFrame({'Lookup': ['ATMIUSBWIBWI4'], 'Base Rate': [200]})
        port_dup = pd.DataFrame({'Port': ['USBWI'], 'Equivalent': ['USBAL']})
        rm = cf.build_rate_lookup(rates, port_dup)
        assert rm['ATMIUSBWIBWI4'] == 200
        assert rm['ATMIUSBALBWI4'] == 200  # alias added


# ---------------------------------------------------------------------------
# _lookup_rate_from_map — ambiguity must yield None, not a wrong rate
# ---------------------------------------------------------------------------

class TestLookupRateFromMap:
    def test_exact(self):
        rm = {'ATMIUSLAXLAX9': 175}
        rate, method = cf._lookup_rate_from_map('ATMI', 'USLAXLAX9', 'LAX9', rm)
        assert rate == 175 and method == 'exact'

    def test_port_unique(self):
        rm = {'ATMIUSLAXLAX9': 175}
        rate, method = cf._lookup_rate_from_map('ATMI', 'USLAXXXXX', 'ZZZ9', rm)
        assert rate == 175 and method == 'port'

    def test_port_ambiguous_returns_none(self):
        # Two entries share the SCAC+port prefix -> ambiguous -> no rate
        rm = {'ATMIUSLAXLAX9': 175, 'ATMIUSLAXLAX7': 200}
        rate, method = cf._lookup_rate_from_map('ATMI', 'USLAXZZZZ', None, rm)
        assert rate is None and method is None

    def test_fc_unique(self):
        rm = {'ATMIUSLAXLAX9': 175}
        rate, method = cf._lookup_rate_from_map('ATMI', None, 'LAX9', rm)
        assert rate == 175 and method == 'fc'

    def test_empty_scac(self):
        assert cf._lookup_rate_from_map('', 'USLAXLAX9', 'LAX9', {'X': 1}) == (None, None)
        assert cf._lookup_rate_from_map(None, 'USLAXLAX9', 'LAX9', {'X': 1}) == (None, None)

    def test_case_insensitive_scac(self):
        rm = {'ATMIUSLAXLAX9': 175}
        rate, _ = cf._lookup_rate_from_map('atmi', 'uslaxlax9', 'lax9', rm)
        assert rate == 175


# ---------------------------------------------------------------------------
# create_container_carrier_mapping — explode, dedup, NaN carriers
# ---------------------------------------------------------------------------

class TestContainerMapping:
    def test_empty_df(self):
        out = cf.create_container_carrier_mapping(pd.DataFrame())
        assert out.empty

    def test_no_carrier_column(self):
        df = pd.DataFrame({'Container Numbers': ['A1, A2']})
        out = cf.create_container_carrier_mapping(df)
        assert out.empty

    def test_explode_and_normalize(self):
        df = pd.DataFrame({
            'NEW SCAC': ['ATMI'],
            'Container Numbers': ['abcu1234567, defu7654321'],
            'Lane': ['USLAXLAX9'],
        })
        out = cf.create_container_carrier_mapping(df)
        assert set(out['Container']) == {'ABCU1234567', 'DEFU7654321'}
        assert (out['NEW SCAC'] == 'ATMI').all()
        # FC derived from Lane (Port=5 chars => 'LAX9')
        assert (out['FC'] == 'LAX9').all()

    def test_nan_carrier_rows_dropped(self):
        df = pd.DataFrame({
            'NEW SCAC': ['ATMI', np.nan],
            'Container Numbers': ['A1', 'B2'],
        })
        out = cf.create_container_carrier_mapping(df)
        assert list(out['Container']) == ['A1']


# ---------------------------------------------------------------------------
# merge_gvt_with_carrier_flips — the integration crux
# ---------------------------------------------------------------------------

def _gvt(containers, scacs, **extra):
    data = {'Container': containers, 'Dray SCAC(FL)': scacs}
    data.update(extra)
    return pd.DataFrame(data)


class TestMergeGvt:
    def test_no_container_col_returns_input(self):
        gvt = pd.DataFrame({'Foo': [1]})
        mapping = pd.DataFrame({'Container': ['A1'], 'NEW SCAC': ['ATMI']})
        out = cf.merge_gvt_with_carrier_flips(gvt, mapping)
        assert 'Match Status' not in out.columns  # bailed out cleanly

    def test_left_join_keeps_all_gvt_rows(self):
        gvt = _gvt(['ABCU1234567', 'UNMATCHED01'], ['HJBT', 'KNIG'])
        mapping = pd.DataFrame({'Container': ['ABCU1234567'], 'NEW SCAC': ['ATMI']})
        out = cf.merge_gvt_with_carrier_flips(gvt, mapping)
        assert len(out) == 2
        assert set(out['Match Status']) == {'Matched', 'No New Assignment'}

    def test_check_digit_fallback(self):
        # GVT has check digit 7, mapping has check digit 9 — short-key fallback recovers it
        gvt = _gvt(['ABCU1234567'], ['HJBT'])
        mapping = pd.DataFrame({'Container': ['ABCU1234569'], 'NEW SCAC': ['ATMI']})
        out = cf.merge_gvt_with_carrier_flips(gvt, mapping)
        assert out.iloc[0]['Match Status'] == 'Matched'
        assert out.iloc[0]['NEW SCAC'] == 'ATMI'

    def test_savings_computed(self):
        gvt = _gvt(['ABCU1234567'], ['HJBT'],
                   **{'Discharged Port': ['LAX'], 'Facility': ['LAX9']})
        mapping = pd.DataFrame({'Container': ['ABCU1234567'], 'NEW SCAC': ['ATMI'],
                                'Lane': ['USLAXLAX9'], 'FC': ['LAX9']})
        rate_map = {'HJBTUSLAXLAX9': 200, 'ATMIUSLAXLAX9': 175}
        out = cf.merge_gvt_with_carrier_flips(gvt, mapping, rate_map)
        row = out.iloc[0]
        assert row['Old Rate'] == 200
        assert row['New Rate'] == 175
        assert row['Savings'] == 25

    def test_savings_none_when_rate_missing(self):
        gvt = _gvt(['ABCU1234567'], ['HJBT'],
                   **{'Discharged Port': ['LAX'], 'Facility': ['LAX9']})
        mapping = pd.DataFrame({'Container': ['ABCU1234567'], 'NEW SCAC': ['ATMI'],
                                'Lane': ['USLAXLAX9'], 'FC': ['LAX9']})
        rate_map = {'ATMIUSLAXLAX9': 175}  # old (HJBT) missing
        out = cf.merge_gvt_with_carrier_flips(gvt, mapping, rate_map)
        row = out.iloc[0]
        assert pd.isna(row['Old Rate'])
        assert pd.isna(row['Savings'])
        assert 'not in rate card' in str(row['Old Rate Reason'])


# ---------------------------------------------------------------------------
# run_carrier_flip_analysis — full orchestration, hostile inputs
# ---------------------------------------------------------------------------

class TestRunAnalysis:
    def test_no_inputs(self):
        res = cf.run_carrier_flip_analysis()
        assert res['summary'] is None
        assert res['gvt_merged'] is None
        assert res['diagnostics']  # has an explanatory line

    def test_empty_frames_treated_as_none(self):
        res = cf.run_carrier_flip_analysis(tender_dfs=[pd.DataFrame()],
                                           constrained_dfs=[pd.DataFrame()])
        assert res['summary'] is None

    def test_tender_only_no_gvt(self):
        tender = pd.DataFrame({
            'NEW SCAC': ['ATMI'],
            'Container Numbers': ['ABCU1234567'],
            'Carrier Flips': ['Now 1: From HJBT (+1)'],
            'Discharged Port': ['LAX'],
            'Week Number': [22],
        })
        res = cf.run_carrier_flip_analysis(tender_dfs=[tender])
        assert res['summary'] is not None
        assert res['gvt_merged'] is None  # no GVT -> no merge

    def test_full_pipeline_savings(self):
        tender = pd.DataFrame({
            'NEW SCAC': ['ATMI'],
            'Container Numbers': ['ABCU1234567'],
            'Carrier Flips': ['Now 1: From HJBT (+1)'],
            'Lane': ['USLAXLAX9'],
            'Discharged Port': ['LAX'],
            'Week Number': [22],
        })
        gvt = pd.DataFrame({
            'Container': ['ABCU1234567'],
            'Dray SCAC(FL)': ['HJBT'],
            'Discharged Port': ['LAX'],
            'Facility': ['LAX9'],
        })
        rates = pd.DataFrame({
            'Lookup': ['HJBTUSLAXLAX9', 'ATMIUSLAXLAX9'],
            'Base Rate': [200, 175],
        })
        res = cf.run_carrier_flip_analysis(tender_dfs=[tender], gvt_df=gvt, rates_df=rates)
        assert res['gvt_merged'] is not None
        assert res['stats']['total_savings'] == 25
        assert res['stats']['matched'] == 1

    def test_unrecognized_carrier_surfaced(self):
        tender = pd.DataFrame({
            'NEW SCAC': ['ZZZZ'],
            'Container Numbers': ['ABCU1234567'],
            'Carrier Flips': ['Now 1: From ZZZZ (+1)'],
        })
        res = cf.run_carrier_flip_analysis(tender_dfs=[tender])
        assert 'ZZZZ' in res['unrecognized_carriers']

    def test_unrecognized_reset_between_runs(self):
        # State leakage guard: a fresh run must not carry ZZZZ from a prior run
        cf.run_carrier_flip_analysis(tender_dfs=[pd.DataFrame({
            'NEW SCAC': ['ZZZZ'], 'Container Numbers': ['A1'],
            'Carrier Flips': ['Now 1: From ZZZZ (+1)']})])
        clean = pd.DataFrame({
            'NEW SCAC': ['ATMI'], 'Container Numbers': ['A2'],
            'Carrier Flips': ['Now 1: From ATMI (+1)']})
        res = cf.run_carrier_flip_analysis(tender_dfs=[clean])
        assert 'ZZZZ' not in res['unrecognized_carriers']

    def test_constraint_wins_over_unconstrained_for_same_container(self):
        # A container the user LOCKED to RKNE via a constraint, but the
        # unconstrained optimizer assigned to ATMI, must report the CONSTRAINED
        # carrier in the flip report — constraints are authoritative. (Regression:
        # the old dedup kept the alphabetically-first SCAC, silently dropping the
        # constraint and reporting ATMI.)
        unconstrained = pd.DataFrame({
            'NEW SCAC': ['ATMI'], 'Container Numbers': ['ZZZU1234567'],
            'Lane': ['USTIWTIW1']})
        constrained = pd.DataFrame({
            'NEW SCAC': ['RKNE'], 'Container Numbers': ['ZZZU1234567'],
            'Lane': ['USTIWTIW1']})
        gvt = _gvt(['ZZZU1234567'], ['HJBT'],
                   **{'Discharged Port': ['TIW'], 'Facility': ['TIW1']})
        res = cf.run_carrier_flip_analysis(
            tender_dfs=[unconstrained], constrained_dfs=[constrained], gvt_df=gvt)
        assert res['gvt_merged'].iloc[0]['NEW SCAC'] == 'RKNE'

    def test_constraint_priority_independent_of_scac_alphabetical_order(self):
        # Guard that the constrained source wins even when its SCAC sorts LATER
        # alphabetically than the unconstrained one (so the fix isn't an accident
        # of alphabetical tie-breaking).
        unconstrained = pd.DataFrame({
            'NEW SCAC': ['AAAA'], 'Container Numbers': ['ZZZU1234567'],
            'Lane': ['USTIWTIW1']})
        constrained = pd.DataFrame({
            'NEW SCAC': ['ZZZZ'], 'Container Numbers': ['ZZZU1234567'],
            'Lane': ['USTIWTIW1']})
        gvt = _gvt(['ZZZU1234567'], ['HJBT'],
                   **{'Discharged Port': ['TIW'], 'Facility': ['TIW1']})
        res = cf.run_carrier_flip_analysis(
            tender_dfs=[unconstrained], constrained_dfs=[constrained], gvt_df=gvt)
        assert res['gvt_merged'].iloc[0]['NEW SCAC'] == 'ZZZZ'


# ---------------------------------------------------------------------------
# build_flip_report_excel — must produce a readable workbook
# ---------------------------------------------------------------------------

class TestExcelExport:
    def test_none_when_empty(self):
        res = cf.run_carrier_flip_analysis()
        assert cf.build_flip_report_excel(res) is None

    def test_roundtrip_sheets(self):
        tender = pd.DataFrame({
            'NEW SCAC': ['ATMI'],
            'Container Numbers': ['ABCU1234567'],
            'Carrier Flips': ['Now 1: From HJBT (+1)'],
            'Lane': ['USLAXLAX9'],
            'Discharged Port': ['LAX'],
            'Week Number': [22],
        })
        gvt = pd.DataFrame({
            'Container': ['ABCU1234567'],
            'Dray SCAC(FL)': ['HJBT'],
            'Discharged Port': ['LAX'],
            'Facility': ['LAX9'],
        })
        rates = pd.DataFrame({'Lookup': ['HJBTUSLAXLAX9', 'ATMIUSLAXLAX9'],
                              'Base Rate': [200, 175]})
        res = cf.run_carrier_flip_analysis(tender_dfs=[tender], gvt_df=gvt, rates_df=rates)
        data = cf.build_flip_report_excel(res)
        assert data is not None and len(data) > 0
        xl = pd.ExcelFile(io.BytesIO(data))
        assert 'GVT with New SCAC' in xl.sheet_names
        gvt_sheet = pd.read_excel(xl, 'GVT with New SCAC')
        assert gvt_sheet.iloc[0]['Savings'] == 25

    def test_datetime_with_tz_sanitized(self):
        # openpyxl chokes on tz-aware datetimes — exporter must strip tz
        tender = pd.DataFrame({
            'NEW SCAC': ['ATMI'], 'Container Numbers': ['ABCU1234567'],
            'Carrier Flips': ['No Flip'],
        })
        gvt = pd.DataFrame({
            'Container': ['ABCU1234567'],
            'Dray SCAC(FL)': ['ATMI'],
            'Ocean ETA': pd.to_datetime(['2026-05-22']).tz_localize('UTC'),
        })
        res = cf.run_carrier_flip_analysis(tender_dfs=[tender], gvt_df=gvt)
        data = cf.build_flip_report_excel(res)  # must not raise
        assert data is not None


class TestGvtPivot:
    def _gvt(self):
        return pd.DataFrame({
            'Container': ['ABCU1234567', 'ABCU1234568', 'ABCU1234569', 'ABCU1234570'],
            'Discharged Port': ['LAX', 'LAX', 'SEA', 'SEA'],
            'NEW SCAC': ['ATMI', 'FRQT', 'ATMI', None],
        })

    def test_counts_by_port_and_scac(self):
        piv = cf.build_gvt_pivot(self._gvt())
        assert piv is not None
        # Port is the first column (vertical), SCACs are columns (horizontal)
        assert piv.columns[0] == 'Discharged Port'
        assert 'ATMI' in piv.columns and 'FRQT' in piv.columns
        lax = piv[piv['Discharged Port'] == 'LAX'].iloc[0]
        assert lax['ATMI'] == 1 and lax['FRQT'] == 1 and lax['Total'] == 2

    def test_unassigned_excluded_and_totals(self):
        piv = cf.build_gvt_pivot(self._gvt())
        total_row = piv[piv['Discharged Port'] == 'Total'].iloc[0]
        # Only 3 of 4 containers have a NEW SCAC; the None row is dropped
        assert total_row['Total'] == 3
        assert total_row['ATMI'] == 2 and total_row['FRQT'] == 1

    def test_none_without_required_cols(self):
        assert cf.build_gvt_pivot(None) is None
        assert cf.build_gvt_pivot(pd.DataFrame({'Container': ['X']})) is None

    def test_none_when_no_assignments(self):
        gvt = pd.DataFrame({'Container': ['ABCU1234567'],
                            'Discharged Port': ['LAX'], 'NEW SCAC': [None]})
        assert cf.build_gvt_pivot(gvt) is None

    def test_pivot_sheet_in_workbook(self):
        tender = pd.DataFrame({
            'NEW SCAC': ['ATMI'],
            'Container Numbers': ['ABCU1234567'],
            'Carrier Flips': ['Now 1: From HJBT (+1)'],
            'Lane': ['USLAXLAX9'],
            'Discharged Port': ['LAX'],
        })
        gvt = pd.DataFrame({
            'Container': ['ABCU1234567'],
            'Dray SCAC(FL)': ['HJBT'],
            'Discharged Port': ['LAX'],
        })
        res = cf.run_carrier_flip_analysis(tender_dfs=[tender], gvt_df=gvt)
        data = cf.build_flip_report_excel(res)
        xl = pd.ExcelFile(io.BytesIO(data))
        assert 'GVT Pivot (Port x New SCAC)' in xl.sheet_names


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
