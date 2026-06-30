"""Audit PNW allocations against all PNW rules (docs/PNW_RULES.md).

Runs each GVT file through the SAME pipeline the dashboard uses:
  process GVT -> merge rate -> merge_prebuilt_first(data) -> apply_constraints
  -> enforce_one_vessel_per_carrier (Rules 3/4)
then checks the resulting PNW allocation against every rule and prints a verdict.

Not a unit test — a diagnostic the user asked for. Streamlit is mocked headless.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("streamlit", MagicMock())
import streamlit as st  # noqa: E402
st.session_state = {}
st.cache_data = lambda **k: (lambda f: f)

import warnings  # noqa: E402
warnings.filterwarnings("ignore")
import pandas as pd  # noqa: E402

from components.data.processor import (  # noqa: E402
    validate_and_process_gvt_data, validate_and_process_rate_data, merge_all_data,
)
from components.constraints.prebuilt import (  # noqa: E402
    merge_prebuilt_first, load_pnw_generated_constraints,
)
from components.constraints.processor import apply_constraints_to_data  # noqa: E402
from components.constraints.pnw_vessel_rules import (  # noqa: E402
    enforce_one_vessel_per_carrier_across, check_one_vessel_per_carrier,
    enforce_per_vessel_cap_across, check_per_vessel_cap,
    PER_VESSEL_MAX, HUNT_SCAC, HUNT_PORT, HUNT_WEEKLY_EXACT, PNW_PORTS,
)

DL = Path("C:/Users/maabdiac/Downloads")
RATE_F = DL / "Rate card 5.22.26.xlsx"
GVT_FILES = [
    ("PNW GVT data.xlsx", DL / "PNW GVT data.xlsx", "Sheet3"),
    ("GVT 6-30.xlsx", DL / "Tender optimization data" / "GVT 6-30.xlsx", "Sheet1"),
]

CARRIER = "Dray SCAC(FL)"


def _pnw(df):
    return df[df["Discharged Port"].astype(str).str.upper().isin(
        [p.upper() for p in PNW_PORTS])].copy()


def _real_carrier_mask(s):
    return ~s.astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])


def audit_file(label, gvt_path, sheet):
    print("\n" + "=" * 78)
    print(f"AUDIT: {label}")
    print("=" * 78)
    if not gvt_path.exists():
        print(f"  !! file not found: {gvt_path}")
        return

    gvt = validate_and_process_gvt_data(pd.read_excel(gvt_path, sheet_name=sheet))
    rate = validate_and_process_rate_data(
        pd.read_excel(RATE_F, sheet_name="US Dray Master - 3P"))
    merged = merge_all_data(gvt, rate, pd.DataFrame(), False)

    pnw_in = _pnw(merged)
    print(f"  merged rows={len(merged)}  PNW rows={len(pnw_in)} "
          f"containers={int(pnw_in['Container Count'].sum())}")
    print(f"  PNW ports: {pnw_in['Discharged Port'].value_counts().to_dict()}")

    # Full pipeline (mirrors dashboard.py).
    gen = load_pnw_generated_constraints(merged)
    print(f"  generated PNW rule rows: {len(gen)} "
          f"(Hunt weekly={int(((gen['Carrier']==HUNT_SCAC)&(gen['Week Number'].notna())).sum())}, "
          f"per-vessel caps={int((gen['Maximum Container Count']==PER_VESSEL_MAX).sum())})")
    cons = merge_prebuilt_first(None, merged)
    constrained, unconstrained, summary, maxc, *_ = apply_constraints_to_data(
        merged.copy(), cons, rate)
    # Post-allocation safety nets, across BOTH tables (combined):
    #   Rule 2 cap first (clears over-cap excess), then Rules 3/4 (one vessel/carrier).
    constrained, unconstrained, cap_chg = enforce_per_vessel_cap_across(
        constrained, unconstrained)
    constrained, unconstrained, ov_chg = enforce_one_vessel_per_carrier_across(
        constrained, unconstrained)
    c_chg, u_chg = ov_chg, []

    full = pd.concat([d for d in (constrained, unconstrained) if len(d)],
                     ignore_index=True)
    pnw = _pnw(full)
    pnw = pnw[pnw["Container Count"] > 0]

    failures = []

    # ---- Rule 0: lockouts (AOYV/RDXY not at TIW; RKNE/HJBT not at SEA) ----
    print("\n  [Rule 0] Carrier-to-port lockouts")
    lockouts = {"TIW": ["AOYV", "RDXY"], "SEA": ["RKNE", "HJBT"]}
    for port, banned in lockouts.items():
        sub = pnw[(pnw["Discharged Port"].astype(str).str.upper() == port)
                  & _real_carrier_mask(pnw[CARRIER])]
        present = sub[sub[CARRIER].astype(str).str.strip().str.upper().isin(banned)]
        n = int(present["Container Count"].sum())
        status = "OK" if n == 0 else "VIOLATION"
        if n: failures.append(f"Rule 0: {n} containers for banned carriers at {port}")
        print(f"    {port}: banned {banned} -> {n} containers  [{status}]")

    # ---- Rule 1: HJBT exactly 130/wk at TIW (constrained side holds the locked vol) ----
    print(f"\n  [Rule 1] {HUNT_SCAC} @ {HUNT_PORT}: cap {HUNT_WEEKLY_EXACT}/week")
    hjbt = constrained[(constrained[CARRIER].astype(str).str.strip() == HUNT_SCAC)
                       & (constrained["Discharged Port"].astype(str).str.upper() == HUNT_PORT)]
    by_wk = hjbt.groupby("Week Number")["Container Count"].sum().astype(int)
    avail = pnw_in[(pnw_in[CARRIER].astype(str).str.strip() == HUNT_SCAC)
                   & (pnw_in["Discharged Port"].astype(str).str.upper() == HUNT_PORT)]
    avail_wk = avail.groupby("Week Number")["Container Count"].sum().astype(int)
    for wk in sorted(set(by_wk.index) | set(avail_wk.index)):
        got = int(by_wk.get(wk, 0)); av = int(avail_wk.get(wk, 0))
        over = got > HUNT_WEEKLY_EXACT
        note = "OVER CAP" if over else ("exact 130" if got == HUNT_WEEKLY_EXACT
                                        else f"shortfall (only {av} avail)")
        if over: failures.append(f"Rule 1: HJBT week {wk} = {got} > {HUNT_WEEKLY_EXACT}")
        print(f"    week {wk}: allocated={got:4d}  available={av:4d}  [{note}]")

    # ---- Rule 2: no SCAC > 60 per vessel (PNW), across both tables ----
    print(f"\n  [Rule 2] No SCAC > {PER_VESSEL_MAX} containers per vessel (PNW)")
    sub = pnw[_real_carrier_mask(pnw[CARRIER])]
    g = sub.groupby(["Discharged Port", "Vessel", CARRIER])["Container Count"].sum()
    over = g[g > PER_VESSEL_MAX]
    if len(over):
        failures.append(f"Rule 2: {len(over)} (vessel,carrier) over {PER_VESSEL_MAX}")
        print(f"    VIOLATIONS ({len(over)}):")
        for (port, ves, car), n in over.items():
            print(f"      {port} | {ves} | {car} = {int(n)}")
    else:
        print(f"    OK — max per (vessel,carrier) = "
              f"{int(g.max()) if len(g) else 0} (<= {PER_VESSEL_MAX})")

    # ---- Rules 3/4: one vessel per SCAC among same-day arrivals ----
    print("\n  [Rules 3/4] One vessel per SCAC among same-day arrivals")
    viols = check_one_vessel_per_carrier(full)
    print(f"    enforcement released: {sum(c['containers'] for c in c_chg+u_chg)} "
          f"container(s) across {len(c_chg+u_chg)} split(s)")
    if viols:
        failures.append(f"Rules 3/4: {len(viols)} residual same-day multi-vessel")
        print(f"    RESIDUAL VIOLATIONS ({len(viols)}):")
        for v in viols:
            print(f"      {v['port']} | {v['day']} | {v['carrier']} -> {v['vessels']}")
    else:
        # show where the rule actually applied (days with 2+ vessels)
        days = _pnw(full).copy()
        days["_d"] = pd.to_datetime(days["Ocean ETA"], errors="coerce").dt.normalize()
        multi = days.groupby(["Discharged Port", "_d"])["Vessel"].nunique()
        multi = multi[multi >= 2]
        print(f"    OK — 0 violations. Same-day multi-vessel groups: {len(multi)}")
        for (port, d), n in multi.items():
            print(f"      {port} | {str(d)[:10]} | {int(n)} vessels")

    print("\n  " + "-" * 40)
    if failures:
        print(f"  RESULT: {len(failures)} RULE VIOLATION(S)")
        for f in failures:
            print(f"    ✗ {f}")
    else:
        print("  RESULT: ✅ ALL RULES FOLLOWED")
    return failures


def main():
    all_fail = {}
    for label, path, sheet in GVT_FILES:
        all_fail[label] = audit_file(label, path, sheet)
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for label, fails in all_fail.items():
        print(f"  {label}: {'✅ all rules followed' if not fails else f'✗ {len(fails)} violation(s)'}")


if __name__ == "__main__":
    main()
