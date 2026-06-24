"""Offline tests for the prompt-intent eval harness (evals/).

These do NOT call Bedrock. They prove the harness *machinery* is correct — the
scoring logic, the case predicates, and the fixture ground-truth — by driving
``score_case`` and ``run_case`` with scripted/fake responses. The live model
behaviour is exercised by ``python -m evals.harness`` (see evals/README.md).

Without these, a bug in the scorer could make every live run falsely pass (or
fail), and we'd burn real model calls to discover it.
"""
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.modules.setdefault("streamlit", MagicMock())
import streamlit as st  # noqa: E402
st.cache_data = lambda **kwargs: (lambda f: f)
st.session_state = {}

from evals import cases as C  # noqa: E402
from evals import fixture as F  # noqa: E402
from evals.harness import score_case, run_case, _SessionState  # noqa: E402
from components.chatbot.bedrock_client import BedrockChatClient  # noqa: E402


# ==================== fixture ground-truth integrity ====================

def test_fixture_totals_are_self_consistent():
    df = F.working_data()
    assert F.total_containers() == int(df["Container Count"].sum())
    # Per-week counts must partition the total (robust to weeks being added).
    weeks = sorted(int(w) for w in df["Week Number"].dropna().unique())
    assert sum(F.containers_in_week(w) for w in weeks) == F.total_containers()


def test_fixture_cheapest_lane_helpers_match_rate_sheet():
    # ATMI is the cheapest on BAL/HGR6 (80 < RKNE 100, FRQT 95).
    scac, rate = F.cheapest_carrier_on_lane("USBALHGR6")
    assert scac == "ATMI" and rate == 80.0
    # ATMI is UNRATED on EWR9 — the cheapest must be FRQT, never ATMI.
    scac, _ = F.cheapest_carrier_on_lane("USNYCEWR9")
    assert scac == "FRQT"


def test_fixture_has_an_unrated_trap_lane():
    # The whole point of EWR9: a target carrier with no published rate there.
    rd = F.rate_data()
    assert not rd["Lookup"].eq("ATMIUSNYCEWR9").any()


# ==================== case definitions are well-formed ====================

def test_all_cases_have_unique_ids_and_some_routing():
    cs = C.all_cases()
    ids = [c.id for c in cs]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in cs:
        # every case must check routing somehow, or it asserts nothing about intent
        assert c.expect_tools or c.expect_any_tool or c.forbid_tools, c.id


def test_case_predicates_never_crash_on_empty_or_garbage_calls():
    # A predicate that raises must be caught and scored as a failed check, not
    # blow up the whole run.
    for c in C.all_cases():
        for calls in ([], [{"name": "x"}], [{"junk": True}], [{"name": "x", "input": None}]):
            r = score_case(c, answer="", tool_calls=calls, error=None)
            assert isinstance(r.passed, bool)
            # no check may be left unscored
            assert all(isinstance(ch.passed, bool) for ch in r.checks)


# ==================== scoring logic ====================

def _case(**kw):
    base = dict(id="t", prompt="p", intent="i")
    base.update(kw)
    return C.IntentCase(**base)


def test_score_expect_tool_pass_and_fail():
    case = _case(expect_tools=["analyze_data"])
    calls = [{"name": "analyze_data", "input": {}, "result": {}, "is_error": False}]
    assert score_case(case, "ok", calls, None).passed
    assert not score_case(case, "ok", [], None).passed


def test_score_forbid_tool():
    case = _case(expect_tools=[], forbid_tools=["simulate_flip"])
    bad = [{"name": "simulate_flip", "input": {}, "result": {}, "is_error": False}]
    assert not score_case(case, "ok", bad, None).passed
    assert score_case(case, "ok", [], None).passed


def test_score_answer_contains_and_not_contains():
    case = _case(expect_tools=[], answer_contains=["13"], answer_not_contains=["dispatched"])
    assert score_case(case, "You have 13 containers.", [], None).passed
    assert not score_case(case, "I dispatched 13.", [], None).passed
    assert not score_case(case, "You have many.", [], None).passed


def test_score_answer_contains_any():
    case = _case(expect_tools=[], answer_contains_any=["ATMI", "Cargomatic"])
    assert score_case(case, "Cargomatic is cheaper", [], None).passed
    assert not score_case(case, "Forrest is cheaper", [], None).passed


def test_score_error_run_fails_clean():
    case = _case(expect_tools=["analyze_data"])
    r = score_case(case, "", [], error="Bedrock error: boom")
    assert not r.passed
    assert any("boom" in ch.detail for ch in r.checks)


def test_score_arg_check_failure_is_localized():
    case = _case(expect_tools=[], arg_checks=[("always false", lambda calls: False)])
    r = score_case(case, "x", [], None)
    assert not r.passed
    assert any(ch.label == "arg: always false" and not ch.passed for ch in r.checks)


# ==================== run_case wiring (fake Bedrock, no network) ====================

class _FakeBedrock(BedrockChatClient):
    def __init__(self, scripted):
        self.model_id = "fake"; self.region = "fake"
        self._client = object(); self._scripted = list(scripted)

    @property
    def has_credentials(self):
        return True

    def converse(self, messages, system=None, tool_specs=None, max_tokens=4096):
        return self._scripted.pop(0)


def _tool(name, inp, tid="t1"):
    return {"stopReason": "tool_use", "output": {"message": {"role": "assistant",
            "content": [{"toolUse": {"toolUseId": tid, "name": name, "input": inp}}]}}}


def _text(t):
    return {"stopReason": "end_turn",
            "output": {"message": {"role": "assistant", "content": [{"text": t}]}}}


def test_run_case_records_real_tool_calls_and_scores():
    case = next(c for c in C.all_cases() if c.id == "overview_total_containers")
    client = _FakeBedrock([
        _tool("analyze_data", {"query_type": "overview"}),
        _text(f"You have {F.total_containers()} containers loaded."),
    ])
    r = run_case(client, case, F.working_data(), F.rate_data())
    assert r.passed
    assert r.tools_used == ["analyze_data"]
    # The recording executor must capture the REAL handler result, not a stub.
    assert r.tool_calls[0]["result"]["total_containers"] == F.total_containers()


def test_run_case_constraint_proposal_normalizes_snake_case_keys():
    # Bedrock forbids spaces in tool keys, so the model sends snake_case; the
    # case predicate must read them via the canonical accessor and pass.
    case = next(c for c in C.all_cases() if c.id == "constraint_cap_rkne_nyc")
    client = _FakeBedrock([
        _tool("preview_constraint_scope", {"port": "NYC"}),
        _tool("generate_constraints", {"proposals": [
            {"priority_score": 95, "carrier": "RKNE", "port": "NYC",
             "maximum_container_count": 50}]}, tid="t2"),
        _text("Drafted. Review it in the panel and click Apply or Download."),
    ])
    r = run_case(client, case, F.working_data(), F.rate_data())
    assert r.passed, [ch.label for ch in r.checks if not ch.passed]


def test_run_case_flags_carrier_smuggled_into_preview_field():
    # The pre-fix failure mode: carrier stuffed into `ssl`. The harness must
    # catch it (this is the regression guard for the tool-spec fix).
    case = next(c for c in C.all_cases() if c.id == "constraint_cap_rkne_nyc")
    client = _FakeBedrock([
        _tool("preview_constraint_scope", {"ssl": "RKNE", "port": "NYC"}),
        _tool("generate_constraints", {"proposals": [
            {"priority_score": 95, "carrier": "RKNE", "port": "NYC",
             "maximum_container_count": 50}]}, tid="t2"),
        _text("Drafted. Review it in the panel."),
    ])
    r = run_case(client, case, F.working_data(), F.rate_data())
    assert not r.passed
    assert any("not given a carrier" in ch.label and not ch.passed for ch in r.checks)


def test_run_case_resets_session_state_each_run():
    # run_case must install a fresh _SessionState before driving the loop, so a
    # constraint staged in one run never leaks into the next. We assert on the
    # session-state object the harness installs (captured locally) rather than
    # the global streamlit module, because other test modules reassign
    # sys.modules['streamlit'] and that global is not reliable cross-module.
    import evals.harness as H

    # Snapshot the state object (and its staged-constraint count) at the moment
    # run_case builds the executor — i.e. at the START of each run, after the
    # reset. If state leaked between runs, run 2 would start non-empty.
    seen_states = []
    start_counts = []
    real_executor_factory = H._make_tool_executor

    def spy_factory(df, rate_data=None, rate_type="Base Rate"):
        state = H._st.session_state
        seen_states.append(state)
        start_counts.append(len(state.get("chatbot_staged_constraints", []) or []))
        return real_executor_factory(df, rate_data, rate_type)

    case = next(c for c in C.all_cases() if c.id == "constraint_cap_rkne_nyc")
    script = lambda: _FakeBedrock([
        _tool("generate_constraints", {"proposals": [
            {"priority_score": 95, "carrier": "RKNE", "port": "NYC",
             "maximum_container_count": 50}]}),
        _text("done, review in panel"),
    ])

    import unittest.mock as M
    with M.patch.object(H, "_make_tool_executor", spy_factory):
        run_case(script(), case, F.working_data(), F.rate_data())
        run_case(script(), case, F.working_data(), F.rate_data())

    # Two runs -> two distinct, freshly-installed session-state objects, and each
    # run STARTS with zero staged constraints (no leak from the prior run).
    assert len(seen_states) == 2
    assert seen_states[0] is not seen_states[1]
    assert all(isinstance(s, _SessionState) for s in seen_states)
    assert start_counts == [0, 0]


def test_run_case_seeds_session_state_before_loop():
    # A case's seed_session_state must be installed AFTER the per-run reset and
    # BEFORE the loop, so a tool that reads it (read_constraints_summary) sees it.
    case = next(c for c in C.all_cases() if c.id == "constraint_impact_shortfall")
    client = _FakeBedrock([
        _tool("read_constraints_summary", {}),
        _text("FRQT fell short of its minimum on EWR9 — it got only 1 of 5 because "
              "the higher-priority RKNE cap claimed the volume."),
    ])
    r = run_case(client, case, F.working_data(), F.rate_data())
    assert r.tools_used == ["read_constraints_summary"]
    # The real handler read the seeded summary and digested it (not a stub/empty).
    result = r.tool_calls[0]["result"]
    assert result["applied"] is True
    assert len(result["shortfalls"]) == 1
    assert r.passed, [ch.label for ch in r.checks if not ch.passed]


def test_run_case_impact_without_seed_reports_not_applied():
    # The no-seed case: the tool must report applied=false, and the seed from the
    # OTHER case must not have leaked in.
    case = next(c for c in C.all_cases() if c.id == "constraint_impact_none_applied")
    client = _FakeBedrock([
        _tool("read_constraints_summary", {}),
        _text("You haven't applied any constraints yet, so there's no impact to report."),
    ])
    r = run_case(client, case, F.working_data(), F.rate_data())
    assert r.tool_calls[0]["result"]["applied"] is False
    assert r.passed, [ch.label for ch in r.checks if not ch.passed]


def test_run_case_survives_bedrock_error():
    class _Boom(BedrockChatClient):
        def __init__(self): self.model_id = "f"; self.region = "f"; self._client = object()
        @property
        def has_credentials(self): return True
        def converse(self, *a, **k):
            from components.chatbot.bedrock_client import BedrockClientError
            raise BedrockClientError("synthetic")

    case = next(c for c in C.all_cases() if c.id == "overview_total_containers")
    r = run_case(_Boom(), case, F.working_data(), F.rate_data())
    assert not r.passed
    assert "synthetic" in (r.error or "")
