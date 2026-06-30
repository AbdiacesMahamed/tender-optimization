"""End-to-end review tests for the restored PNW state (local verification).

Written to prove, in the user's own words:

  1. "if i say a terminal needs a min of 40 it needs to follow that throughout
     for both constrained and unconstrained" — a scoped Minimum is honored on
     the COMBINED (constrained + unconstrained) pool.
  2. "the combination of scope like scac and terminal" — a rule scoped to a
     Terminal AND targeting a specific SCAC binds only on that intersection, and
     a Max on it holds across both tables.
  3. The PNW standing rules (Hunt 130/wk at Tacoma + 60-per-vessel cap) flow
     through the REAL prebuilt-merge pipeline into the allocation, and the
     resulting constrained allocation feeds the carrier-flip report.

These drive the actual engine (apply_constraints_to_data, merge_prebuilt_first,
run_carrier_flip_analysis) — no reimplementation — so they fail if the wiring
regresses. Streamlit is stubbed in tests/conftest.py.
"""
import pandas as pd
import pytest

from components.constraints.processor import apply_constraints_to_data
from components.constraints.prebuilt import merge_prebuilt_first
from components.reporting.carrier_flip import run_carrier_flip_analysis


CANON_COLS = [
    'Category', 'Carrier', 'Lane', 'Port', 'Week Number', 'Day of Week',
    'Terminal', 'SSL', 'Vessel', 'Maximum Container Count',
    'Minimum Container Count', 'Percent Allocation', 'Excluded FC', 'Priority Score',
]


def _constraint(**fields):
    base = {c: None for c in CANON_COLS}
    base['Priority Score'] = 10
    base.update(fields)
    return pd.DataFrame([base])


def _tiw_data(terminals=('T18', 'T30'), per_term=60, carrier='ZZZZ'):
    """TIW containers spread across terminals/days, all on one source carrier so a
    Min targeting a DIFFERENT carrier must pull from this pool to meet its floor."""
    rows = []
    for term in terminals:
        for i in range(per_term):
            rows.append({
                'Dray SCAC(FL)': carrier, 'Discharged Port': 'TIW', 'Category': 'TL',
                'Lane': 'USTIWOLM1', 'Week Number': 27, 'Day of Week': (i % 5) + 2,
                'Terminal': term, 'SSL': 'MAEU', 'Vessel': f'VES_{term}',
                'Facility': 'OLM1', 'Container Numbers': f'{term}{i:05d}',
                'Container Count': 1, 'Base Rate': 100, 'Total Rate': 100,
            })
    return pd.DataFrame(rows)


def _combined_total(con, unc, **filt):
    """Container Count for rows matching ALL of filt, summed across both tables."""
    def t(df):
        if df is None or not len(df):
            return 0
        m = pd.Series(True, index=df.index)
        for k, v in filt.items():
            if k not in df.columns:
                return 0
            m &= df[k].astype(str) == str(v)
        return int(df[m]['Container Count'].sum())
    return t(con) + t(unc)


# ==================== 1. terminal MIN of 40 across both tables ====================

class TestTerminalMinAcrossBothTables:
    def test_terminal_min_40_is_met(self):
        # "a terminal needs a min of 40" — HJBT must end with >= 40 at T18.
        c = _constraint(Carrier='HJBT', Port='TIW', Terminal='T18',
                        **{'Minimum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(_tiw_data(), c)
        hjbt_t18 = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Terminal': 'T18'})
        assert hjbt_t18 >= 40, f"terminal min not met: HJBT@T18={hjbt_t18}"

    def test_min_does_not_bleed_into_other_terminal(self):
        # Scope is T18 only — the floor must not inflate HJBT at T30.
        c = _constraint(Carrier='HJBT', Port='TIW', Terminal='T18',
                        **{'Minimum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(_tiw_data(), c)
        hjbt_t30 = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Terminal': 'T30'})
        assert hjbt_t30 == 0, f"min bled into T30: HJBT@T30={hjbt_t30}"

    def test_conservation_holds(self):
        data = _tiw_data()
        c = _constraint(Carrier='HJBT', Port='TIW', Terminal='T18',
                        **{'Minimum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(data, c)
        tot = (con['Container Count'].sum() if len(con) else 0) + \
              (unc['Container Count'].sum() if len(unc) else 0)
        assert tot == data['Container Count'].sum()


# ==================== 2. SCAC + Terminal combination scope ====================

class TestScacAndTerminalCombination:
    def test_scac_terminal_max_holds_both_tables(self):
        # SCAC (HJBT, the target) + Terminal (T18) + Max 25 → bind on intersection.
        c = _constraint(Carrier='HJBT', Port='TIW', Terminal='T18',
                        **{'Maximum Container Count': 25})
        con, unc, *_ = apply_constraints_to_data(_tiw_data(), c)
        total = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Terminal': 'T18'})
        assert total <= 25, f"SCAC+Terminal cap violated: {total}"

    def test_scac_terminal_min_and_max_band(self):
        c = _constraint(Carrier='HJBT', Port='TIW', Terminal='T18',
                        **{'Minimum Container Count': 20, 'Maximum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(_tiw_data(), c)
        total = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Terminal': 'T18'})
        assert 20 <= total <= 40, f"SCAC+Terminal band violated: {total}"

    def test_two_scacs_same_terminal_each_respected(self):
        # Two SCAC+Terminal rules on the same terminal must each hold.
        c1 = _constraint(Carrier='HJBT', Port='TIW', Terminal='T18',
                         **{'Maximum Container Count': 30, 'Priority Score': 2})
        c2 = _constraint(Carrier='RKNE', Port='TIW', Terminal='T18',
                         **{'Maximum Container Count': 15, 'Priority Score': 1})
        cons = pd.concat([c1, c2], ignore_index=True)
        con, unc, *_ = apply_constraints_to_data(_tiw_data(), cons)
        hjbt = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Terminal': 'T18'})
        rkne = _combined_total(con, unc, **{'Dray SCAC(FL)': 'RKNE', 'Terminal': 'T18'})
        assert hjbt <= 30, f"HJBT@T18={hjbt}"
        assert rkne <= 15, f"RKNE@T18={rkne}"


# ==================== 3. PNW rules flow into the carrier-flip report ====================

class TestPnwRulesReachCarrierFlips:
    def _allocate_with_pnw(self, data):
        """Run the REAL prebuilt-merge + constraint engine the dashboard uses."""
        merged = merge_prebuilt_first(None, data)          # injects PNW Rule 1 + 2
        con, unc, *_ = apply_constraints_to_data(data, merged)
        return merged, con, unc

    def test_hunt_130_rows_are_injected(self):
        merged, _, _ = self._allocate_with_pnw(_tiw_data())
        # Rule 1 generates ONE Max-130 HJBT/TIW row per week (no Min floor): HJBT
        # is capped at up to 130 and allocated first, not forced to exactly 130.
        hunt = merged[(merged['Carrier'].astype(str).str.upper() == 'HJBT')
                      & (merged['Port'].astype(str).str.upper() == 'TIW')]
        assert len(hunt) >= 1, "expected a Hunt Max-130 row"
        assert (hunt['Maximum Container Count'] == 130).any()
        # No hard Min-130 floor should be emitted anymore.
        assert hunt['Minimum Container Count'].isna().all()

    def test_hunt_capped_at_130_in_allocation(self):
        # 120 TIW containers available; Hunt rule caps HJBT at 130 → it can take
        # all 120 but never exceed 130. (Pool < 130 so it takes the whole pool.)
        _, con, unc = self._allocate_with_pnw(_tiw_data(per_term=60))  # 120 total
        hjbt = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Discharged Port': 'TIW'})
        assert hjbt <= 130, f"Hunt exceeded 130: {hjbt}"

    def test_hunt_takes_all_available_when_under_130(self):
        # "as close to 130 as possible": with only 120 TIW containers and HJBT
        # allocated FIRST, HJBT should claim ALL 120 (not stop short, not forced
        # to a 130 floor it can't reach).
        data = _tiw_data(per_term=60)  # 120 TIW containers total
        _, con, unc = self._allocate_with_pnw(data)
        hjbt = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Discharged Port': 'TIW'})
        assert hjbt == 120, f"HJBT should take all 120 available, got {hjbt}"

    def test_hunt_stops_at_130_when_more_available(self):
        # With 200 TIW containers, the cap binds: HJBT gets exactly 130, the rest
        # stay available for other carriers / the optimizer.
        data = _tiw_data(per_term=100)  # 200 TIW containers total
        _, con, unc = self._allocate_with_pnw(data)
        hjbt = _combined_total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Discharged Port': 'TIW'})
        assert hjbt == 130, f"HJBT should be capped at 130, got {hjbt}"

    def test_flip_report_builds_from_pnw_constrained_allocation(self):
        data = _tiw_data()
        _, con, unc = self._allocate_with_pnw(data)
        # GVT: original carrier ZZZZ for every container, so any HJBT assignment is
        # a real flip the report should price/trace.
        gvt = data[['Container Numbers', 'Dray SCAC(FL)', 'Lane',
                    'Discharged Port', 'Week Number']].copy()
        # Constrained frame labels the assigned carrier as 'NEW SCAC' (as metrics.py does).
        con_flip = con.rename(columns={'Dray SCAC(FL)': 'NEW SCAC'}) if len(con) else con
        results = run_carrier_flip_analysis(
            tender_dfs=[unc] if len(unc) else [],
            constrained_dfs=[con_flip] if len(con_flip) else [],
            gvt_df=gvt,
            rates_df=None,
        )
        # The report must build a result (not error out) and see the constrained set.
        assert results is not None
        assert results.get('constrained') is not None
        assert not results['constrained'].empty


# ==================== 4. SEA is a PNW port too ====================

class TestSeaIsCoveredByPnwRules:
    """SEA (Seattle) and TIW (Tacoma) are both PNW ports. Every PNW rule keyed on
    _is_pnw_port must apply at SEA as well — the per-vessel cap (Rule 2), the
    one-vessel-per-carrier pass (Rules 3/4), and the SEA port lockout (Rule 0).
    The ONLY TIW-exclusive rule is Hunt 130/wk (HUNT_PORT='TIW') — by design,
    since that rule is 'JB Hunt 130/week at Tacoma'."""

    def _sea_data(self, over_cap_carrier='ULSE', over_cap_n=75):
        """SEA containers: one carrier with >60 on a single vessel (to exercise the
        per-vessel cap at SEA), plus a couple of RKNE rows (locked out of SEA)."""
        rows = []
        for i in range(over_cap_n):  # 75 > 60 → cap must bite at SEA
            rows.append({
                'Dray SCAC(FL)': over_cap_carrier, 'Discharged Port': 'SEA',
                'Category': 'TL', 'Lane': 'USSEAOLM1', 'Week Number': 27,
                'Day of Week': (i % 5) + 2, 'Terminal': 'T18', 'SSL': 'MAEU',
                'Vessel': 'SEA_VES_1', 'Facility': 'OLM1',
                'Container Numbers': f'SEA{i:05d}', 'Container Count': 1,
                'Ocean ETA': '2026-07-10', 'Base Rate': 100, 'Total Rate': 100,
            })
        for i in range(5):  # RKNE is locked OUT of Seattle (SEA.csv Max 0)
            rows.append({
                'Dray SCAC(FL)': 'RKNE', 'Discharged Port': 'SEA', 'Category': 'TL',
                'Lane': 'USSEAOLM1', 'Week Number': 27, 'Day of Week': (i % 5) + 2,
                'Terminal': 'T18', 'SSL': 'MAEU', 'Vessel': 'SEA_VES_1',
                'Facility': 'OLM1', 'Container Numbers': f'SEARK{i:05d}',
                'Container Count': 1, 'Ocean ETA': '2026-07-10',
                'Base Rate': 120, 'Total Rate': 120,
            })
        return pd.DataFrame(rows)

    def _allocate_with_pnw(self, data):
        merged = merge_prebuilt_first(None, data)
        con, unc, *_ = apply_constraints_to_data(data, merged)
        return merged, con, unc

    def test_per_vessel_cap_row_generated_for_sea(self):
        # Rule 2 must materialize a Max-60 row for the SEA (vessel, carrier).
        merged = merge_prebuilt_first(None, self._sea_data())
        sea_caps = merged[(merged['Port'].astype(str).str.upper() == 'SEA')
                          & (merged['Maximum Container Count'] == 60)]
        assert len(sea_caps) >= 1, "no 60-per-vessel cap row generated for SEA"

    def test_sea_lockout_zeroes_rkne(self):
        # Rule 0: RKNE is banned from Seattle (Max 0) → 0 RKNE allocated at SEA.
        _, con, unc = self._allocate_with_pnw(self._sea_data())
        rkne_sea = _combined_total(con, unc,
                                   **{'Dray SCAC(FL)': 'RKNE', 'Discharged Port': 'SEA'})
        assert rkne_sea == 0, f"RKNE should be locked out of SEA, got {rkne_sea}"

    def test_hunt_130_does_NOT_apply_to_sea(self):
        # Hunt is Tacoma-only: no HJBT/SEA 130 row should be generated.
        merged = merge_prebuilt_first(None, self._sea_data())
        hjbt_sea_130 = merged[(merged['Carrier'].astype(str).str.upper() == 'HJBT')
                              & (merged['Port'].astype(str).str.upper() == 'SEA')
                              & ((merged['Maximum Container Count'] == 130)
                                 | (merged['Minimum Container Count'] == 130))]
        assert len(hjbt_sea_130) == 0, "Hunt 130 must NOT apply at SEA (Tacoma-only)"

    def test_conservation_holds_at_sea(self):
        data = self._sea_data()
        _, con, unc = self._allocate_with_pnw(data)
        tot = (con['Container Count'].sum() if len(con) else 0) + \
              (unc['Container Count'].sum() if len(unc) else 0)
        assert tot == data['Container Count'].sum()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
