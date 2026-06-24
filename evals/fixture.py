"""Deterministic data fixture for the prompt-intent evals.

Every number a case asserts against is derived here in plain Python so the
expectations are *computed*, never hand-copied — if the fixture changes, the
ground-truth helpers below change with it and the cases stay honest.

Shape (small enough to reason about, rich enough to disambiguate intent):

  Carriers : RKNE (incumbent on most), HJBT, ABCD
  Ports    : BAL (HGR6), NYC (EWR9, ABE8)
  Weeks    : 32, 33
  Rates    : ATMI cheaper than RKNE on USBALHGR6; ATMI UNRATED on USNYCEWR9
             FRQT rated on both BAL+NYC lanes; only ATMI rated on USNYCABE8.

The unrated-lane case (ATMI on USNYCEWR9) is deliberate: it lets a case assert
the assistant reports unpriced containers instead of pretending they are free.
"""
from __future__ import annotations

import pandas as pd

CARRIER_COL = "Dray SCAC(FL)"


def working_data() -> pd.DataFrame:
    """The merged GVT+rate table the dashboard would hand the assistant."""
    return pd.DataFrame([
        # week 32 — RKNE incumbent
        {CARRIER_COL: "RKNE", "Discharged Port": "BAL", "Facility": "HGR6",
         "Week Number": 32, "Category": "FBA FCL", "Lane": "USBALHGR6",
         "Container Numbers": "C1, C2, C3, C4", "Container Count": 4,
         "Base Rate": 100.0, "Total Rate": 400.0, "CPC": 110.0, "Total CPC": 440.0,
         "Performance_Score": 0.90},
        {CARRIER_COL: "RKNE", "Discharged Port": "NYC", "Facility": "EWR9",
         "Week Number": 32, "Category": "FBA FCL", "Lane": "USNYCEWR9",
         "Container Numbers": "C5, C6, C7", "Container Count": 3,
         "Base Rate": 200.0, "Total Rate": 600.0, "CPC": 210.0, "Total CPC": 630.0,
         "Performance_Score": 0.80},
        # week 32 — HJBT on the NYC ABE8 lane
        {CARRIER_COL: "HJBT", "Discharged Port": "NYC", "Facility": "ABE8",
         "Week Number": 32, "Category": "Retail CD", "Lane": "USNYCABE8",
         "Container Numbers": "C8, C9", "Container Count": 2,
         "Base Rate": 150.0, "Total Rate": 300.0, "CPC": 160.0, "Total CPC": 320.0,
         "Performance_Score": 0.70},
        # week 33 — ABCD on BAL, RKNE on NYC ABE8
        {CARRIER_COL: "ABCD", "Discharged Port": "BAL", "Facility": "HGR6",
         "Week Number": 33, "Category": "Retail CD", "Lane": "USBALHGR6",
         "Container Numbers": "C10", "Container Count": 1,
         "Base Rate": 130.0, "Total Rate": 130.0, "CPC": 140.0, "Total CPC": 140.0,
         "Performance_Score": 0.95},
        {CARRIER_COL: "RKNE", "Discharged Port": "NYC", "Facility": "ABE8",
         "Week Number": 33, "Category": "FBA FCL", "Lane": "USNYCABE8",
         "Container Numbers": "C11, C12, C13", "Container Count": 3,
         "Base Rate": 175.0, "Total Rate": 525.0, "CPC": 185.0, "Total CPC": 555.0,
         "Performance_Score": 0.85},
        # week 34 — ONE [Lane, Week] group with THREE carriers, designed so the
        # optimizer's cost+performance blend (70/30) does NOT pick the cheapest:
        #   RKNE rate 100 (cheapest), perf 0.80 (worst)
        #   ABCD rate 110,            perf 0.99 (best)   <- blend winner
        #   HJBT rate 200 (pricey decoy that widens the cost range), perf 0.85
        # With min-max normalization the decoy shrinks ABCD's normalized cost to
        # 0.10, so 0.7*0.10+0.3*0 = 0.07 beats RKNE's 0.7*0+0.3*1 = 0.30.
        {CARRIER_COL: "RKNE", "Discharged Port": "BAL", "Facility": "HGR6",
         "Week Number": 34, "Category": "FBA FCL", "Lane": "USBALHGR6",
         "Container Numbers": "C14, C15, C16", "Container Count": 3,
         "Base Rate": 100.0, "Total Rate": 300.0, "CPC": 110.0, "Total CPC": 330.0,
         "Performance_Score": 0.80},
        {CARRIER_COL: "ABCD", "Discharged Port": "BAL", "Facility": "HGR6",
         "Week Number": 34, "Category": "FBA FCL", "Lane": "USBALHGR6",
         "Container Numbers": "C17, C18, C19", "Container Count": 3,
         "Base Rate": 110.0, "Total Rate": 330.0, "CPC": 120.0, "Total CPC": 360.0,
         "Performance_Score": 0.99},
        {CARRIER_COL: "HJBT", "Discharged Port": "BAL", "Facility": "HGR6",
         "Week Number": 34, "Category": "FBA FCL", "Lane": "USBALHGR6",
         "Container Numbers": "C20, C21, C22", "Container Count": 3,
         "Base Rate": 200.0, "Total Rate": 600.0, "CPC": 210.0, "Total CPC": 630.0,
         "Performance_Score": 0.85},
    ])


def rate_data() -> pd.DataFrame:
    """Rate sheet keyed by Lookup = SCAC + Lane (= SCAC + Port + Facility)."""
    return pd.DataFrame([
        # ATMI: cheaper than RKNE on BAL/HGR6; NO rate on NYC/EWR9 (the unrated trap)
        {"Lookup": "ATMIUSBALHGR6", "Base Rate": 80.0, "CPC": 85.0},
        {"Lookup": "ATMIUSNYCABE8", "Base Rate": 140.0, "CPC": 150.0},
        # FRQT: rated on every lane in the data
        {"Lookup": "FRQTUSBALHGR6", "Base Rate": 95.0, "CPC": 99.0},
        {"Lookup": "FRQTUSNYCEWR9", "Base Rate": 150.0, "CPC": 160.0},
        {"Lookup": "FRQTUSNYCABE8", "Base Rate": 160.0, "CPC": 170.0},
        # The incumbents' own published rates (so flip_report can price the OLD side)
        {"Lookup": "RKNEUSBALHGR6", "Base Rate": 100.0, "CPC": 110.0},
        {"Lookup": "RKNEUSNYCEWR9", "Base Rate": 200.0, "CPC": 210.0},
        {"Lookup": "RKNEUSNYCABE8", "Base Rate": 175.0, "CPC": 185.0},
        {"Lookup": "HJBTUSNYCABE8", "Base Rate": 150.0, "CPC": 160.0},
        {"Lookup": "ABCDUSBALHGR6", "Base Rate": 130.0, "CPC": 140.0},
    ])


# ---- ground-truth helpers (computed, not hand-copied) ---------------------

def total_containers() -> int:
    return int(working_data()["Container Count"].sum())


def containers_in_week(week: int) -> int:
    df = working_data()
    return int(df[df["Week Number"] == week]["Container Count"].sum())


def containers_for_carrier(scac: str) -> int:
    df = working_data()
    return int(df[df[CARRIER_COL] == scac]["Container Count"].sum())


def carrier_holding_container(container_id: str) -> str:
    """Current carrier holding a given container ID (for the trace_containers case)."""
    df = working_data()
    for _, r in df.iterrows():
        ids = [c.strip() for c in str(r["Container Numbers"]).split(",") if c.strip()]
        if container_id in ids:
            return str(r[CARRIER_COL])
    return ""


def cheapest_scenario_winner_in_week(week: int, rate_col: str = "Base Rate") -> str:
    """SCAC the Cheapest scenario routes a single-group week to — the carrier with
    the lowest rate in that Lane/Week group. Data-driven so the case can't drift."""
    df = working_data()
    wk = df[df["Week Number"] == week]
    return str(wk.sort_values(rate_col).iloc[0][CARRIER_COL])


def priciest_carrier_by_avg_rate(rate_col: str = "Base Rate") -> str:
    """SCAC with the highest UNWEIGHTED average rate — matches what analyze_data
    'most_expensive' and a naive run_analysis groupby both compute. Data-driven so
    the stress case can't drift when the fixture changes."""
    df = working_data()
    return str(df.groupby(CARRIER_COL)[rate_col].mean().idxmax())


def cheapest_carrier_by_avg_rate(rate_col: str = "Base Rate") -> str:
    df = working_data()
    return str(df.groupby(CARRIER_COL)[rate_col].mean().idxmin())


def cheapest_carrier_on_lane(lane: str, rate_type: str = "Base Rate"):
    """(scac, rate) of the cheapest published rate on a lane, or (None, None)."""
    rd = rate_data()
    rows = rd[rd["Lookup"].str.endswith(lane)]
    if rows.empty:
        return None, None
    rows = rows.assign(scac=rows["Lookup"].str[:4])
    best = rows.sort_values(rate_type).iloc[0]
    return best["scac"], float(best[rate_type])


def cheapest_carrier_in_week(week: int) -> str:
    """SCAC with the lowest Base Rate among the carriers present in a week."""
    df = working_data()
    sub = df[df["Week Number"] == week]
    return str(sub.sort_values("Base Rate").iloc[0][CARRIER_COL])


def optimizer_winner_in_week(week: int,
                             cost_weight: float = 0.70,
                             performance_weight: float = 0.30) -> str:
    """SCAC the optimizer's cost+performance blend routes a week's volume to.

    Computed by running the SAME LP the dashboard uses on the week's slice, so the
    expectation can never drift from the engine. For week 34 this is ABCD (best
    performer) even though RKNE is the cheapest rate — the case that asserts
    'recommend != cheapest' relies on these two helpers disagreeing.
    """
    from optimization.linear_programming import optimize_carrier_allocation
    df = working_data()
    sub = df[df["Week Number"] == week].copy()
    allocated = optimize_carrier_allocation(
        sub, cost_weight=cost_weight, performance_weight=performance_weight,
        carrier_column=CARRIER_COL,
    )
    g = (allocated.assign(_c=allocated["Container Count"])
         .groupby(CARRIER_COL)["_c"].sum().sort_values(ascending=False))
    return str(g.index[0])


def applied_constraints_summary() -> list:
    """A realistic Applied Constraints Summary for the read_constraints_summary case.

    Shaped like the per-rule outcome dicts ``constraints_processor`` emits and the
    dashboard stashes in ``st.session_state['chatbot_constraint_summary']``. Built
    against the NYC/EWR9 lane, which holds only 3 RKNE containers in the fixture:

      * P95 — cap RKNE at 2 on NYC/EWR9: applied in full (claims 2 of the 3).
      * P80 — floor FRQT at 5 on NYC/EWR9: PARTIAL. Only 1 container remained
        after P95 took 2, so FRQT gets 1, not 5 — a shortfall whose cause is the
        higher-priority P95 claim plus a thin eligible pool.

    The assistant should read this and explain the shortfall from 'claimed_by' /
    'eligible' / 'why' rather than guessing.
    """
    return [
        {
            "priority": 95,
            "description": "Priority 95: Carrier=RKNE, Port=NYC, Lane=EWR9 (Max 2)",
            "status": "Applied",
            "containers_allocated": 2,
            "eligible_containers": 3,
            "claimed_by": None,
            "target_containers": 2,
            "method": "Maximum: 2",
            "scope": {"Port": "NYC", "Lane": "USNYCEWR9", "Target Carrier": "RKNE"},
            "reason": None,
        },
        {
            "priority": 80,
            "description": "Priority 80: Carrier=FRQT, Port=NYC, Lane=EWR9 (Min 5)",
            "status": "Partial (shortfall: 4)",
            "containers_allocated": 1,
            "eligible_containers": 1,
            "claimed_by": {95: 2},
            "target_containers": 5,
            "method": "Minimum: 5",
            "scope": {"Port": "NYC", "Lane": "USNYCEWR9", "Target Carrier": "FRQT"},
            "reason": ("Target was 5 but only 1 container was eligible: 2 of the 3 "
                       "in this scope were already claimed by: P95(2)."),
        },
    ]
