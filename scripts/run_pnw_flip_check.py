"""Ad-hoc runner: drive the REAL pipeline on the PNW data + the 6.25 PNW TEST
constraints, then inspect the Carrier Flip sheet for the HJBT/VIENNA EXPRESS cap.

Mirrors the dashboard chain:
  GVT + Rate -> process -> merge -> apply_constraints -> flip report
Runs TWICE: the constraint file AS UPLOADED (vessel name sitting in the Terminal
column) and a FIXED copy (vessel name moved into the Vessel column), so we can see
whether the 40-container cap on VIENNA EXPRESS actually binds.

Not a unit test — a one-off diagnostic. Streamlit is mocked so the component code
runs headless.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("streamlit", MagicMock())
import streamlit as st  # noqa: E402
st.session_state = {}
st.cache_data = lambda **k: (lambda f: f)

import pandas as pd  # noqa: E402

from components.data.processor import (  # noqa: E402
    validate_and_process_gvt_data, validate_and_process_rate_data, merge_all_data,
)
from components.constraints.processor import (  # noqa: E402
    process_constraints_file, apply_constraints_to_data,
)
from components.reporting import carrier_flip as cf  # noqa: E402

DL = Path("C:/Users/maabdiac/Downloads")
GVT_F = DL / "PNW GVT data.xlsx"
RATE_F = DL / "Rate card 5.22.26.xlsx"
CONS_F = DL / "New constraints 6.25 PNW TEST.xlsx"

VESSEL = "VIENNA EXPRESS"


def load_inputs():
    gvt_raw = pd.read_excel(GVT_F, sheet_name="Sheet3")
    gvt = validate_and_process_gvt_data(gvt_raw)
    rate = validate_and_process_rate_data(pd.read_excel(RATE_F, sheet_name="US Dray Master - 3P"))
    merged = merge_all_data(gvt, rate, pd.DataFrame(), False)
    return gvt_raw, rate, merged


def run_one(label, constraints_df, merged, rate, gvt_raw):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    constrained, unconstrained, summary, max_carriers, fc_excl, *_ = \
        apply_constraints_to_data(merged, constraints_df, rate)

    # How much HJBT volume on VIENNA EXPRESS landed in the constrained (locked) table?
    # The merged data carries Vessel through, so we can check the cap directly.
    def hjbt_vienna(df, tag):
        if "Vessel" not in df.columns:
            print(f"  [{tag}] no Vessel column"); return
        sub = df[(df["Dray SCAC(FL)"].astype(str) == "HJBT")
                 & (df["Vessel"].astype(str).str.upper() == VESSEL)]
        cnt = sub["Container Count"].sum() if "Container Count" in sub.columns else len(sub)
        print(f"  [{tag}] HJBT @ {VESSEL}: rows={len(sub)} containers={int(cnt)}")

    hjbt_vienna(constrained, "CONSTRAINED (locked to target)")
    hjbt_vienna(unconstrained, "UNCONSTRAINED (free to reassign)")

    # Was the cap recognized as a max constraint at all?
    vessel_caps = [m for m in (max_carriers or [])
                   if str(m.get("carrier")) == "HJBT"]
    print(f"  max_constrained_carriers for HJBT: {vessel_caps}")

    flip_con = constrained.copy()
    if "Dray SCAC(FL)" in flip_con.columns and "NEW SCAC" not in flip_con.columns:
        flip_con = flip_con.rename(columns={"Dray SCAC(FL)": "NEW SCAC"})

    # The dashboard's flip "unconstrained" side is the SELECTED SCENARIO'S output, not
    # the raw remainder. Run each scenario's real strategy (with the lockout list) so the
    # flip sheet reflects what would actually ship under that scenario.
    from components.scenarios.strategies import (
        apply_cheapest_strategy, apply_performance_strategy,
        apply_optimized_strategy, apply_current_selection,
    )
    st.session_state.update({"opt_cost_weight": 70, "opt_performance_weight": 30,
                             "opt_max_growth_pct": 30})
    base = unconstrained.copy()
    if "Container Numbers" in base.columns:
        pass

    def _scenario_unconstrained(name):
        d = base.copy()
        if name == "Cheapest Cost":
            disp, dl, *_ = apply_cheapest_strategy(d, "Dray SCAC(FL)", {}, False, None, {},
                                                   d.copy(), d.copy(),
                                                   max_constrained_carriers=max_carriers)
            out = dl
        elif name == "Performance":
            out, *_ = apply_performance_strategy(d, "Dray SCAC(FL)", {},
                                                 max_constrained_carriers=max_carriers)
        elif name == "Optimized":
            out, *_ = apply_optimized_strategy(d, "Dray SCAC(FL)", max_carriers, {}, d.copy())
        else:  # Current Selection
            out, *_ = apply_current_selection(d, "Dray SCAC(FL)", max_carriers)
        if "Dray SCAC(FL)" in out.columns and "NEW SCAC" not in out.columns:
            out = out.rename(columns={"Dray SCAC(FL)": "NEW SCAC"})
        elif "Carrier" in out.columns and "NEW SCAC" not in out.columns:
            out = out.rename(columns={"Carrier": "NEW SCAC"})
        return out

    for scen in ["Cheapest Cost", "Performance", "Optimized", "Current Selection"]:
        flip_unc = _scenario_unconstrained(scen)
        res = cf.run_carrier_flip_analysis(
            tender_dfs=[flip_unc], constrained_dfs=[flip_con],
            gvt_df=gvt_raw, rates_df=rate,
        )
        gm = res.get("gvt_merged")
        if gm is None or "Vessel" not in gm.columns:
            print(f"  [{scen}] no gvt_merged/Vessel"); continue
        vsub = gm[gm["Vessel"].astype(str).str.upper() == VESSEL]
        n_hjbt = (vsub["NEW SCAC"].astype(str) == "HJBT").sum()
        verdict = "RESPECTED" if n_hjbt <= 40 else "VIOLATED"
        print(f"  FLIP [{scen:17s}] {VESSEL} HJBT = {n_hjbt:3d}  -> cap 40 {verdict}")
    return None


def main():
    gvt_raw, rate, merged = load_inputs()
    print(f"merged rows={len(merged)} containers={int(merged['Container Count'].sum())}")

    cons_asis = process_constraints_file(CONS_F)

    # Fixed copy: move the vessel name out of Terminal into Vessel for the cap row.
    raw = pd.read_excel(CONS_F, sheet_name="Sheet1")
    fixed_raw = raw.copy()
    mask = fixed_raw["Terminal"].astype(str).str.upper() == VESSEL
    fixed_raw.loc[mask, "Vessel"] = fixed_raw.loc[mask, "Terminal"]
    fixed_raw.loc[mask, "Terminal"] = None
    fixed_tmp = DL / "_pnw_fixed_constraints.xlsx"
    fixed_raw.to_excel(fixed_tmp, index=False)
    cons_fixed = process_constraints_file(fixed_tmp)

    run_one("AS UPLOADED (vessel in Terminal column)", cons_asis, merged, rate, gvt_raw)
    run_one("FIXED (vessel moved to Vessel column)", cons_fixed, merged, rate, gvt_raw)


if __name__ == "__main__":
    main()
