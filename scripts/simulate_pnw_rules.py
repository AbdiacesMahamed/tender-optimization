"""Simulate the PNW allocation BEFORE vs AFTER all PNW rules, on the provided data.

Runs each GVT file through the SAME pipeline the dashboard uses (process GVT ->
merge rate -> merge_prebuilt_first(data) -> apply_constraints -> the two PNW
post-allocation safety nets) and reports, for the PNW slice:

  * Original per-carrier volume (as the GVT data arrived), per port.
  * Final per-carrier volume after every rule, per port.
  * The net delta per carrier (who gains, who sheds), and how much volume was
    RELEASED (carrier cleared) for the optimizer to re-home.
  * A per-rule movement breakdown (lockouts, Hunt 130/wk, 60/vessel cap, one
    vessel per same-day arrival).

Not a unit test — a what-if the user asked for. Streamlit is mocked headless.
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
    enforce_one_vessel_per_carrier_across, enforce_per_vessel_cap_across,
    PER_VESSEL_MAX, HUNT_SCAC, HUNT_PORT, HUNT_WEEKLY_MAX, PNW_PORTS,
    PORT_LOCKED_OUT_CARRIERS,
)
from config.carrier_mapping import get_carrier_name  # noqa: E402

DL = Path("C:/Users/maabdiac/Downloads")
RATE_F = DL / "Rate card 5.22.26.xlsx"
GVT_FILES = [
    ("PNW GVT data.xlsx", DL / "PNW GVT data.xlsx", "Sheet3"),
    ("GVT 6-30.xlsx", DL / "Tender optimization data" / "GVT 6-30.xlsx", "Sheet1"),
]

CARRIER = "Dray SCAC(FL)"
COUNT = "Container Count"


def _pnw(df):
    if df is None or len(df) == 0:
        return pd.DataFrame()
    return df[df["Discharged Port"].astype(str).str.upper().isin(
        [p.upper() for p in PNW_PORTS])].copy()


def _real(df):
    if df is None or len(df) == 0:
        return df
    return df[~df[CARRIER].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])]


def _by_carrier_port(df):
    """{(port, carrier): containers} for real (assigned) PNW rows."""
    d = _real(_pnw(df))
    if d is None or len(d) == 0:
        return {}
    g = d.assign(_c=pd.to_numeric(d[COUNT], errors="coerce").fillna(0)).groupby(
        [d["Discharged Port"].astype(str).str.upper(),
         d[CARRIER].astype(str).str.strip()])["_c"].sum()
    return {k: int(v) for k, v in g.items() if v}


def _released(df):
    """Containers with the carrier cleared (to be re-homed by the optimizer), PNW only."""
    d = _pnw(df)
    if d is None or len(d) == 0:
        return 0
    blank = d[d[CARRIER].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])]
    return int(pd.to_numeric(blank[COUNT], errors="coerce").fillna(0).sum())


def simulate(label, gvt_path, sheet):
    print("\n" + "=" * 80)
    print(f"SIMULATION: {label}")
    print("=" * 80)
    if not gvt_path.exists():
        print(f"  !! file not found: {gvt_path}")
        return

    gvt = validate_and_process_gvt_data(pd.read_excel(gvt_path, sheet_name=sheet))
    rate = validate_and_process_rate_data(
        pd.read_excel(RATE_F, sheet_name="US Dray Master - 3P"))
    merged = merge_all_data(gvt, rate, pd.DataFrame(), False)

    pnw0 = _pnw(merged)
    orig = _by_carrier_port(merged)
    total_pnw = int(pd.to_numeric(pnw0[COUNT], errors="coerce").fillna(0).sum())
    print(f"  PNW containers in: {total_pnw}  "
          f"({pnw0['Discharged Port'].value_counts().to_dict()})")

    # ---- run the full pipeline ----
    gen = load_pnw_generated_constraints(merged)
    cons = merge_prebuilt_first(None, merged)
    constrained, unconstrained, summary, maxc, *_ = apply_constraints_to_data(
        merged.copy(), cons, rate)
    constrained, unconstrained, cap_chg = enforce_per_vessel_cap_across(
        constrained, unconstrained)
    constrained, unconstrained, ov_chg = enforce_one_vessel_per_carrier_across(
        constrained, unconstrained)

    full = pd.concat([d for d in (constrained, unconstrained) if len(d)],
                     ignore_index=True)
    final = _by_carrier_port(full)
    released = _released(full)

    # ================= per-carrier BEFORE -> AFTER, by port =================
    print("\n  ── Per-carrier volume: BEFORE → AFTER (by port) ──")
    print(f"    {'Port':4} {'SCAC':5} {'Carrier':24} {'before':>7} {'after':>7} {'delta':>7}")
    keys = sorted(set(orig) | set(final))
    for (port, scac) in keys:
        b = orig.get((port, scac), 0)
        a = final.get((port, scac), 0)
        if b == 0 and a == 0:
            continue
        d = a - b
        flag = ""
        if scac in PORT_LOCKED_OUT_CARRIERS.get(port, set()):
            flag = "  <- locked out here"
        mark = "+" if d > 0 else ""
        print(f"    {port:4} {scac:5} {get_carrier_name(scac)[:24]:24} "
              f"{b:7d} {a:7d} {mark}{d:6d}{flag}")
    locked_in = sum(a for (p, c), a in final.items())
    print(f"    {'':4} {'':5} {'TOTAL assigned (PNW)':24} {total_pnw:7d} {locked_in:7d}")
    print(f"    {'':4} {'':5} {'RELEASED for re-home':24} {'':7} {released:7d}  "
          "(carrier cleared; optimizer re-assigns)")

    # ================= per-rule movement =================
    print("\n  ── What each rule did ──")

    # Rule 0 — lockouts: original volume that was on a banned carrier at a port.
    lock_moved = 0
    for (port, scac), b in orig.items():
        if scac in PORT_LOCKED_OUT_CARRIERS.get(port, set()):
            lock_moved += b
    print(f"    Rule 0 (port lockouts): {lock_moved} container(s) were on a carrier "
          "banned at their port and were moved off it.")
    for (port, scac), b in sorted(orig.items()):
        if scac in PORT_LOCKED_OUT_CARRIERS.get(port, set()):
            print(f"        {scac} @ {port}: {b} -> {final.get((port, scac), 0)}")

    # Rule 1 — Hunt 130/wk at TIW: show the weekly cap outcome (constrained side).
    print(f"    Rule 1 (Hunt {HUNT_WEEKLY_MAX}/wk @ {HUNT_PORT}):")
    hjbt = constrained[(constrained[CARRIER].astype(str).str.strip() == HUNT_SCAC)
                       & (constrained["Discharged Port"].astype(str).str.upper() == HUNT_PORT)]
    avail = pnw0[(pnw0[CARRIER].astype(str).str.strip() == HUNT_SCAC)
                 & (pnw0["Discharged Port"].astype(str).str.upper() == HUNT_PORT)]
    a_wk = avail.groupby("Week Number")[COUNT].sum().astype(int)
    g_wk = hjbt.groupby("Week Number")[COUNT].sum().astype(int)
    for wk in sorted(set(a_wk.index) | set(g_wk.index)):
        got, av = int(g_wk.get(wk, 0)), int(a_wk.get(wk, 0))
        note = ("locked at cap 130" if got == HUNT_WEEKLY_MAX
                else f"short of 130 (only {av} available)")
        print(f"        week {int(wk):>2}: locked {got:4d} / available {av:4d}  ({note})")

    # Rule 2 — per-vessel cap releases.
    cap_total = sum(c["containers"] for c in cap_chg)
    print(f"    Rule 2 (≤{PER_VESSEL_MAX}/vessel): released {cap_total} container(s) "
          f"over the limit across {len(cap_chg)} (vessel, carrier) group(s).")
    for c in sorted(cap_chg, key=lambda x: -x["containers"])[:8]:
        print(f"        {c['carrier']} on {c['vessel']} ({c['port']}): -{c['containers']}")

    # Rules 3/4 — one vessel per carrier among same-day arrivals.
    ov_total = sum(c["containers"] for c in ov_chg)
    print(f"    Rules 3/4 (one vessel per carrier, same-day): released {ov_total} "
          f"container(s) across {len(ov_chg)} carrier/vessel split(s).")
    for c in sorted(ov_chg, key=lambda x: -x["containers"])[:8]:
        print(f"        {c['carrier']} @ {c['port']} {str(c['day'])[:10]}: "
              f"dropped {c['released_vessel']} (-{c['containers']}), kept {c['kept_vessel']}")

    print("\n  ── Net effect ──")
    movers = sorted(((p, c, final.get((p, c), 0) - orig.get((p, c), 0))
                     for (p, c) in keys),
                    key=lambda t: abs(t[2]), reverse=True)
    gained = [(p, c, d) for p, c, d in movers if d > 0][:5]
    shed = [(p, c, d) for p, c, d in movers if d < 0][:5]
    print("    Biggest gainers:", ", ".join(f"{c}@{p} +{d}" for p, c, d in gained) or "none")
    print("    Biggest shedders:", ", ".join(f"{c}@{p} {d}" for p, c, d in shed) or "none")
    print(f"    {released} PNW container(s) end up unassigned and flow to the "
          "scenario optimizer to be re-homed onto eligible (non-banned, under-cap) carriers.")


def main():
    for label, path, sheet in GVT_FILES:
        simulate(label, path, sheet)
    print("\n" + "=" * 80)
    print("Note: 'after' = volume locked to a carrier by the rules. 'RELEASED' volume")
    print("is intentionally left carrier-blank so the dashboard's scenario optimizer")
    print("re-assigns it (cheapest/performance/optimized) among carriers the rules allow.")
    print("=" * 80)


if __name__ == "__main__":
    main()
