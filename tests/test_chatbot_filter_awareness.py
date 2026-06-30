"""Tests for the chatbot's dashboard-filter awareness.

The assistant is wired to the dashboard's full ``comprehensive_data``, but the
user is looking at ``final_filtered_data`` — the slice left after the Data
Filters (port / facility / week / carrier). Before this feature, asking "how
many containers?" while filtered to week 32 answered about the WHOLE file.

Two layers are covered:
  1. ``build_system_prompt`` — the per-turn status line must announce the active
     filters so the model answers about the on-screen slice (pure, no Streamlit).
  2. ``_make_tool_executor`` — data tools must run on the filtered VIEW, while
     multi-week history tools (historical share) still see the full data.
"""
from __future__ import annotations

import pandas as pd
import pytest

from components.chatbot import tools as T
from components.chatbot.tool_specs import (
    build_system_prompt, SYSTEM_PROMPT, _describe_active_filters,
)


# ==================== build_system_prompt: active-filter clause ====================

def test_no_filters_leaves_status_line_unchanged():
    # Empty/None filters must not add a filter clause — behavior identical to before.
    plain = build_system_prompt(data_rows=500, constraint_rows=0)
    with_empty = build_system_prompt(
        data_rows=500, constraint_rows=0,
        active_filters={"ports": [], "facilities": [], "weeks": [], "carriers": []},
    )
    assert plain.splitlines()[0] == with_empty.splitlines()[0]
    assert "ACTIVE DATA FILTER" not in with_empty.splitlines()[0]


def test_active_week_filter_is_announced():
    head = build_system_prompt(
        data_rows=500, constraint_rows=0, filtered_rows=42,
        active_filters={"weeks": [32]},
    ).splitlines()[0]
    assert "ACTIVE DATA FILTERS" in head
    assert "week 32" in head
    assert "42 of 500 rows" in head
    # It must steer the model to answer about the filtered slice.
    assert "filtered slice" in head.lower()


def test_multiple_filters_all_listed():
    head = build_system_prompt(
        data_rows=1000, constraint_rows=0, filtered_rows=7,
        active_filters={"ports": ["NYC"], "weeks": [33, 34], "carriers": ["RKNE"]},
    ).splitlines()[0]
    assert "port NYC" in head
    assert "weeks 33, 34" in head           # pluralized
    assert "carrier RKNE" in head


def test_filter_clause_suppressed_when_no_data():
    # A filter with zero data rows makes no sense to announce.
    head = build_system_prompt(
        data_rows=0, constraint_rows=0, active_filters={"weeks": [32]},
    ).splitlines()[0]
    assert "ACTIVE DATA FILTER" not in head
    assert "no dashboard data loaded yet" in head


def test_filter_clause_coexists_with_constraint_status():
    head = build_system_prompt(
        data_rows=500, constraint_rows=65, filtered_rows=10,
        constraint_source="main:rules.xlsx:999", active_filters={"ports": ["BAL"]},
    ).splitlines()[0]
    assert "ACTIVE DATA FILTERS" in head and "port BAL" in head
    assert "65 constraint row(s)" in head
    assert "rules.xlsx" in head


def test_build_system_prompt_still_preserves_body_with_filters():
    prompt = build_system_prompt(
        data_rows=5, constraint_rows=1, filtered_rows=2, active_filters={"weeks": [32]},
    )
    assert prompt.endswith(SYSTEM_PROMPT)
    assert "WORKING WITH UPLOADED CONSTRAINTS" in prompt


def test_filters_tolerate_garbage_without_raising():
    # The status line must never crash a turn, whatever junk reaches it.
    for f in (None, [], "weeks", 42, {"weeks": "x"}, {"ports": object()}):
        out = build_system_prompt(data_rows=10, constraint_rows=0, active_filters=f)
        assert out.endswith(SYSTEM_PROMPT)


# ==================== _describe_active_filters (pure helper) ====================

def test_describe_filters_orders_and_pluralizes():
    phrase = _describe_active_filters(
        {"weeks": [32], "ports": ["NYC", "BAL"], "facilities": [], "carriers": ["RKNE"]}
    )
    # week first, then ports (plural), carrier last; facilities omitted (empty).
    assert phrase == "week 32; ports NYC, BAL; carrier RKNE"


def test_describe_filters_empty_returns_blank():
    assert _describe_active_filters({}) == ""
    assert _describe_active_filters(None) == ""
    assert _describe_active_filters({"weeks": [], "ports": []}) == ""


# ==================== executor scoping (filtered view) ====================

class _FakeSS(dict):
    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v

    def setdefault(self, k, d=None):
        return super().setdefault(k, d)


def _sample_df():
    """A 3-week, 2-port, 2-carrier table with distinct per-slice totals."""
    rows = []
    # week 32 / NYC / RKNE: 5 containers
    rows.append({"Dray SCAC(FL)": "RKNE", "Discharged Port": "NYC", "Facility": "EWR9",
                 "Week Number": 32, "Lane": "USNYCEWR9", "Container Count": 5,
                 "Base Rate": 100.0, "Total Rate": 500.0, "Performance_Score": 0.9})
    # week 33 / NYC / HJBT: 8 containers
    rows.append({"Dray SCAC(FL)": "HJBT", "Discharged Port": "NYC", "Facility": "EWR9",
                 "Week Number": 33, "Lane": "USNYCEWR9", "Container Count": 8,
                 "Base Rate": 120.0, "Total Rate": 960.0, "Performance_Score": 0.8})
    # week 32 / BAL / HJBT: 3 containers
    rows.append({"Dray SCAC(FL)": "HJBT", "Discharged Port": "BAL", "Facility": "HGR6",
                 "Week Number": 32, "Lane": "USBALHGR6", "Container Count": 3,
                 "Base Rate": 90.0, "Total Rate": 270.0, "Performance_Score": 0.85})
    return pd.DataFrame(rows)


def _run(df, ss_init, name, tool_input):
    import components.chatbot.chat_ui as ui
    ss = _FakeSS(ss_init)
    orig = ui.st.session_state
    ui.st.session_state = ss
    try:
        execute = ui._make_tool_executor(df, None, "Base Rate")
        return execute(name, tool_input)
    finally:
        ui.st.session_state = orig


def test_overview_unfiltered_sees_all_containers():
    out, err = _run(_sample_df(), {}, "analyze_data", {"query_type": "overview"})
    assert err is False
    assert out["total_containers"] == 16          # 5 + 8 + 3
    assert sorted(out["weeks"]) == [32, 33, 34] or out["weeks"] == [32, 33]


def test_overview_respects_active_week_filter():
    # Filter to week 32 — only the two week-32 rows (5 + 3 = 8) should count.
    out, err = _run(_sample_df(), {"filter_weeks": [32]},
                    "analyze_data", {"query_type": "overview"})
    assert err is False
    assert out["total_containers"] == 8
    assert out["weeks"] == [32]


def test_overview_respects_port_and_carrier_filters():
    out, _ = _run(_sample_df(), {"filter_ports": ["NYC"]},
                  "analyze_data", {"query_type": "overview"})
    assert out["total_containers"] == 13          # 5 + 8, BAL excluded
    assert out["ports"] == ["NYC"]

    out2, _ = _run(_sample_df(), {"filter_scacs": ["RKNE"]},
                   "analyze_data", {"query_type": "overview"})
    assert out2["total_containers"] == 5
    assert out2["unique_carriers"] == 1


def test_by_carrier_only_lists_filtered_carriers():
    out, _ = _run(_sample_df(), {"filter_weeks": [32]},
                  "analyze_data", {"query_type": "by_carrier"})
    groups = {g["group"]: g["containers"] for g in out["groups"]}
    # Week 32 has RKNE(5) and HJBT(3); week-33-only HJBT volume excluded.
    assert groups == {"RKNE": 5, "HJBT": 3}


def test_describe_selection_operates_on_filtered_view():
    # describe_selection runs over the FILTERED view: with a week-32 filter, an
    # all-data ("everything currently selected") describe sees only the 8 week-32
    # containers (RKNE 5 + HJBT 3), never the 8 off-screen week-33/34 ones.
    out, _ = _run(_sample_df(), {"filter_weeks": [32]},
                  "describe_selection", {"scope": {}})
    assert out["containers"] == 8
    assert out["carriers"] == {"RKNE": 5, "HJBT": 3}


def test_historic_volume_share_uses_full_data_despite_week_filter():
    # History must NOT be narrowed by the week filter — it spans all weeks so the
    # baseline isn't starved. RKNE and HJBT should both appear even when filtered
    # to a single week.
    out, err = _run(_sample_df(), {"filter_weeks": [32]},
                    "historic_volume_share", {})
    assert err is False
    blob = str(out)
    assert "RKNE" in blob and "HJBT" in blob
