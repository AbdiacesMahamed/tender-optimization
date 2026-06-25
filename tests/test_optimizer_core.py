"""
Tests for the optimization-aware assistant tools.

These prove the agent reasons the way the dashboard's optimizer does — a weighted
cost+performance blend, NOT naive cheapest — and that the direct-apply path mutates
the live optimization correctly while the analytical handlers stay pure (no
session-state access, no input mutation).

Everything runs offline: the optimizer functions are pure pandas/PuLP, and the
executor is exercised with a dict-backed fake session state (no Streamlit runtime,
no Bedrock).
"""
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

# Mock Streamlit before importing modules whose package __init__ touches it.
sys.modules.setdefault("streamlit", MagicMock())
import streamlit as st  # noqa: E402
st.cache_data = lambda **kwargs: (lambda f: f)


class _SessionState(dict):
    """Dict that also supports attribute access, like st.session_state.

    The chat executor both ``.get(...)`` and attribute-assigns on session state;
    a plain dict rejects attribute writes, so mirror the app's behavior (this is
    the same shim the eval harness uses).
    """
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


st.session_state = _SessionState()

from components.chatbot import optimizer_core as OC  # noqa: E402
from components.chatbot import tools as T  # noqa: E402


# ==================== fixtures ====================

@pytest.fixture
def blend_data():
    """One [Lane, Week] group where cheapest-by-rate is NOT the optimizer winner.

    At 70/30 the optimizer minimizes cost_weight*norm_cost + perf_weight*(1-norm_perf):
      - CHEP: rate 100 (cheapest), perf 0.80 (worst) -> coeff 0.7*0   + 0.3*1     = 0.300
      - MIDD: rate 110,            perf 0.99 (best)  -> coeff 0.7*0.10 + 0.3*0     = 0.070  <- winner
      - EXPN: rate 200 (priciest), perf 0.90         -> coeff 0.7*1    + 0.3*0.474 = 0.842
    So the optimizer routes all volume to MIDD even though CHEP is the cheapest rate.
    """
    return pd.DataFrame([
        {"Dray SCAC(FL)": "CHEP", "Lane": "USBALHGR6", "Week Number": 32,
         "Category": "FBA FCL", "Discharged Port": "BAL", "Facility": "HGR6",
         "Container Numbers": "A1, A2, A3, A4, A5, A6, A7, A8, A9, A10",
         "Container Count": 10, "Base Rate": 100.0, "Total Rate": 1000.0,
         "Performance_Score": 0.80},
        {"Dray SCAC(FL)": "MIDD", "Lane": "USBALHGR6", "Week Number": 32,
         "Category": "FBA FCL", "Discharged Port": "BAL", "Facility": "HGR6",
         "Container Numbers": "B1, B2, B3, B4, B5, B6, B7, B8, B9, B10",
         "Container Count": 10, "Base Rate": 110.0, "Total Rate": 1100.0,
         "Performance_Score": 0.99},
        {"Dray SCAC(FL)": "EXPN", "Lane": "USBALHGR6", "Week Number": 32,
         "Category": "FBA FCL", "Discharged Port": "BAL", "Facility": "HGR6",
         "Container Numbers": "D1, D2, D3, D4, D5, D6, D7, D8, D9, D10",
         "Container Count": 10, "Base Rate": 200.0, "Total Rate": 2000.0,
         "Performance_Score": 0.90},
    ])


@pytest.fixture
def rate_data():
    return pd.DataFrame([
        {"Lookup": "CHEPUSBALHGR6", "Base Rate": 100.0},
        {"Lookup": "MIDDUSBALHGR6", "Base Rate": 110.0},
        {"Lookup": "EXPNUSBALHGR6", "Base Rate": 200.0},
    ])


# ==================== recommend_carriers_core (optimizer blend) ====================

def test_recommend_is_not_naive_cheapest(blend_data):
    out = OC.recommend_carriers_core(
        blend_data, {"weeks": [32]},
        cost_weight=0.70, performance_weight=0.30, max_growth_pct=0.30, top_n=5,
    )
    assert "error" not in out
    # The cheapest rate is CHEP, but the optimizer blend recommends MIDD.
    assert out["recommended"]["carrier"] == "MIDD"
    assert out["recommended"]["optimizer_allocated_containers"] == 30
    # CHEP is present and is genuinely the cheapest by rate — proving the
    # recommendation diverges from cheapest-by-rate on purpose.
    by_carrier = {r["carrier"]: r for r in out["ranked_carriers"]}
    assert by_carrier["CHEP"]["avg_base_rate"] == 100.0
    assert by_carrier["MIDD"]["avg_base_rate"] == 110.0
    assert out["weights"] == {"cost": 0.7, "performance": 0.3}


def test_recommend_follows_the_weights(blend_data):
    # Crank performance to 100%: the best-performer MIDD must still win, and a
    # cost-only run should instead favor the cheapest CHEP.
    perf_heavy = OC.recommend_carriers_core(
        blend_data, {"weeks": [32]},
        cost_weight=0.0, performance_weight=1.0, max_growth_pct=0.30,
    )
    assert perf_heavy["recommended"]["carrier"] == "MIDD"

    cost_only = OC.recommend_carriers_core(
        blend_data, {"weeks": [32]},
        cost_weight=1.0, performance_weight=0.0, max_growth_pct=0.30,
    )
    assert cost_only["recommended"]["carrier"] == "CHEP"


def test_recommend_empty_and_missing_columns(blend_data):
    assert "error" in OC.recommend_carriers_core(None, {}, cost_weight=0.7,
                                                  performance_weight=0.3, max_growth_pct=0.3)
    assert "error" in OC.recommend_carriers_core(pd.DataFrame(), {}, cost_weight=0.7,
                                                  performance_weight=0.3, max_growth_pct=0.3)
    no_rate = blend_data.drop(columns=["Base Rate"])
    assert "error" in OC.recommend_carriers_core(no_rate, {"weeks": [32]},
                                                  cost_weight=0.7, performance_weight=0.3,
                                                  max_growth_pct=0.3)


def test_recommend_scope_matches_nothing(blend_data):
    out = OC.recommend_carriers_core(blend_data, {"weeks": [99]},
                                     cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert out.get("matched_containers") == 0
    assert "note" in out


def test_recommend_does_not_mutate_input(blend_data):
    before = blend_data.copy()
    OC.recommend_carriers_core(blend_data, {"weeks": [32]},
                               cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert_frame_equal(blend_data, before)


# ==================== cost_perf_rollup ====================

def test_cost_perf_rollup(blend_data):
    roll = OC.cost_perf_rollup(blend_data)
    assert roll["containers"] == 30
    assert roll["total_cost"] == 4100.0  # 1000 + 1100 + 2000
    # Volume-weighted perf = (0.80+0.99+0.90)*10 / 30
    assert roll["avg_performance"] == pytest.approx((0.80 + 0.99 + 0.90) / 3, abs=1e-3)
    assert set(roll["carrier_mix"]) == {"CHEP", "MIDD", "EXPN"}
    assert roll["carrier_mix"]["CHEP"]["pct"] == pytest.approx(33.3, abs=0.1)


# ==================== constraint_impact_core (what-if through the optimizer) ====================

def test_constraint_impact_runs_and_reports_delta(blend_data, rate_data):
    # Cap EXPN (the priciest) at 0 in this scope — a lockout. The optimizer should
    # then route the freed volume to the blend winner, lowering total cost vs the
    # as-loaded mix.
    constraints_df = T.constraints_to_dataframe([
        T._normalize_constraint({"Carrier": "EXPN", "Lane": "USBALHGR6",
                                 "Maximum Container Count": 0, "Priority Score": 100})
    ])
    out = OC.constraint_impact_core(
        blend_data, constraints_df, rate_data,
        cost_weight=0.70, performance_weight=0.30, max_growth_pct=0.30,
    )
    assert "error" not in out
    assert "current" in out and "proposed" in out
    assert out["current"]["total_cost"] == 4100.0
    assert "cost_delta" in out
    assert isinstance(out["constraint_summary"], list)
    # Where the volume moves: EXPN is locked out, so it must shed volume (delta<0)
    # and at least one other carrier must gain it. Total moved is reported.
    movement = out["per_carrier_movement"]
    assert isinstance(movement, list) and movement
    by_carrier = {m["carrier"]: m for m in movement}
    assert by_carrier["EXPN"]["new_containers"] == 0
    assert by_carrier["EXPN"]["delta"] < 0          # EXPN sheds its volume
    assert any(m["delta"] > 0 for m in movement)    # someone picks it up
    # Each movement row carries current/new counts and a name.
    assert all({"current_containers", "new_containers", "delta", "name"} <= set(m)
               for m in movement)
    assert out["containers_reallocated"] > 0
    # JSON-serializable (goes back to Bedrock as a tool result).
    import json
    assert json.dumps(out["per_carrier_movement"])


def test_constraint_impact_no_constraints(blend_data):
    assert "error" in OC.constraint_impact_core(blend_data, pd.DataFrame(), None,
                                                cost_weight=0.7, performance_weight=0.3,
                                                max_growth_pct=0.3)


def test_constraint_impact_does_not_mutate_input(blend_data, rate_data):
    before = blend_data.copy()
    constraints_df = T.constraints_to_dataframe([
        T._normalize_constraint({"Carrier": "EXPN", "Maximum Container Count": 0,
                                 "Priority Score": 100})
    ])
    OC.constraint_impact_core(blend_data, constraints_df, rate_data,
                              cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert_frame_equal(blend_data, before)


# ==================== tools.py thin handlers ====================

def test_get_optimization_settings_echoes_weights():
    out = T.get_optimization_settings(0.6, 0.4, 0.25)
    assert out["cost_weight"] == 0.6
    assert out["performance_weight"] == 0.4
    assert out["cost_weight_pct"] == 60
    assert out["max_growth_pct"] == 25
    assert "objective" in out


def test_optimization_summary(blend_data):
    out = T.optimization_summary(blend_data, 0.7, 0.3, 0.3)
    assert "settings" in out
    assert out["current"]["total_cost"] == 4100.0
    # The optimized allocation should not be more expensive than current here.
    assert out["optimized"]["total_cost"] <= out["current"]["total_cost"]


# ==================== apply_constraints (pure validation half) ====================

def _valid_row():
    row = T._normalize_constraint({"Carrier": "RKNE", "Port": "NYC",
                                   "Maximum Container Count": 50, "Priority Score": 90})
    row["_problems"] = []
    return row


def _invalid_row():
    # Missing carrier for a max rule -> a validation problem.
    row = T._normalize_constraint({"Maximum Container Count": 50, "Priority Score": 90})
    row["_problems"] = T.validate_constraint(row)
    assert row["_problems"]  # sanity: this really is invalid
    return row


def test_apply_constraints_filters_invalid():
    out = T.apply_constraints([_valid_row(), _invalid_row()])
    assert out["applied_count"] == 1
    assert len(out["to_apply"]) == 1
    assert len(out["rejected"]) == 1


def test_apply_constraints_all_invalid():
    out = T.apply_constraints([_invalid_row()])
    assert out["applied_count"] == 0
    assert out["to_apply"] == []


def test_apply_constraints_empty():
    out = T.apply_constraints([])
    assert out["applied_count"] == 0
    assert "note" in out


def test_apply_constraints_is_pure_no_session_state():
    # The handler must never touch session state — clear it and confirm unchanged.
    st.session_state = _SessionState()
    T.apply_constraints([_valid_row()])
    assert "chatbot_applied_constraints" not in st.session_state


# ==================== executor routing (chat_ui) ====================

def _fresh_executor(df, rate_data=None, *, weights=(70, 30, 30), staged=None):
    """Install a clean session state and build the executor over it."""
    import components.chatbot.chat_ui as ui
    ss = _SessionState()
    ss["opt_cost_weight"], ss["opt_performance_weight"], ss["opt_max_growth_pct"] = weights
    ss["chatbot_staged_constraints"] = staged or []
    ss["chatbot_applied_constraints"] = []
    ui.st.session_state = ss
    return ui._make_tool_executor(df, rate_data, "Base Rate"), ss


def test_executor_threads_configured_weights(blend_data, monkeypatch):
    import components.chatbot.chat_ui as ui
    captured = {}

    def spy(df, scope, cw, pw, mg, top_n=5):
        captured.update(cw=cw, pw=pw, mg=mg)
        return {"ok": True}

    monkeypatch.setattr(ui.T, "recommend_carrier", spy)
    executor, _ = _fresh_executor(blend_data, weights=(60, 40, 25))
    result, is_error = executor("recommend_carrier", {"scope": {"weeks": [32]}})
    assert is_error is False
    assert captured == {"cw": 0.6, "pw": 0.4, "mg": 0.25}


def test_executor_apply_requires_confirm(blend_data):
    executor, ss = _fresh_executor(blend_data, staged=[_valid_row()])
    # Without confirm:true the executor refuses and writes nothing.
    result, is_error = executor("apply_constraints", {})
    assert is_error is True
    assert "error" in result
    assert ss["chatbot_applied_constraints"] == []


def test_executor_apply_writes_session_state(blend_data):
    executor, ss = _fresh_executor(blend_data, staged=[_valid_row()])
    result, is_error = executor("apply_constraints", {"confirm": True})
    assert is_error is False
    assert result["applied_count"] == 1
    assert len(ss["chatbot_applied_constraints"]) == 1
    assert ss.get("chatbot_apply_happened") is True


def test_executor_apply_all_invalid_writes_nothing(blend_data):
    executor, ss = _fresh_executor(blend_data, staged=[_invalid_row()])
    result, is_error = executor("apply_constraints", {"confirm": True})
    assert is_error is True
    assert ss["chatbot_applied_constraints"] == []


def test_executor_remove_requires_confirm_then_clears(blend_data):
    executor, ss = _fresh_executor(blend_data, staged=[_valid_row()])
    ss["chatbot_applied_constraints"] = [_valid_row()]

    result, is_error = executor("remove_applied_constraints", {})
    assert is_error is True
    assert len(ss["chatbot_applied_constraints"]) == 1  # untouched without confirm

    result, is_error = executor("remove_applied_constraints", {"confirm": True})
    assert is_error is False
    assert result["removed_count"] == 1
    assert ss["chatbot_applied_constraints"] == []


def test_executor_routes_optimization_tools(blend_data):
    executor, _ = _fresh_executor(blend_data)
    for tool in ("get_optimization_settings", "optimization_summary"):
        result, is_error = executor(tool, {})
        assert is_error is False
        assert isinstance(result, dict)

    result, is_error = executor("recommend_carrier", {"scope": {"weeks": [32]}})
    assert is_error is False
    assert result["recommended"]["carrier"] == "MIDD"


# ==================== run_scenario_core (cheapest / performance / optimized) ====================

@pytest.fixture
def scenario_data():
    """BAL/HGR6 has a cheaper carrier (ABCD@80 vs RKNE@100); the NYC lane is
    UNRATED (Base Rate 0) so the cheapest scenario must leave it untouched, not
    price it at $0. Performance favors RKNE on BAL.
    """
    return pd.DataFrame([
        {"Dray SCAC(FL)": "RKNE", "Lane": "USBALHGR6", "Week Number": 32,
         "Category": "FBA FCL", "Discharged Port": "BAL", "Facility": "HGR6",
         "Container Numbers": "C1, C2, C3", "Container Count": 3,
         "Base Rate": 100.0, "Total Rate": 300.0, "Performance_Score": 0.90},
        {"Dray SCAC(FL)": "ABCD", "Lane": "USBALHGR6", "Week Number": 32,
         "Category": "FBA FCL", "Discharged Port": "BAL", "Facility": "HGR6",
         "Container Numbers": "C4", "Container Count": 1,
         "Base Rate": 80.0, "Total Rate": 80.0, "Performance_Score": 0.70},
        {"Dray SCAC(FL)": "HJBT", "Lane": "USNYCEWR9", "Week Number": 33,
         "Category": "Retail CD", "Discharged Port": "NYC", "Facility": "EWR9",
         "Container Numbers": "C5, C6", "Container Count": 2,
         "Base Rate": 0.0, "Total Rate": 0.0, "Performance_Score": 0.80},
    ])


def test_scenario_cheapest_moves_to_cheaper_and_skips_unrated(scenario_data):
    out = OC.run_scenario_core(scenario_data, "cheapest",
                               cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert "error" not in out
    # BAL: 4 containers @80 (ABCD) = 320; NYC unrated stays as-is at 0.
    # Current BAL = 300+80 = 380; new BAL = 320 -> saves 60.
    assert out["current_cost"] == 380.0
    assert out["new_cost"] == 320.0
    assert out["savings"] == 60.0
    assert out["containers_reallocated"] == 3  # RKNE's 3 BAL containers move to ABCD
    # The $0-rate NYC group must be reported as unpriced, never costed at $0.
    assert any("no carrier with a published rate" in n for n in out.get("notes", []))
    deltas = {r["carrier"]: r["delta"] for r in out["per_carrier"]}
    assert deltas["ABCD"] == 3 and deltas["RKNE"] == -3


def test_scenario_performance_needs_scorecard(scenario_data):
    no_perf = scenario_data.drop(columns=["Performance_Score"])
    out = OC.run_scenario_core(no_perf, "performance",
                               cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert "error" in out and "scorecard" in out["error"].lower()


def test_scenario_performance_routes_to_best_score(scenario_data):
    out = OC.run_scenario_core(scenario_data, "performance",
                               cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert "error" not in out
    # On BAL, RKNE (0.90) beats ABCD (0.70): RKNE should hold all 4 BAL containers.
    deltas = {r["carrier"]: r for r in out["per_carrier"]}
    assert deltas["RKNE"]["new_containers"] == 4


def test_scenario_optimized_runs(scenario_data):
    out = OC.run_scenario_core(scenario_data, "optimized",
                               cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert "error" not in out
    assert out["scenario"] == "optimized"
    assert "savings" in out and "per_carrier" in out


def test_scenario_unknown_and_empty():
    assert "error" in OC.run_scenario_core(pd.DataFrame([{"x": 1}]), "bogus",
                                           cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert "error" in OC.run_scenario_core(None, "cheapest",
                                           cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)


def test_scenario_scope_filters(scenario_data):
    # Scope to week 32 only — the NYC week-33 group drops out entirely.
    out = OC.run_scenario_core(scenario_data, "cheapest", {"weeks": [32]},
                               cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert out["containers"] == 4
    assert not out.get("notes")  # no unrated group in week 32


def test_scenario_does_not_mutate_input(scenario_data):
    before = scenario_data.copy()
    OC.run_scenario_core(scenario_data, "cheapest",
                         cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    OC.run_scenario_core(scenario_data, "performance",
                         cost_weight=0.7, performance_weight=0.3, max_growth_pct=0.3)
    assert_frame_equal(scenario_data, before)


def test_run_optimization_handler_normalizes_weights(scenario_data):
    # The handler accepts 0-100 weights and normalizes to fractions internally.
    out = T.run_optimization(scenario_data, "cheapest", cost_weight=70,
                             performance_weight=30, max_growth_pct=30)
    assert "error" not in out
    assert out["savings"] == 60.0


def test_executor_routes_run_optimization(scenario_data):
    executor, _ = _fresh_executor(scenario_data)
    result, is_error = executor("run_optimization",
                                {"scenario": "cheapest", "scope": {"weeks": [32]}})
    assert is_error is False
    assert result["scenario"] == "cheapest"
    assert result["containers"] == 4


# ==================== "New chat" full reset ====================

def test_reset_chat_clears_conversation_and_tables():
    import components.chatbot.chat_ui as ui
    ss = _SessionState()
    ss["chatbot_messages"] = [{"role": "user", "content": [{"text": "hi"}]}]
    ss["chatbot_display"] = [{"role": "user", "text": "hi"}]
    ss["chatbot_staged_constraints"] = [_valid_row()]
    ss["chatbot_applied_constraints"] = [_valid_row()]
    ss["chatbot_apply_happened"] = True
    ss["chatbot_constraint_source_sig"] = "main:file.xlsx:123"
    ui.st.session_state = ss

    ui._reset_chat()

    assert ss["chatbot_messages"] == []
    assert ss["chatbot_display"] == []
    assert ss["chatbot_staged_constraints"] == []
    assert ss["chatbot_applied_constraints"] == []
    assert "chatbot_apply_happened" not in ss
    # The source signature is intentionally kept so an already-consumed upload
    # does not immediately re-seed the just-cleared table.
    assert ss["chatbot_constraint_source_sig"] == "main:file.xlsx:123"


def test_reset_chat_drops_applied_from_optimizer():
    # After reset, get_applied_constraints_df must return None so dashboard.py
    # feeds nothing to the optimizer (allocation returns to unconstrained).
    import components.chatbot.chat_ui as ui
    ss = _SessionState()
    ss["chatbot_applied_constraints"] = [_valid_row()]
    ui.st.session_state = ss
    assert ui.get_applied_constraints_df() is not None
    ui._reset_chat()
    assert ui.get_applied_constraints_df() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
