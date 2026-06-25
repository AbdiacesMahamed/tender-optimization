"""Stress tests: the Carrier Flip report must respect input constraints across
ALL scenarios.

The flip report (`run_carrier_flip_analysis`) merges TWO allocations into one
container->carrier mapping:

  * the *unconstrained* allocation — the optimizer is free to pick any carrier
    (this is what the selected scenario — Cheapest / Performance / Optimized /
    Current Selection — produces for the manipulable volume), and
  * the *constrained* allocation — containers a user constraint LOCKED to a
    specific carrier.

When the SAME container shows up in both (an optimizer freely assigned it, but a
constraint also pinned it), the constraint must win. These tests prove that
invariant holds no matter which scenario produced the unconstrained side, plus a
battery of adversarial edge cases on the dedup that enforces it.

Two layers:
  1. Engine-level: feed `run_carrier_flip_analysis` constrained + unconstrained
     frames directly and assert the constrained carrier always wins the dedup.
  2. Scenario-level (end-to-end): run each REAL strategy function from
     `components.scenarios.strategies` to produce the unconstrained allocation,
     then feed it (with a conflicting constrained frame) through the flip report
     and assert every locked container still reports its constrained carrier.
"""
import sys
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

# Strategy functions read st.session_state / st.info etc. Install a non-clobbering
# mock so this file is safe to run alongside the rest of the suite.
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = MagicMock()
import streamlit as st  # noqa: E402
st.session_state = {}

from components.reporting import carrier_flip as cf  # noqa: E402
from components.scenarios.strategies import (  # noqa: E402
    apply_cheapest_strategy,
    apply_performance_strategy,
    apply_optimized_strategy,
    apply_current_selection,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _gvt(containers, scacs, ports=None, facilities=None):
    """Minimal GVT frame keyed on Container + original Dray SCAC."""
    n = len(containers)
    return pd.DataFrame({
        "Container": containers,
        "Dray SCAC(FL)": scacs,
        "Discharged Port": ports or ["TIW"] * n,
        "Facility": facilities or ["TIW1"] * n,
    })


def _flip_new_scac(gvt_merged, container):
    """Return the NEW SCAC the flip report assigned to a container."""
    key = cf._normalize_container(container)
    row = gvt_merged[gvt_merged["Container"].map(cf._normalize_container) == key]
    assert len(row) == 1, f"expected exactly one row for {container}, got {len(row)}"
    return row.iloc[0]["NEW SCAC"]


# ===========================================================================
# Layer 1 — engine-level: constrained always wins the dedup
# ===========================================================================

class TestConstrainedWinsDedup:
    def test_constraint_beats_unconstrained_same_container(self):
        unc = pd.DataFrame({"NEW SCAC": ["ATMI"], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"]})
        con = pd.DataFrame({"NEW SCAC": ["RKNE"], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"]})
        res = cf.run_carrier_flip_analysis(tender_dfs=[unc], constrained_dfs=[con],
                                           gvt_df=_gvt(["ZZZU1234567"], ["HJBT"]))
        assert _flip_new_scac(res["gvt_merged"], "ZZZU1234567") == "RKNE"

    @pytest.mark.parametrize("unc_scac,con_scac", [
        ("AAAA", "ZZZZ"),   # constrained sorts LATER alphabetically
        ("ZZZZ", "AAAA"),   # constrained sorts EARLIER alphabetically
        ("MMMM", "MMMM"),   # identical — must not crash or duplicate
    ])
    def test_priority_independent_of_alphabetical_order(self, unc_scac, con_scac):
        unc = pd.DataFrame({"NEW SCAC": [unc_scac], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"]})
        con = pd.DataFrame({"NEW SCAC": [con_scac], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"]})
        res = cf.run_carrier_flip_analysis(tender_dfs=[unc], constrained_dfs=[con],
                                           gvt_df=_gvt(["ZZZU1234567"], ["HJBT"]))
        gm = res["gvt_merged"]
        # Exactly one row per GVT container (no dupes from the concat).
        assert (gm["Container"].map(cf._normalize_container) == "ZZZU1234567").sum() == 1
        assert _flip_new_scac(gm, "ZZZU1234567") == con_scac

    def test_nan_constrained_falls_through_to_unconstrained(self):
        # A constrained frame that does NOT actually assign this container (NaN
        # carrier) must not blank it out — the unconstrained pick stands.
        unc = pd.DataFrame({"NEW SCAC": ["ATMI"], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"]})
        con = pd.DataFrame({"NEW SCAC": [np.nan], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"]})
        res = cf.run_carrier_flip_analysis(tender_dfs=[unc], constrained_dfs=[con],
                                           gvt_df=_gvt(["ZZZU1234567"], ["HJBT"]))
        assert _flip_new_scac(res["gvt_merged"], "ZZZU1234567") == "ATMI"

    def test_constrained_only_container_kept(self):
        # A container present ONLY in the constrained frame still reaches the report.
        unc = pd.DataFrame({"NEW SCAC": ["ATMI"], "Container Numbers": ["AAAU1111111"],
                            "Lane": ["USTIWTIW1"]})
        con = pd.DataFrame({"NEW SCAC": ["RKNE"], "Container Numbers": ["BBBU2222222"],
                            "Lane": ["USTIWTIW1"]})
        gvt = _gvt(["AAAU1111111", "BBBU2222222"], ["HJBT", "HJBT"])
        res = cf.run_carrier_flip_analysis(tender_dfs=[unc], constrained_dfs=[con], gvt_df=gvt)
        gm = res["gvt_merged"]
        assert _flip_new_scac(gm, "AAAU1111111") == "ATMI"
        assert _flip_new_scac(gm, "BBBU2222222") == "RKNE"

    def test_multiple_constrained_files_all_win(self):
        # Two constrained frames + one unconstrained; every locked container wins.
        unc = pd.DataFrame({
            "NEW SCAC": ["ATMI", "ATMI"],
            "Container Numbers": ["AAAU1111111", "BBBU2222222"],
            "Lane": ["USTIWTIW1", "USTIWTIW1"]})
        con1 = pd.DataFrame({"NEW SCAC": ["RKNE"], "Container Numbers": ["AAAU1111111"],
                             "Lane": ["USTIWTIW1"]})
        con2 = pd.DataFrame({"NEW SCAC": ["FRQT"], "Container Numbers": ["BBBU2222222"],
                             "Lane": ["USTIWTIW1"]})
        gvt = _gvt(["AAAU1111111", "BBBU2222222"], ["HJBT", "HJBT"])
        res = cf.run_carrier_flip_analysis(tender_dfs=[unc],
                                           constrained_dfs=[con1, con2], gvt_df=gvt)
        gm = res["gvt_merged"]
        assert _flip_new_scac(gm, "AAAU1111111") == "RKNE"
        assert _flip_new_scac(gm, "BBBU2222222") == "FRQT"

    def test_savings_priced_against_constrained_carrier(self):
        # The savings number must reflect the CONSTRAINED carrier's rate, not the
        # unconstrained one — otherwise the dollars lie about what will ship.
        unc = pd.DataFrame({"NEW SCAC": ["ATMI"], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"], "FC": ["TIW1"]})
        con = pd.DataFrame({"NEW SCAC": ["RKNE"], "Container Numbers": ["ZZZU1234567"],
                            "Lane": ["USTIWTIW1"], "FC": ["TIW1"]})
        gvt = _gvt(["ZZZU1234567"], ["HJBT"])
        rates = pd.DataFrame({
            "Lookup": ["HJBTUSTIWTIW1", "ATMIUSTIWTIW1", "RKNEUSTIWTIW1"],
            "Base Rate": [300, 100, 250],
        })
        res = cf.run_carrier_flip_analysis(tender_dfs=[unc], constrained_dfs=[con],
                                           gvt_df=gvt, rates_df=rates)
        row = res["gvt_merged"].iloc[0]
        assert row["NEW SCAC"] == "RKNE"
        assert row["New Rate"] == 250          # RKNE's rate, not ATMI's 100
        assert row["Savings"] == 300 - 250     # vs old HJBT 300

    def test_no_duplicate_rows_after_dedup_at_scale(self):
        # 200 containers each present in BOTH frames — output must stay 1 row each.
        ids = [f"AAAU{str(i).zfill(7)}" for i in range(200)]
        unc = pd.DataFrame({"NEW SCAC": ["ATMI"] * 200, "Container Numbers": ids,
                            "Lane": ["USTIWTIW1"] * 200})
        con = pd.DataFrame({"NEW SCAC": ["RKNE"] * 200, "Container Numbers": ids,
                            "Lane": ["USTIWTIW1"] * 200})
        gvt = _gvt(ids, ["HJBT"] * 200)
        res = cf.run_carrier_flip_analysis(tender_dfs=[unc], constrained_dfs=[con], gvt_df=gvt)
        gm = res["gvt_merged"]
        assert len(gm) == 200
        assert (gm["NEW SCAC"] == "RKNE").all()


# ===========================================================================
# Layer 2 — scenario-level end-to-end: every strategy feeds a constraint-
# respecting flip report.
# ===========================================================================

@pytest.fixture
def scenario_data():
    """Manipulable (unconstrained) allocation input shared by all strategies.

    Two carriers on one lane, with rate + performance so each strategy has a real
    reason to prefer a different winner:
      ATMI  — cheap (100), low performance (0.50)
      RKNE  — pricey (250), high performance (0.95)
    A Cheapest run picks ATMI; a Performance run picks RKNE; Optimized blends.
    """
    return pd.DataFrame({
        "Discharged Port": ["TIW", "TIW"],
        "Category": ["TL", "TL"],
        "Dray SCAC(FL)": ["ATMI", "RKNE"],
        "Lane": ["USTIWTIW1", "USTIWTIW1"],
        "Facility": ["TIW1", "TIW1"],
        "Week Number": [9, 9],
        "Container Numbers": ["AAAU1111111, AAAU2222222", "AAAU1111111, AAAU2222222"],
        "Container Count": [2, 2],
        "Base Rate": [100.0, 250.0],
        "Total Rate": [200.0, 500.0],
        "Performance_Score": [0.50, 0.95],
    })


def _run_flip_with_constraint(unconstrained_alloc, locked_container, locked_carrier):
    """Feed a strategy's output + a conflicting constraint through the flip report."""
    # The constraint locks `locked_container` to `locked_carrier` regardless of what
    # the unconstrained allocation chose.
    constrained = pd.DataFrame({
        "NEW SCAC": [locked_carrier],
        "Container Numbers": [locked_container],
        "Lane": ["USTIWTIW1"],
        "FC": ["TIW1"],
    })
    gvt = _gvt(["AAAU1111111", "AAAU2222222"], ["HJBT", "HJBT"])
    return cf.run_carrier_flip_analysis(
        tender_dfs=[unconstrained_alloc],
        constrained_dfs=[constrained],
        gvt_df=gvt,
    )


def _normalize_alloc_for_flip(display_data, carrier_col="Dray SCAC(FL)"):
    """Mirror metrics.py: rename the carrier column to 'NEW SCAC' so the flip engine
    recognizes the assigned carrier, matching how the dashboard wires the source."""
    out = display_data.copy()
    # Strategies emit a 'Carrier' column (renamed from the SCAC col) and/or keep the
    # original. The flip engine looks for NEW SCAC / Carrier / SCAC in that order.
    if "NEW SCAC" not in out.columns:
        if carrier_col in out.columns:
            out = out.rename(columns={carrier_col: "NEW SCAC"})
        elif "Carrier" in out.columns:
            out = out.rename(columns={"Carrier": "NEW SCAC"})
    return out


class TestEveryScenarioRespectsConstraints:
    """For each scenario, the unconstrained side is whatever that strategy picks;
    the constraint must still win in the flip report."""

    def setup_method(self):
        st.session_state = {
            "opt_cost_weight": 70, "opt_performance_weight": 30, "opt_max_growth_pct": 30,
        }

    def test_cheapest_scenario(self, scenario_data):
        display, download, *_ = apply_cheapest_strategy(
            scenario_data.copy(), "Dray SCAC(FL)", {}, False, None, {},
            scenario_data.copy(), scenario_data.copy(),
        )
        alloc = _normalize_alloc_for_flip(download)
        # Cheapest would pick ATMI; constraint pins AAAU1111111 to RKNE.
        res = _run_flip_with_constraint(alloc, "AAAU1111111", "RKNE")
        assert _flip_new_scac(res["gvt_merged"], "AAAU1111111") == "RKNE"

    def test_performance_scenario(self, scenario_data):
        display, *_ = apply_performance_strategy(
            scenario_data.copy(), "Dray SCAC(FL)", {},
        )
        alloc = _normalize_alloc_for_flip(display)
        # Performance would pick RKNE; constraint pins AAAU1111111 to ATMI.
        res = _run_flip_with_constraint(alloc, "AAAU1111111", "ATMI")
        assert _flip_new_scac(res["gvt_merged"], "AAAU1111111") == "ATMI"

    def test_optimized_scenario(self, scenario_data):
        display, *_ = apply_optimized_strategy(
            scenario_data.copy(), "Dray SCAC(FL)", [], {}, scenario_data.copy(),
        )
        alloc = _normalize_alloc_for_flip(display)
        res = _run_flip_with_constraint(alloc, "AAAU1111111", "FRQT")
        assert _flip_new_scac(res["gvt_merged"], "AAAU1111111") == "FRQT"

    def test_current_selection_scenario(self, scenario_data):
        display, *_ = apply_current_selection(
            scenario_data.copy(), "Dray SCAC(FL)", [],
        )
        alloc = _normalize_alloc_for_flip(display)
        res = _run_flip_with_constraint(alloc, "AAAU1111111", "RKNE")
        assert _flip_new_scac(res["gvt_merged"], "AAAU1111111") == "RKNE"


class TestOptimizedReallocatedMetric:
    """Regression: the optimized scenario's 'reallocated' count must reflect real
    movement. It used to parse the Volume_Change LABEL string ('↑ Increase') as a
    number, which coerces to all-zeros, so the count was permanently 0/0 even when
    volume clearly shifted between carriers."""

    def setup_method(self):
        st.session_state = {
            "opt_cost_weight": 70, "opt_performance_weight": 30, "opt_max_growth_pct": 30,
        }

    def test_reallocated_nonzero_when_volume_moves(self):
        # One lane/week/category, two carriers split 50/50 historically. The
        # cost+performance blend rebalances the split, so at least one container
        # moves -> reallocated must be > 0 (was 0 under the string-parse bug).
        data = pd.DataFrame({
            "Discharged Port": ["TIW", "TIW"],
            "Category": ["TL", "TL"],
            "Dray SCAC(FL)": ["AAAA", "BBBB"],
            "Lane": ["USTIWTIW1", "USTIWTIW1"],
            "Facility": ["TIW1", "TIW1"],
            "Week Number": [34, 34],
            "Container Numbers": [", ".join(f"A{i}" for i in range(5)),
                                  ", ".join(f"B{i}" for i in range(5))],
            "Container Count": [5, 5],
            "Base Rate": [100.0, 90.0],
            "Total Rate": [500.0, 450.0],
            "Performance_Score": [0.80, 0.99],
        })
        display, reallocated, groups_impacted = apply_optimized_strategy(
            data.copy(), "Dray SCAC(FL)", [], {}, data.copy(),
        )
        # Volume genuinely shifts (BBBB is both cheaper and higher-performing), so
        # the metric must register movement rather than the old permanent zero.
        assert reallocated > 0
        assert groups_impacted >= 1

    def test_reallocated_zero_when_nothing_moves(self):
        # A single-carrier group has nowhere to reallocate to -> 0 is correct.
        data = pd.DataFrame({
            "Discharged Port": ["TIW"],
            "Category": ["TL"],
            "Dray SCAC(FL)": ["AAAA"],
            "Lane": ["USTIWTIW1"],
            "Facility": ["TIW1"],
            "Week Number": [34],
            "Container Numbers": [", ".join(f"A{i}" for i in range(4))],
            "Container Count": [4],
            "Base Rate": [100.0],
            "Total Rate": [400.0],
            "Performance_Score": [0.80],
        })
        display, reallocated, groups_impacted = apply_optimized_strategy(
            data.copy(), "Dray SCAC(FL)", [], {}, data.copy(),
        )
        assert reallocated == 0
        assert groups_impacted == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
