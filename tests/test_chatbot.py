"""
Adversarial test suite for the Tender Optimization Assistant.

These tests attack the chatbot's tool layer and Bedrock conversation loop with
hostile and edge-case inputs to confirm the features degrade safely instead of
crashing, silently corrupting state, or producing invalid constraints the
optimizer would choke on. The Bedrock loop is tested with a fake client so no
network/credentials are required.
"""
import json
import math

import numpy as np
import pandas as pd
import pytest

from components.chatbot import tools as T
from components.chatbot.bedrock_client import BedrockChatClient


# ==================== fixtures ====================

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "Week Number": [9, 9, 10, 10],
        "Category": ["CD", "TL", "CD", "CD"],
        "Discharged Port": ["LAX", "LAX", "NYC", "NYC"],
        "Dray SCAC(FL)": ["ABCD", "XPDR", "ABCD", "EFGH"],
        "Facility": ["IUSF", "IUSF", "ABE8", "ABE8"],
        "Lane": ["USLAXIUSF", "USLAXIUSF", "USNYCABE8", "USNYCABE8"],
        "Container Count": [10, 5, 20, 7],
        "Base Rate": [100.0, 200.0, 150.0, 0.0],
        "Total Rate": [1000.0, 1000.0, 3000.0, 0.0],
        "Performance_Score": [0.9, 0.8, 0.95, 0.7],
    })


# ==================== analyze_data: adversarial ====================

def test_analyze_none_and_empty():
    assert "error" in T.analyze_data(None, "overview")
    assert "error" in T.analyze_data(pd.DataFrame(), "overview")


def test_analyze_unknown_query_type(sample_df):
    out = T.analyze_data(sample_df, "'; DROP TABLE constraints; --")
    assert "error" in out


def test_analyze_missing_columns_does_not_crash():
    # Only a carrier column, nothing else the analyzers expect.
    df = pd.DataFrame({"Dray SCAC(FL)": ["A", "B"]})
    # overview must survive missing Container Count / rate / perf columns
    out = T.analyze_data(df, "overview")
    assert out["total_rows"] == 2
    # cheapest needs Base Rate -> graceful error, not exception
    assert "error" in T.analyze_data(df, "cheapest")
    assert "error" in T.analyze_data(df, "performance")


def test_analyze_all_zero_rates_handled():
    df = pd.DataFrame({
        "Dray SCAC(FL)": ["A", "B"],
        "Base Rate": [0.0, 0.0],
        "Container Count": [1, 1],
    })
    out = T.analyze_data(df, "cheapest")
    assert "error" in out  # no positive rates -> clear error, no divide-by-zero


def test_analyze_nan_performance_skipped(sample_df):
    sample_df.loc[0, "Performance_Score"] = float("nan")
    out = T.analyze_data(sample_df, "by_carrier")
    # No NaN should leak into the JSON payload
    for g in out["groups"]:
        if "avg_performance" in g:
            assert not math.isnan(g["avg_performance"])


def test_analyze_huge_top_n(sample_df):
    out = T.analyze_data(sample_df, "by_carrier", top_n=10**9)
    assert len(out["groups"]) <= sample_df["Dray SCAC(FL)"].nunique()


# ==================== validate_constraint: adversarial ====================

def test_validate_requires_priority():
    problems = T.validate_constraint({"Carrier": "ABCD", "Maximum Container Count": 10})
    assert any("Priority Score" in p for p in problems)


def test_validate_max_without_carrier():
    problems = T.validate_constraint({"Priority Score": 90, "Maximum Container Count": 100})
    assert any("Carrier is required" in p for p in problems)


def test_validate_min_without_carrier():
    problems = T.validate_constraint({"Priority Score": 90, "Minimum Container Count": 30})
    assert any("Carrier is required" in p for p in problems)


def test_validate_excluded_fc_without_carrier():
    problems = T.validate_constraint({"Priority Score": 90, "Excluded FC": "IUSF"})
    assert any("Carrier is required" in p for p in problems)


def test_validate_no_action_constraint():
    # Carrier + priority but no amount/exclusion = does nothing
    problems = T.validate_constraint({"Priority Score": 90, "Carrier": "ABCD"})
    assert any("no effect" in p for p in problems)


def test_validate_percent_out_of_range():
    assert any("between 0 and 100" in p for p in
               T.validate_constraint({"Priority Score": 1, "Carrier": "A", "Percent Allocation": 150}))
    assert any("between 0 and 100" in p for p in
               T.validate_constraint({"Priority Score": 1, "Carrier": "A", "Percent Allocation": -5}))


def test_validate_negative_max():
    problems = T.validate_constraint({"Priority Score": 1, "Carrier": "A", "Maximum Container Count": -10})
    assert any("negative" in p for p in problems)


def test_validate_min_exceeds_max():
    problems = T.validate_constraint(
        {"Priority Score": 1, "Carrier": "A", "Minimum Container Count": 50, "Maximum Container Count": 10}
    )
    assert any("cannot exceed" in p for p in problems)


def test_validate_non_numeric_week():
    problems = T.validate_constraint(
        {"Priority Score": 1, "Carrier": "A", "Percent Allocation": 10, "Week Number": "next tuesday"}
    )
    assert any("Week Number must be a number" in p for p in problems)


def test_validate_unknown_carrier_warns():
    problems = T.validate_constraint(
        {"Priority Score": 1, "Carrier": "ZZZZ", "Maximum Container Count": 5},
        valid_carriers={"ABCD", "EFGH"},
    )
    assert any("not present in the loaded data" in p for p in problems)


def test_validate_zero_percent_is_actionable():
    # 0% is a deliberate lockout, must be treated as an action (not "no effect")
    problems = T.validate_constraint({"Priority Score": 1, "Carrier": "A", "Percent Allocation": 0})
    assert not any("no effect" in p for p in problems)


def test_validate_zero_max_is_actionable():
    problems = T.validate_constraint({"Priority Score": 1, "Carrier": "A", "Maximum Container Count": 0})
    assert not any("no effect" in p for p in problems)


# ==================== generate_constraints: adversarial ====================

def test_generate_non_list():
    assert "error" in T.generate_constraints({"not": "a list"})
    assert "error" in T.generate_constraints("ABCD")
    assert "error" in T.generate_constraints(None)


def test_generate_non_dict_items():
    out = T.generate_constraints(["just a string", 42, None])
    assert out["valid_count"] == 0
    assert out["invalid_count"] == 3


def test_generate_case_insensitive_keys():
    out = T.generate_constraints([
        {"priority score": 90, "carrier": "ABCD", "maximum container count": 50}
    ])
    row = out["constraints"][0]
    assert row["Priority Score"] == 90
    assert row["Carrier"] == "ABCD"
    assert row["Maximum Container Count"] == 50
    assert out["valid_count"] == 1


def test_generate_strips_junk_keys():
    out = T.generate_constraints([
        {"Priority Score": 90, "Carrier": "ABCD", "Percent Allocation": 30,
         "evil_field": "rm -rf /", "Container Numbers": "leak"}
    ])
    row = out["constraints"][0]
    assert "evil_field" not in row
    assert "Container Numbers" not in row
    # Only schema columns plus internal helper keys (_problems, _origin) survive.
    assert set(row.keys()) - {"_problems", "_origin"} == set(T.CONSTRAINT_COLUMNS)


def test_generate_string_numerics_coerced():
    out = T.generate_constraints([
        {"Priority Score": "90", "Carrier": "ABCD", "Maximum Container Count": "50"}
    ])
    assert out["valid_count"] == 1
    assert out["constraints"][0]["Maximum Container Count"] == 50.0


def test_generate_mixed_valid_invalid():
    out = T.generate_constraints([
        {"Priority Score": 90, "Carrier": "ABCD", "Percent Allocation": 30},  # valid
        {"Carrier": "EFGH", "Maximum Container Count": 10},                    # missing priority
        {"Priority Score": 50, "Maximum Container Count": 5},                  # max w/o carrier
    ])
    assert out["valid_count"] == 1
    assert out["invalid_count"] == 2


def test_generate_appends_to_existing():
    # Generating a new rule must NOT discard existing (e.g. uploaded) constraints.
    existing = T.constraints_from_dataframe(
        T.constraints_to_dataframe([
            {col: None for col in T.CONSTRAINT_COLUMNS}
            | {"Priority Score": 100, "Carrier": "UPLD", "Percent Allocation": 50}
        ]),
        origin="uploaded",
    )
    out = T.generate_constraints(
        [{"Priority Score": 80, "Carrier": "NEW1", "Maximum Container Count": 5}],
        existing=existing,
    )
    assert len(out["constraints"]) == 2
    assert out["constraints"][0]["Carrier"] == "UPLD"   # preserved, first
    assert out["constraints"][0]["_origin"] == "uploaded"
    assert out["constraints"][1]["Carrier"] == "NEW1"
    assert out["constraints"][1]["_origin"] == "assistant"  # default for drafted


# ==================== composite tools: working_set + scope_containers ====================
#
# generate_constraints / edit_constraints accept the loaded data (df=) and fold
# in what preview_constraint_scope + describe_constraints would return, so the
# model can judge a rule's reach without separate round-trips. These pin that
# behaviour, and that it stays backward-compatible when df is not supplied.

def test_generate_without_df_has_no_working_set(sample_df):
    # Backward compatible: no df -> no working_set key (existing callers unaffected).
    out = T.generate_constraints(
        [{"Priority Score": 90, "Carrier": "ABCD", "Maximum Container Count": 50}]
    )
    assert "working_set" not in out
    assert out["valid_count"] == 1


def test_generate_with_df_carries_indexed_scope_counts(sample_df):
    # sample_df: NYC has 27 containers (two NYC/ABE8 rows: 20 + 7).
    out = T.generate_constraints(
        [{"Priority Score": 90, "Carrier": "ABCD", "Port": "NYC",
          "Maximum Container Count": 50}],
        df=sample_df,
    )
    assert "working_set" in out
    item = out["working_set"][0]
    assert item["index"] == 0
    assert item["Carrier"] == "ABCD"
    assert item["scope_containers"] == 27          # the count a separate preview would give


def test_generate_with_df_scope_count_matches_preview(sample_df):
    # The composite count must equal what preview_constraint_scope returns alone.
    proposal = {"Priority Score": 90, "Carrier": "XPDR", "Lane": "USLAXIUSF",
                "Maximum Container Count": 3}
    out = T.generate_constraints([proposal], df=sample_df)
    preview = T.preview_constraint_scope(sample_df, proposal)
    assert out["working_set"][0]["scope_containers"] == preview["matched_containers"]


def test_edit_with_df_carries_post_edit_scope_counts(sample_df):
    staged = T.generate_constraints(
        [{"Priority Score": 90, "Carrier": "ABCD", "Port": "NYC",
          "Maximum Container Count": 50}],
        df=sample_df,
    )["constraints"]
    out = T.edit_constraints(
        staged, [{"action": "update", "index": 0, "Maximum Container Count": 60}],
        df=sample_df,
    )
    assert "working_set" in out
    assert out["constraints"][0]["Maximum Container Count"] == 60.0
    # Scope didn't change (still NYC), so the count is still 27 after the edit.
    assert out["working_set"][0]["scope_containers"] == 27


def test_edit_delete_working_set_reindexes(sample_df):
    staged = T.generate_constraints([
        {"Priority Score": 90, "Carrier": "ABCD", "Port": "NYC", "Maximum Container Count": 50},
        {"Priority Score": 80, "Carrier": "XPDR", "Lane": "USLAXIUSF", "Minimum Container Count": 1},
    ], df=sample_df)["constraints"]
    out = T.edit_constraints(staged, [{"action": "delete", "index": 0}], df=sample_df)
    # After deleting index 0, the surviving rule is re-indexed to 0.
    assert len(out["working_set"]) == 1
    assert out["working_set"][0]["index"] == 0
    assert out["working_set"][0]["Carrier"] == "XPDR"


def test_composite_routes_through_executor_with_df(sample_df):
    # The chat_ui executor must pass df into generate_constraints so the model
    # actually receives the folded-in scope counts.
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self.get(k)
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)
    _ss = _FakeSS()
    orig = ui.st.session_state
    ui.st.session_state = _ss
    try:
        execute = ui._make_tool_executor(sample_df, None, "Base Rate")
        result, is_error = execute("generate_constraints", {"proposals": [
            {"priority_score": 90, "carrier": "ABCD", "port": "NYC",
             "maximum_container_count": 50}]})
        assert is_error is False
        assert "working_set" in result
        assert result["working_set"][0]["scope_containers"] == 27
    finally:
        ui.st.session_state = orig


# ==================== describe_constraints / from_dataframe ====================

def test_describe_empty_asks_not_invents():
    out = T.describe_constraints([])
    assert out["count"] == 0
    assert "note" in out and "Do not invent" in out["note"]
    out2 = T.describe_constraints(None)
    assert out2["count"] == 0


def test_describe_reports_index_and_origin():
    rows = T.constraints_from_dataframe(
        T.constraints_to_dataframe([
            {col: None for col in T.CONSTRAINT_COLUMNS}
            | {"Priority Score": 90, "Carrier": "ABCD", "Maximum Container Count": 50},
        ]),
        origin="uploaded",
    )
    out = T.describe_constraints(rows)
    assert out["count"] == 1
    item = out["constraints"][0]
    assert item["index"] == 0
    assert item["origin"] == "uploaded"
    assert item["Carrier"] == "ABCD"
    # Values are JSON-safe (plain int, not numpy)
    assert isinstance(item["Maximum Container Count"], int)


def test_from_dataframe_empty_and_none():
    assert T.constraints_from_dataframe(None) == []
    assert T.constraints_from_dataframe(pd.DataFrame()) == []


def test_from_dataframe_validates_and_tags_origin():
    df = pd.DataFrame([
        {"Priority Score": 90, "Carrier": "ABCD", "Percent Allocation": 30},
        {"Priority Score": 50, "Maximum Container Count": 5},  # max w/o carrier -> invalid
    ])
    rows = T.constraints_from_dataframe(df, origin="uploaded")
    assert len(rows) == 2
    assert all(r["_origin"] == "uploaded" for r in rows)
    assert rows[0]["_problems"] == []
    assert rows[1]["_problems"]  # flagged


def test_edit_preserves_origin():
    rows = T.constraints_from_dataframe(
        pd.DataFrame([{"Priority Score": 90, "Carrier": "ABCD", "Percent Allocation": 30}]),
        origin="uploaded",
    )
    out = T.edit_constraints(rows, [{"action": "update", "index": 0, "percent_allocation": 60}])
    assert out["constraints"][0]["Percent Allocation"] == 60
    assert out["constraints"][0]["_origin"] == "uploaded"  # origin survives edit


# ==================== summarize_applied_constraints: applied-constraint impact ====================
#
# summarize_applied_constraints digests the dashboard's Applied Constraints
# Summary (the per-rule outcome list constraints_processor builds) into a
# JSON-safe view the assistant reads to explain constraint impact and seed new
# suggestions. These confirm it never crashes on empty/garbage input, never
# leaks numpy scalars into the tool payload, and surfaces shortfalls correctly.


def _summary_row(**kw):
    """A constraint-summary item shaped like constraints_processor emits."""
    base = {
        "priority": 90,
        "description": "Priority 90: rule",
        "status": "Applied",
        "containers_allocated": 50,
        "eligible_containers": 50,
        "claimed_by": None,
        "target_containers": 50,
        "method": "Maximum: 50",
        "scope": {},
        "reason": None,
    }
    base.update(kw)
    return base


def test_summary_empty_says_not_applied():
    out = T.summarize_applied_constraints([])
    assert out["applied"] is False
    assert "note" in out
    out2 = T.summarize_applied_constraints(None)
    assert out2["applied"] is False


def test_summary_garbage_input_is_safe():
    # Not a list, and a list with non-dict items -> never crashes.
    assert T.summarize_applied_constraints("nope")["applied"] is False
    out = T.summarize_applied_constraints([_summary_row(), "junk", 42, None])
    assert out["applied"] is True
    assert out["rule_count"] == 1  # only the real dict is counted


def test_summary_rollup_counts():
    out = T.summarize_applied_constraints([
        _summary_row(priority=90, status="Applied", containers_allocated=50, target_containers=50),
        _summary_row(priority=80, status="Partial (shortfall: 20)", containers_allocated=30,
                     target_containers=50),
        _summary_row(priority=70, status="Failed: No matching data", containers_allocated=0,
                     target_containers=0),
    ])
    assert out["rule_count"] == 3
    assert out["successful"] == 1
    assert out["partial"] == 1
    assert out["failed_or_skipped"] == 1
    assert out["total_allocated_containers"] == 80


def test_summary_surfaces_shortfall_with_cause():
    out = T.summarize_applied_constraints([
        _summary_row(
            priority=80, status="Partial (shortfall: 20)", containers_allocated=30,
            target_containers=50, eligible_containers=30,
            claimed_by={90: 40}, scope={"Port": "LAX", "Target Carrier": "ATMI"},
            reason="Target was 50 but 40 container(s) were already claimed by: P90.",
        ),
    ])
    assert len(out["shortfalls"]) == 1
    sf = out["shortfalls"][0]
    assert sf["priority"] == 80
    assert sf["target"] == 50
    assert sf["allocated"] == 30
    assert sf["gap"] == 20
    assert sf["scope"]["Port"] == "LAX"
    assert sf["claimed_by"] == {"P90": 40}    # priority-keyed claim map
    assert "already claimed" in sf["why"]


def test_summary_applied_in_full_is_not_a_shortfall():
    out = T.summarize_applied_constraints([
        _summary_row(status="Applied", containers_allocated=50, target_containers=50),
    ])
    assert out["shortfalls"] == []


def test_summary_coerces_numpy_to_plain_json():
    # constraints_processor builds rows from DataFrame cells -> numpy scalars.
    # These must not leak into the Bedrock tool payload (it can't serialize them).
    out = T.summarize_applied_constraints([
        _summary_row(
            priority=np.int64(90),
            containers_allocated=np.int64(30),
            target_containers=np.float64(50.0),
            eligible_containers=np.int64(30),
            claimed_by={np.int64(95): np.int64(20)},
            status="Partial (shortfall: 20)",
            scope={"Week Number": np.int64(9),
                   "Excluded Facilities": [np.str_("HGR6")]},
        ),
    ])
    rule = out["rules"][0]
    assert type(rule["priority"]) is int and rule["priority"] == 90
    assert type(rule["target"]) is int and rule["target"] == 50  # whole float -> int
    assert rule["scope"]["Week Number"] == 9
    assert rule["scope"]["Excluded Facilities"] == ["HGR6"]
    assert rule["claimed_by"] == {"P95": 20}
    # The whole payload must be JSON-serializable with no numpy types left.
    assert json.dumps(out)


def test_summary_zero_target_rule_omits_target_and_shortfall():
    # A pure exclusion / lockout rule (target 0) is applied but never a shortfall.
    out = T.summarize_applied_constraints([
        _summary_row(status="Applied (Exclusion Rule)", containers_allocated=0,
                     target_containers=0, method="Exclusion: ATMI blocked from HGR6"),
    ])
    assert out["shortfalls"] == []
    assert out["rules"][0]["status"] == "Applied (Exclusion Rule)"


# -------- failure root-cause triage (classify_constraint_failure + digest buckets) --------
#
# Reason strings below are verbatim from constraints_processor's diagnose paths
# (the dashboard's Applied Constraints Summary CSV) so the classifier is tested
# against what it will actually see. Core product rule: ROOT CAUSE decides whether
# a failure is acceptable; priority only ranks the ones that need attention.

# Real reason strings the processor emits (see components/constraints/processor.py).
_R_DEAD_CATEGORY = (
    "No rows in the source data match the scope filter(s) Category=CD. That value "
    "isn't present in the GVT file for this run — check for a typo, an alias that "
    "didn't expand, or a value that only exists under a different week/port/category."
)
_R_DEAD_LANE = (
    "No rows in the source data match the scope filter(s) Category=CD, Lane=RMN3. "
    "That value isn't present in the GVT file for this run — check for a typo, an "
    "alias that didn't expand, or a value that only exists under a different "
    "week/port/category."
)
_R_DEAD_TERMINAL = (
    "No rows in the source data match the scope filter(s) Terminal=Everport. That "
    "value isn't present in the GVT file for this run — check for a typo, an alias "
    "that didn't expand, or a value that only exists under a different week/port/category."
)
_R_SUPERSEDED = (
    "All 45 container(s) that matched this constraint's scope were already claimed by "
    "higher-priority constraint(s): Priority 9 (45). Lower the other constraint(s)' "
    "allocations or raise this constraint's priority."
)
_R_EXCLUSION = (
    "No containers matched the constraint filters after removing 176 row(s) at excluded "
    "facilities (HEA2, MIT2, RMN3, VGT2, WBW2). Check that scope filters and exclusions "
    "don't fully eliminate the data."
)
_R_NARROW = (
    "Each scope filter matches rows on its own, but no single row satisfies all of them "
    "at once (Category=Robotics → 55 row(s); Port=CHI → 14 row(s)). The filter "
    "combination is too narrow — relax one dimension so the scopes overlap."
)


def test_classify_dead_coarse_category_is_acceptable():
    # A dead Category (coarse partition) means the run lacks that segment -> fine.
    v = T.classify_constraint_failure("Failed: No matching data", _R_DEAD_CATEGORY, False)
    assert v["class"] == "out_of_scope_data"
    assert v["acceptable"] is True


def test_classify_dead_category_dominates_codead_lane():
    # When BOTH a coarse partition (Category) AND a fine dim (Lane) are dead, the
    # coarse one dominates: fixing the lane won't help when the run has no CD at
    # all, so this is out-of-scope (acceptable), not a lane typo to chase. This is
    # exactly the "CD rule on a Robotics/Devices run" case from the 6-18 data.
    v = T.classify_constraint_failure("Failed: No matching data", _R_DEAD_LANE, False)
    assert v["class"] == "out_of_scope_data"
    assert v["acceptable"] is True


def test_classify_dead_terminal_needs_attention():
    v = T.classify_constraint_failure("Failed: No matching data", _R_DEAD_TERMINAL, False)
    assert v["class"] == "dead_filter_value"
    assert v["acceptable"] is False


def test_classify_superseded_is_acceptable_regardless_of_priority():
    # claimed_by present -> superseded by higher priority -> expected, fine to fail.
    v = T.classify_constraint_failure("Failed: No matching data", _R_SUPERSEDED, True)
    assert v["class"] == "superseded"
    assert v["acceptable"] is True


def test_classify_exclusion_conflict_needs_attention():
    v = T.classify_constraint_failure("Failed: No matching data", _R_EXCLUSION, False)
    assert v["class"] == "exclusion_conflict"
    assert v["acceptable"] is False


def test_classify_narrow_combination_needs_attention():
    v = T.classify_constraint_failure("Failed: No matching data", _R_NARROW, False)
    assert v["class"] == "narrow_combination"
    assert v["acceptable"] is False


def test_classify_malformed_error_status():
    v = T.classify_constraint_failure(
        "Error: No carrier specified for maximum constraint", None, False)
    assert v["class"] == "malformed"
    assert v["acceptable"] is False


def test_classify_applied_and_partial_are_not_failures():
    assert T.classify_constraint_failure("Applied", None, False)["class"] == ""
    assert T.classify_constraint_failure("Applied (Lockout)", None, False)["acceptable"] is True
    assert T.classify_constraint_failure("Partial (shortfall: 5)", None, False)["class"] == ""


def test_classify_unknown_reason_is_conservative():
    # Anything unrecognised must be flagged, not silently treated as acceptable.
    v = T.classify_constraint_failure("Failed: No matching data", "mystery reason", False)
    assert v["class"] == "unclassified"
    assert v["acceptable"] is False


def test_dead_dimensions_parsing():
    assert T._dead_dimensions_from_reason(_R_DEAD_LANE) == ["Category", "Lane"]
    assert T._dead_dimensions_from_reason(_R_DEAD_CATEGORY) == ["Category"]
    assert T._dead_dimensions_from_reason(_R_SUPERSEDED) == []
    assert T._dead_dimensions_from_reason("") == []


def test_summary_triage_buckets_split_acceptable_from_real():
    # A representative mix mirroring the user's 6-18 run: dead-category (fine),
    # superseded (fine), dead-terminal-only (real typo), exclusion (real), plus a
    # clean Applied. The dead Terminal=Everport has a LIVE Port=LAX, so it's a
    # genuine fine-grained typo — unlike the dead-Category rows.
    out = T.summarize_applied_constraints([
        _summary_row(priority=10, status="Applied", containers_allocated=657,
                     target_containers=657),
        _summary_row(priority=10, status="Failed: No matching data",
                     containers_allocated=0, target_containers=0, reason=_R_DEAD_CATEGORY),
        _summary_row(priority=10, status="Failed: No matching data",
                     containers_allocated=0, target_containers=0, reason=_R_DEAD_TERMINAL),
        _summary_row(priority=8, status="Failed: No matching data",
                     containers_allocated=0, target_containers=0,
                     claimed_by={9: 45}, reason=_R_SUPERSEDED),
        _summary_row(priority=9, status="Failed: No matching data",
                     containers_allocated=0, target_containers=0, reason=_R_EXCLUSION),
    ])
    assert out["acceptable_failure_count"] == 2     # dead-category + superseded
    assert out["needs_attention_count"] == 2        # dead-terminal + exclusion
    # needs_attention is ranked highest-priority first.
    assert out["needs_attention"][0]["priority"] == 10
    assert out["needs_attention"][0]["failure_class"] == "dead_filter_value"
    assert out["needs_attention"][1]["failure_class"] == "exclusion_conflict"
    # acceptable classes are tallied and never appear as "needs attention".
    assert out["failure_classes"]["out_of_scope_data"] == 1
    assert out["failure_classes"]["superseded"] == 1
    # The clean Applied rule is not triaged into either bucket.
    assert all(r["status"].startswith("Failed")
               for r in out["acceptable_failures"] + out["needs_attention"])
    # Backward-compat: legacy keys still present and correct.
    assert out["successful"] == 1
    assert out["failed_or_skipped"] == 4
    assert json.dumps(out)  # still fully JSON-serializable


def test_summary_triaged_rule_carries_class_fields():
    out = T.summarize_applied_constraints([
        _summary_row(priority=10, status="Failed: No matching data",
                     containers_allocated=0, target_containers=0, reason=_R_DEAD_CATEGORY),
    ])
    rule = out["rules"][0]
    assert rule["failure_class"] == "out_of_scope_data"
    assert rule["acceptable_to_fail"] is True
    assert "triage_note" in rule


def test_summary_no_failures_has_empty_buckets():
    out = T.summarize_applied_constraints([
        _summary_row(status="Applied", containers_allocated=50, target_containers=50),
    ])
    assert out["acceptable_failure_count"] == 0
    assert out["needs_attention_count"] == 0
    assert out["acceptable_failures"] == []
    assert out["needs_attention"] == []


def test_summary_dispatches_through_executor(sample_df, monkeypatch):
    # The chat_ui executor must route "read_constraints_summary" to the tool and
    # read the summary from session state (NOT from any tool input).
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self[k]
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)

    ss = _FakeSS()
    ss["chatbot_constraint_summary"] = [
        _summary_row(status="Partial (shortfall: 20)", containers_allocated=30,
                     target_containers=50),
    ]
    monkeypatch.setattr(ui.st, "session_state", ss, raising=False)

    execute = ui._make_tool_executor(sample_df)
    result, is_error = execute("read_constraints_summary", {})
    assert is_error is False
    assert result["applied"] is True
    assert result["rule_count"] == 1
    assert len(result["shortfalls"]) == 1


def test_summary_executor_no_constraints_applied(sample_df, monkeypatch):
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self[k]
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)

    monkeypatch.setattr(ui.st, "session_state", _FakeSS(), raising=False)
    execute = ui._make_tool_executor(sample_df)
    result, is_error = execute("read_constraints_summary", {})
    assert is_error is False
    assert result["applied"] is False  # nothing in session state -> clean "not applied"


# ==================== edit_constraints: adversarial ====================

def _two_valid():
    return [
        {col: None for col in T.CONSTRAINT_COLUMNS} | {"Priority Score": 90, "Carrier": "ABCD", "Percent Allocation": 30},
        {col: None for col in T.CONSTRAINT_COLUMNS} | {"Priority Score": 80, "Carrier": "EFGH", "Maximum Container Count": 10},
    ]


def test_edit_index_out_of_range():
    out = T.edit_constraints(_two_valid(), [{"action": "update", "index": 99, "Priority Score": 1}])
    assert out["errors"]
    assert len(out["constraints"]) == 2  # untouched


def test_edit_negative_index_rejected():
    out = T.edit_constraints(_two_valid(), [{"action": "delete", "index": -1}])
    assert out["errors"]
    assert len(out["constraints"]) == 2


def test_edit_delete_reindex_correctness():
    # Deleting indices 0 and 1 should remove both correct rows, not shift wrong.
    base = _two_valid()
    base.append({col: None for col in T.CONSTRAINT_COLUMNS} | {"Priority Score": 70, "Carrier": "XPDR", "Percent Allocation": 10})
    out = T.edit_constraints(base, [{"action": "delete", "index": 0}, {"action": "delete", "index": 2}])
    remaining = out["constraints"]
    assert len(remaining) == 1
    assert remaining[0]["Carrier"] == "EFGH"  # index 1 survived


def test_edit_update_then_revalidates():
    # Updating a valid row into an invalid one must surface problems.
    out = T.edit_constraints(_two_valid(), [{"action": "update", "index": 0, "Percent Allocation": 999}])
    assert out["constraints"][0]["_problems"]


def test_edit_add_action():
    out = T.edit_constraints(_two_valid(), [
        {"action": "add", "Priority Score": 60, "Carrier": "WXYZ", "Minimum Container Count": 5}
    ])
    assert len(out["constraints"]) == 3
    assert out["constraints"][-1]["Carrier"] == "WXYZ"


def test_edit_unknown_action():
    out = T.edit_constraints(_two_valid(), [{"action": "nuke", "index": 0}])
    assert any("Unknown action" in e for e in out["errors"])


def test_edit_empty_existing():
    out = T.edit_constraints([], [{"action": "delete", "index": 0}])
    assert out["errors"]
    assert out["constraints"] == []


# ==================== preview_constraint_scope: adversarial ====================

def test_preview_no_data():
    assert "error" in T.preview_constraint_scope(None, {"Port": "LAX"})
    assert "error" in T.preview_constraint_scope(pd.DataFrame(), {"Port": "LAX"})


def test_preview_carrier_is_not_a_filter(sample_df):
    # Carrier is the assignment target; it must NOT narrow the scope.
    out = T.preview_constraint_scope(sample_df, {"Carrier": "ABCD"})
    assert out["matched_containers"] == int(sample_df["Container Count"].sum())


def test_preview_short_lane_endswith(sample_df):
    out = T.preview_constraint_scope(sample_df, {"Lane": "IUSF"})
    assert out["matched_containers"] == 15  # both LAX/IUSF rows


def test_preview_full_lane_exact(sample_df):
    out = T.preview_constraint_scope(sample_df, {"Lane": "USNYCABE8"})
    assert out["matched_containers"] == 27


def test_preview_week_as_string_coerced(sample_df):
    out = T.preview_constraint_scope(sample_df, {"Week Number": "9"})
    assert out["matched_containers"] == 15


def test_preview_nonexistent_value(sample_df):
    out = T.preview_constraint_scope(sample_df, {"Port": "MARS"})
    assert out["matched_containers"] == 0


def test_preview_missing_column_ignored(sample_df):
    df = sample_df.drop(columns=["SSL"], errors="ignore")
    out = T.preview_constraint_scope(df, {"SSL": "MAEU", "Port": "LAX"})
    # SSL filter is silently skipped (column absent); Port still applies
    assert out["matched_containers"] == 15


# ==================== Day of Week scope ====================

@pytest.fixture
def dow_df():
    # Day of Week carries the Excel WEEKDAY number (2=Mon, 3=Tue).
    return pd.DataFrame({
        "Week Number": [9, 9, 9],
        "Category": ["CD", "CD", "CD"],
        "Discharged Port": ["LAX", "LAX", "LAX"],
        "Dray SCAC(FL)": ["ABCD", "ABCD", "ABCD"],
        "Facility": ["IUSF", "IUSF", "IUSF"],
        "Lane": ["USLAXIUSF", "USLAXIUSF", "USLAXIUSF"],
        "Day of Week": [2, 2, 3],
        "Container Count": [10, 5, 7],
        "Base Rate": [100.0, 100.0, 100.0],
        "Total Rate": [1000.0, 500.0, 700.0],
    })


def test_preview_day_of_week_numeric(dow_df):
    # Day=2 (Monday) → the two Monday rows (10+5).
    out = T.preview_constraint_scope(dow_df, {"Day of Week": 2})
    assert out["matched_containers"] == 15


def test_preview_day_of_week_name(dow_df):
    # 'tue' → Excel 3 → the single Tuesday row.
    out = T.preview_constraint_scope(dow_df, {"Day of Week": "tue"})
    assert out["matched_containers"] == 7


def test_normalize_parses_day_name_to_excel_number():
    # The apply path bypasses process_constraints_file, so _normalize_constraint
    # must parse the day name → Excel number itself.
    row = T._normalize_constraint({"Priority Score": 90, "Carrier": "ABCD",
                                   "day_of_week": "monday", "maximum_container_count": 5})
    assert row["Day of Week"] == 2


def test_normalize_keeps_numeric_day():
    row = T._normalize_constraint({"Priority Score": 90, "day_of_week": 7})
    assert row["Day of Week"] == 7


def test_validate_flags_bad_day_of_week():
    problems = T.validate_constraint(
        {"Priority Score": 90, "Carrier": "ABCD",
         "Maximum Container Count": 5, "Day of Week": "someday"}
    )
    assert any("Day of Week" in p for p in problems)


# ==================== export: roundtrip ====================

def test_excel_roundtrip_strips_helper_keys():
    rows = T.generate_constraints([
        {"Priority Score": 90, "Carrier": "ABCD", "Percent Allocation": 30},
    ])["constraints"]
    data = T.constraints_to_excel_bytes(rows)
    assert isinstance(data, bytes) and len(data) > 0
    import io
    back = pd.read_excel(io.BytesIO(data))
    assert "_problems" not in back.columns
    assert list(back.columns) == T.CONSTRAINT_COLUMNS
    assert back.iloc[0]["Carrier"] == "ABCD"


def test_excel_empty_list():
    data = T.constraints_to_excel_bytes([])
    import io
    back = pd.read_excel(io.BytesIO(data))
    assert list(back.columns) == T.CONSTRAINT_COLUMNS
    assert len(back) == 0


def test_generated_constraint_processable_by_real_processor():
    """The end-to-end contract: a constraint the assistant generates must be
    accepted by the actual constraints_processor used in the dashboard."""
    from components.constraints.processor import process_constraints_file
    rows = T.generate_constraints([
        {"Priority Score": 95, "Carrier": "ABCD", "Category": "CD",
         "Port": "LAX", "Maximum Container Count": 50},
    ])["constraints"]
    excel = T.constraints_to_excel_bytes(rows)
    import io
    df = process_constraints_file(io.BytesIO(excel))
    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["Priority Score"] == 95


# ==================== Bedrock conversation loop: adversarial (fake client) ====================

class _FakeBedrock(BedrockChatClient):
    """Overrides converse() so we can drive the loop deterministically."""
    def __init__(self, scripted_responses):
        # bypass real __init__/env loading
        self.model_id = "fake"
        self.region = "fake"
        self._client = object()
        self._scripted = list(scripted_responses)

    @property
    def has_credentials(self):
        return True

    def converse(self, messages, system=None, tool_specs=None, max_tokens=4096):
        return self._scripted.pop(0)


def _text_response(text):
    return {"stopReason": "end_turn",
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}


def _tool_response(tool_name, tool_input, tool_use_id="tu_1"):
    return {"stopReason": "tool_use",
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": tool_use_id, "name": tool_name, "input": tool_input}}
            ]}}}


def test_loop_simple_text():
    client = _FakeBedrock([_text_response("Hello, here is your answer.")])
    out = client.run_conversation([{"role": "user", "content": [{"text": "hi"}]}],
                                  "sys", [], lambda n, i: ({}, False))
    assert out["text"] == "Hello, here is your answer."
    assert out["tool_calls"] == []


def test_loop_executes_tool_then_answers():
    client = _FakeBedrock([
        _tool_response("analyze_data", {"query_type": "overview"}),
        _text_response("You have 42 containers."),
    ])
    calls = []

    def executor(name, inp):
        calls.append((name, inp))
        return {"total_containers": 42}, False

    out = client.run_conversation([{"role": "user", "content": [{"text": "summarize"}]}],
                                  "sys", [], executor)
    assert out["text"] == "You have 42 containers."
    assert calls == [("analyze_data", {"query_type": "overview"})]
    assert out["tool_calls"][0]["result"] == {"total_containers": 42}


def test_loop_tool_crash_is_contained():
    client = _FakeBedrock([
        _tool_response("analyze_data", {"query_type": "overview"}),
        _text_response("Handled the error."),
    ])

    def boom(name, inp):
        raise ValueError("kaboom")

    out = client.run_conversation([{"role": "user", "content": [{"text": "x"}]}],
                                  "sys", [], boom)
    # loop survives, marks the tool call as an error, and still returns text
    assert out["text"] == "Handled the error."
    assert out["tool_calls"][0]["is_error"] is True
    assert "kaboom" in str(out["tool_calls"][0]["result"])


def test_loop_infinite_tool_use_is_capped():
    # Model that ALWAYS asks for a tool -> must hit the iteration cap, not hang.
    client = _FakeBedrock([_tool_response("analyze_data", {"query_type": "overview"})] * 100)
    out = client.run_conversation([{"role": "user", "content": [{"text": "x"}]}],
                                  "sys", [], lambda n, i: ({}, False),
                                  max_iterations=4)
    assert "maximum number of tool steps" in out["text"]
    assert len(out["tool_calls"]) == 4  # exactly the cap, no more


def test_loop_multiple_tools_in_one_turn():
    client = _FakeBedrock([
        {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "a", "name": "analyze_data", "input": {"query_type": "overview"}}},
            {"toolUse": {"toolUseId": "b", "name": "analyze_data", "input": {"query_type": "cheapest"}}},
        ]}}},
        _text_response("done"),
    ])
    out = client.run_conversation([{"role": "user", "content": [{"text": "x"}]}],
                                  "sys", [], lambda n, i: ({"ok": True}, False))
    assert len(out["tool_calls"]) == 2
    # The single tool_result user turn must carry both results (one block each).
    tool_result_turns = [
        m for m in out["messages"]
        if m.get("role") == "user"
        and any("toolResult" in b for b in m.get("content", []))
    ]
    assert len(tool_result_turns) == 1
    assert len(tool_result_turns[0]["content"]) == 2


# ==================== streaming loop: adversarial (fake stream) ====================
#
# The streaming loop (stream_conversation) must reproduce run_conversation's
# control flow — text turns end, tool-use turns execute tools then continue —
# while emitting incremental text. These drive it with scripted Converse-stream
# event lists so no network is touched.

class _FakeStreamBedrock(BedrockChatClient):
    """Overrides converse_stream() with scripted event streams."""
    def __init__(self, scripted_streams):
        self.model_id = "fake"
        self.region = "fake"
        self._client = object()
        self._streams = list(scripted_streams)

    @property
    def has_credentials(self):
        return True

    def converse_stream(self, messages, system=None, tool_specs=None, max_tokens=4096):
        return {"stream": iter(self._streams.pop(0))}


def _text_stream(text, chunks=None, stop_reason="end_turn"):
    """Build a Converse event stream that emits `text` as one text content block.

    If `chunks` is given, the text is split across that many contentBlockDelta
    events to exercise incremental assembly.
    """
    if chunks and chunks > 1:
        size = max(1, len(text) // chunks)
        pieces = [text[i:i + size] for i in range(0, len(text), size)]
    else:
        pieces = [text]
    events = [{"messageStart": {"role": "assistant"}},
              {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}]
    for p in pieces:
        events.append({"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": p}}})
    events.append({"contentBlockStop": {"contentBlockIndex": 0}})
    events.append({"messageStop": {"stopReason": stop_reason}})
    events.append({"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1}}})
    return events


def _tool_stream(tool_name, tool_input, tool_use_id="tu_1"):
    """Build a Converse event stream for a single toolUse block.

    The tool input JSON is split across two deltas to mirror Bedrock streaming
    partial JSON fragments.
    """
    payload = json.dumps(tool_input)
    half = len(payload) // 2
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"contentBlockIndex": 0,
                               "start": {"toolUse": {"toolUseId": tool_use_id,
                                                     "name": tool_name}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0,
                               "delta": {"toolUse": {"input": payload[:half]}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0,
                               "delta": {"toolUse": {"input": payload[half:]}}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]


def _drain(events):
    """Split a stream_conversation event iterator into (text, done_payload)."""
    text_fragments = []
    done = None
    tool_events = []
    for ev in events:
        if ev["type"] == "text":
            text_fragments.append(ev["text"])
        elif ev["type"] in ("tool_use", "tool_result"):
            tool_events.append(ev)
        elif ev["type"] == "done":
            done = ev
    return "".join(text_fragments), tool_events, done


def test_stream_simple_text_is_chunked():
    client = _FakeStreamBedrock([_text_stream("Hello, here is your answer.", chunks=5)])
    streamed, tool_events, done = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "hi"}]}], "sys", [], lambda n, i: ({}, False)))
    # Text arrives incrementally...
    assert streamed == "Hello, here is your answer."
    # ...and the final payload matches run_conversation's shape.
    assert done["text"] == "Hello, here is your answer."
    assert done["tool_calls"] == []
    assert tool_events == []


def test_stream_executes_tool_then_answers():
    client = _FakeStreamBedrock([
        _tool_stream("analyze_data", {"query_type": "overview"}),
        _text_stream("You have 42 containers."),
    ])
    calls = []

    def executor(name, inp):
        calls.append((name, inp))
        return {"total_containers": 42}, False

    streamed, tool_events, done = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "summarize"}]}], "sys", [], executor))
    # Tool input was reassembled from split JSON fragments.
    assert calls == [("analyze_data", {"query_type": "overview"})]
    assert done["text"] == "You have 42 containers."
    assert done["tool_calls"][0]["result"] == {"total_containers": 42}
    # The UI gets tool lifecycle events to drive its status line.
    assert [e["type"] for e in tool_events] == ["tool_use", "tool_result"]
    assert tool_events[0]["name"] == "analyze_data"
    assert tool_events[1]["is_error"] is False


def test_stream_tool_result_event_carries_input_and_result():
    """The tool_result event carries the tool's input + result so the UI can
    stream the result into the chat (not just a status flicker)."""
    client = _FakeStreamBedrock([
        _tool_stream("analyze_data", {"query_type": "overview"}),
        _text_stream("done"),
    ])
    _, tool_events, _ = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "x"}]}], "sys", [],
        lambda n, i: ({"total_containers": 42}, False)))
    result_evt = [e for e in tool_events if e["type"] == "tool_result"][0]
    assert result_evt["input"] == {"query_type": "overview"}
    assert result_evt["result"] == {"total_containers": 42}
    assert result_evt["is_error"] is False


def test_stream_tool_crash_is_contained():
    client = _FakeStreamBedrock([
        _tool_stream("analyze_data", {"query_type": "overview"}),
        _text_stream("Handled the error."),
    ])

    def boom(name, inp):
        raise ValueError("kaboom")

    _, tool_events, done = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "x"}]}], "sys", [], boom))
    assert done["text"] == "Handled the error."
    assert done["tool_calls"][0]["is_error"] is True
    assert "kaboom" in str(done["tool_calls"][0]["result"])
    assert tool_events[-1]["is_error"] is True


def test_stream_infinite_tool_use_is_capped():
    client = _FakeStreamBedrock([_tool_stream("analyze_data", {"query_type": "overview"})] * 100)
    _, _, done = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "x"}]}], "sys", [],
        lambda n, i: ({}, False), max_iterations=4))
    assert "maximum number of tool steps" in done["text"]
    assert len(done["tool_calls"]) == 4


def test_stream_assembles_message_history_for_tool_turn():
    client = _FakeStreamBedrock([
        _tool_stream("analyze_data", {"query_type": "overview"}, tool_use_id="xyz"),
        _text_stream("done"),
    ])
    _, _, done = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "x"}]}], "sys", [],
        lambda n, i: ({"ok": True}, False)))
    # The assistant toolUse turn is persisted with its reassembled input...
    assistant_tool_turns = [
        m for m in done["messages"]
        if m.get("role") == "assistant"
        and any("toolUse" in b for b in m.get("content", []))
    ]
    assert len(assistant_tool_turns) == 1
    tu = assistant_tool_turns[0]["content"][0]["toolUse"]
    assert tu["toolUseId"] == "xyz"
    assert tu["input"] == {"query_type": "overview"}
    # ...and exactly one tool_result user turn follows.
    tool_result_turns = [
        m for m in done["messages"]
        if m.get("role") == "user"
        and any("toolResult" in b for b in m.get("content", []))
    ]
    assert len(tool_result_turns) == 1


def test_stream_malformed_tool_json_falls_back_to_empty_input():
    # If the streamed tool-input JSON never parses, input defaults to {} rather
    # than crashing the loop.
    bad_stream = [
        {"contentBlockStart": {"contentBlockIndex": 0,
                               "start": {"toolUse": {"toolUseId": "t", "name": "analyze_data"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0,
                               "delta": {"toolUse": {"input": "{not valid json"}}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]
    client = _FakeStreamBedrock([bad_stream, _text_stream("ok")])
    seen = []

    def executor(name, inp):
        seen.append(inp)
        return {}, False

    _, _, done = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "x"}]}], "sys", [], executor))
    assert seen == [{}]
    assert done["text"] == "ok"


def test_stream_mixed_text_and_tool_in_one_turn():
    # A turn that emits a leading sentence AND a tool call (two content blocks).
    mixed = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Let me check. "}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockStart": {"contentBlockIndex": 1,
                               "start": {"toolUse": {"toolUseId": "m", "name": "analyze_data"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1,
                               "delta": {"toolUse": {"input": json.dumps({"query_type": "overview"})}}}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]
    client = _FakeStreamBedrock([mixed, _text_stream("All good.")])
    streamed, tool_events, done = _drain(client.stream_conversation(
        [{"role": "user", "content": [{"text": "x"}]}], "sys", [],
        lambda n, i: ({"ok": True}, False)))
    assert "Let me check." in streamed
    assert done["text"] == "All good."
    assert done["tool_calls"][0]["name"] == "analyze_data"


# ==================== flip_report: adversarial ====================
#
# flip_report is the container-level carrier-flip report (old vs new rate +
# per-container savings) added to the assistant's flip toolset. These tests
# attack it with no data, no rate sheet, unrated lanes, unknown carriers,
# garbage scope, and oversized inputs, and confirm it never crashes, never
# silently truncates, and never invents a price for an unrated lane.

@pytest.fixture
def flip_rates():
    """Rate sheet: ABCD/XPDR priced on USLAXIUSF; only XPDR priced on USNYCABE8."""
    return pd.DataFrame({
        "Lookup": ["ABCDUSLAXIUSF", "XPDRUSLAXIUSF", "XPDRUSNYCABE8"],
        "Base Rate": [100.0, 70.0, 130.0],
    })


def test_flip_report_no_data_no_crash():
    out = T.flip_report(None, {}, "XPDR")
    assert "error" in out


def test_flip_report_blank_target():
    df = pd.DataFrame({"Dray SCAC(FL)": ["ABCD"], "Lane": ["USLAXIUSF"],
                       "Container Numbers": ["C1"], "Container Count": [1]})
    out = T.flip_report(df, {}, "   ")
    assert "error" in out


def test_flip_report_no_match_is_clean(sample_df, flip_rates):
    out = T.flip_report(sample_df, {"weeks": [999]}, "XPDR", flip_rates)
    assert out["matched_rows"] == 0
    assert out["containers"] == 0
    assert "note" in out


def test_flip_report_savings_math(flip_rates):
    # 3 containers on USLAXIUSF currently ABCD ($100) -> XPDR ($70): save $30 each.
    df = pd.DataFrame({
        "Dray SCAC(FL)": ["ABCD"],
        "Lane": ["USLAXIUSF"],
        "Container Numbers": ["AAAU1000000, AAAU1000001, AAAU1000002"],
        "Container Count": [3],
    })
    out = T.flip_report(df, {}, "XPDR", flip_rates)
    assert out["containers"] == 3
    assert out["containers_priced"] == 3
    assert out["total_old_cost"] == 300.0
    assert out["total_new_cost"] == 210.0
    assert out["total_savings"] == 90.0
    assert out["cheaper"] is True
    # Each itemized row carries the per-container savings.
    assert all(r["savings"] == 30.0 for r in out["rows"])
    assert all(r["flips"] is True for r in out["rows"])


def test_flip_report_unrated_new_lane_not_priced(flip_rates):
    # USNYCABE8 has no ABCD/EFGH old rate AND no... wait: target XPDR IS rated there.
    # Use a target with no rate on the lane to exercise the unrated path.
    df = pd.DataFrame({
        "Dray SCAC(FL)": ["EFGH"],
        "Lane": ["USNYCABE8"],
        "Container Numbers": ["BBBU2000000, BBBU2000001"],
        "Container Count": [2],
    })
    out = T.flip_report(df, {}, "ZZZZ", flip_rates)  # ZZZZ priced nowhere
    assert out["unpriced_new_containers"] == 2
    assert out["containers_priced"] == 0
    assert out["total_savings"] == 0.0
    # Savings must be None per row — never fabricated as 0 for an unrated lane.
    assert all(r["savings"] is None for r in out["rows"])
    assert "notes" in out


def test_flip_report_already_on_target_not_counted_as_flip(flip_rates):
    # Containers already on XPDR — flipping to XPDR is a no-op move.
    df = pd.DataFrame({
        "Dray SCAC(FL)": ["XPDR"],
        "Lane": ["USLAXIUSF"],
        "Container Numbers": ["CCCU3000000"],
        "Container Count": [1],
    })
    out = T.flip_report(df, {}, "XPDR", flip_rates)
    assert out["containers_changing_carrier"] == 0
    assert out["containers_already_on_target"] == 1
    assert out["total_savings"] == 0.0  # same carrier, same rate


def test_flip_report_max_rows_capped_and_reported(flip_rates):
    ids = ", ".join(f"DDDU{4000000 + i}" for i in range(50))
    df = pd.DataFrame({
        "Dray SCAC(FL)": ["ABCD"], "Lane": ["USLAXIUSF"],
        "Container Numbers": [ids], "Container Count": [50],
    })
    out = T.flip_report(df, {}, "XPDR", flip_rates, max_rows=10)
    assert len(out["rows"]) == 10
    assert out["rows_omitted"] == 40       # truncation is surfaced, not silent
    assert out["containers"] == 50         # totals still count every container


def test_flip_report_garbage_scope_does_not_crash(sample_df, flip_rates):
    # Scope is a string, not a dict — Scope.from_dict must tolerate it.
    out = T.flip_report(sample_df, "not-a-dict", "XPDR", flip_rates)
    assert "containers" in out or "error" in out


def test_flip_report_no_rate_sheet_all_unpriced(sample_df):
    out = T.flip_report(sample_df, {"weeks": [9]}, "XPDR", rate_data=None)
    # Without a rate sheet nothing can be priced, but it still counts containers.
    assert out["containers"] > 0
    assert out["containers_priced"] == 0
    assert out["total_savings"] == 0.0


def test_flip_report_falls_back_to_count_without_ids(flip_rates):
    # No Container Numbers column — engine must fall back to Container Count.
    df = pd.DataFrame({
        "Dray SCAC(FL)": ["ABCD"], "Lane": ["USLAXIUSF"], "Container Count": [4],
    })
    out = T.flip_report(df, {}, "XPDR", flip_rates)
    assert out["containers"] == 4
    assert out["total_savings"] == 120.0   # 4 * (100 - 70)


def test_flip_report_lane_with_mixed_old_carriers(flip_rates):
    # One lane, two different current carriers (ABCD@100 priced, EFGH unpriced),
    # both flipping to XPDR. Per-container savings must still be correct, and the
    # lane's single old_rate must be reported as None (no representative value)
    # rather than silently showing only the first row's rate.
    df = pd.DataFrame({
        "Dray SCAC(FL)": ["ABCD", "EFGH"],
        "Lane": ["USLAXIUSF", "USLAXIUSF"],
        "Container Numbers": ["A1", "B1"],
        "Container Count": [1, 1],
    })
    out = T.flip_report(df, {}, "XPDR", flip_rates)
    assert out["containers"] == 2
    assert out["containers_priced"] == 1          # only ABCD has an old rate
    assert out["unpriced_old_containers"] == 1     # EFGH has no old rate
    assert out["total_savings"] == 30.0            # 100 - 70 over the one priced
    lane = out["per_lane"][0]
    assert lane["old_carriers"] == ["ABCD", "EFGH"]
    assert lane["old_rate"] is None                # ambiguous -> not a single number


def test_flip_report_dispatches_through_executor(sample_df, flip_rates, monkeypatch):
    # The chat_ui executor must route "flip_report" to T.flip_report.
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self[k]
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)
    monkeypatch.setattr(ui.st, "session_state", _FakeSS(), raising=False)

    execute = ui._make_tool_executor(sample_df, flip_rates, "Base Rate")
    result, is_error = execute("flip_report", {"scope": {"weeks": [9]},
                                               "target_carrier": "XPDR"})
    assert is_error is False
    assert "containers" in result
    assert "rows" in result


# ==================== build_system_prompt: session-status ground-truth ====================
#
# Regression for the "I don't have your list" bug: a constraint file WAS uploaded
# (65 rows reached the working set) yet the agent told the user nothing had
# reached it, then immediately recanted after calling describe_constraints. The
# root cause was that the model had no visibility into session state and answered
# from assumption. build_system_prompt now injects a ground-truth status line.

from components.chatbot.tool_specs import build_system_prompt, SYSTEM_PROMPT


def test_status_line_reports_loaded_constraints():
    # The exact failure scenario: a file with 65 rows is in the working set.
    prompt = build_system_prompt(
        data_rows=12000, constraint_rows=65,
        constraint_source="main:constraints list - 3.10.26.xlsx:99999",
    )
    head = prompt.splitlines()[0]
    assert head.startswith("[Session status:")
    assert "65 constraint row(s)" in head
    # The source filename is surfaced (signature prefix/size stripped).
    assert "constraints list - 3.10.26.xlsx" in head
    assert "main:" not in head
    assert "99999" not in head
    # It must steer the model to read them, not deny them.
    assert "describe_constraints" in head
    assert "ARE" in head  # "...these ARE available..."


def test_status_line_never_claims_empty_when_constraints_present():
    # No phrasing in the status line may suggest emptiness when rows exist.
    prompt = build_system_prompt(data_rows=500, constraint_rows=65, constraint_source=None)
    head = prompt.splitlines()[0].lower()
    assert "0 constraint" not in head
    assert "nothing uploaded" not in head
    assert "no constraint" not in head


def test_status_line_reports_truly_empty_working_set():
    prompt = build_system_prompt(data_rows=500, constraint_rows=0, constraint_source=None)
    head = prompt.splitlines()[0]
    assert "0 constraint rows" in head
    assert "nothing uploaded or drafted" in head


def test_status_line_handles_no_data_loaded():
    prompt = build_system_prompt(data_rows=0, constraint_rows=0, constraint_source=None)
    head = prompt.splitlines()[0]
    assert "no dashboard data loaded yet" in head


def test_status_line_reports_applied_count():
    prompt = build_system_prompt(data_rows=500, constraint_rows=65,
                                 constraint_source=None, applied_rows=12)
    head = prompt.splitlines()[0]
    assert "12 constraint(s) currently APPLIED" in head


def test_status_line_omits_applied_when_zero():
    prompt = build_system_prompt(data_rows=500, constraint_rows=65,
                                 constraint_source=None, applied_rows=0)
    assert "APPLIED" not in prompt.splitlines()[0]


def test_build_system_prompt_preserves_full_prompt_body():
    # The status line is a PREFIX; the entire base prompt must still be present.
    prompt = build_system_prompt(data_rows=1, constraint_rows=1, constraint_source=None)
    assert prompt.endswith(SYSTEM_PROMPT)
    assert "WORKING WITH UPLOADED CONSTRAINTS" in prompt


def test_build_system_prompt_tolerates_garbage_inputs():
    # None / negative / non-int must not raise — the preamble is best-effort.
    for kwargs in (
        {"data_rows": None, "constraint_rows": None, "constraint_source": None},
        {"data_rows": -5, "constraint_rows": -1, "constraint_source": 12345},
        {"data_rows": "x", "constraint_rows": "y", "constraint_source": object()},
    ):
        try:
            out = build_system_prompt(**kwargs)
        except Exception as e:  # noqa: BLE001
            assert False, f"build_system_prompt raised on {kwargs}: {e}"
        assert out.endswith(SYSTEM_PROMPT)


def test_handle_user_message_passes_status_prompt_to_stream(sample_df, monkeypatch):
    # End-to-end: the composed system prompt (with status line) must be what the
    # client actually receives — not the static SYSTEM_PROMPT.
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self[k]
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)

    ss = _FakeSS()
    ss["chatbot_display"] = []
    ss["chatbot_messages"] = []
    ss["chatbot_staged_constraints"] = [{"Priority Score": 90}] * 65
    ss["chatbot_constraint_source_sig"] = "main:constraints list - 3.10.26.xlsx:1"
    ss["chatbot_applied_constraints"] = []
    monkeypatch.setattr(ui.st, "session_state", ss, raising=False)

    # Neutralize Streamlit chrome the handler touches.
    monkeypatch.setattr(ui.st, "chat_message", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "container", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "empty", lambda *a, **k: _Empty(), raising=False)

    captured = {}

    class _FakeClient:
        has_credentials = True
        def stream_conversation(self, messages, system, tool_specs, tool_executor):
            captured["system"] = system
            yield {"type": "done", "text": "ok", "messages": messages, "tool_calls": []}

    monkeypatch.setattr(ui, "BedrockChatClient", lambda *a, **k: _FakeClient())

    ui._handle_user_message("match my list", sample_df)

    assert "system" in captured, "stream_conversation was never called"
    status_head = captured["system"].splitlines()[0]
    assert "65 constraint row(s)" in status_head
    assert "constraints list - 3.10.26.xlsx" in status_head


class _nullctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Empty:
    def markdown(self, *a, **k): pass
    def caption(self, *a, **k): pass
    def empty(self, *a, **k): pass


# ==================== clean-start: main-panel file seeds lazily, not on load ====================
#
# Regression for "the chat opens with a table already in it": a constraint file
# uploaded in the MAIN dashboard panel must NOT pre-fill the assistant's working
# set (and therefore the 'Proposed constraints' table) on passive page load. It
# should seed only once the user sends their first message. The in-chat uploader
# stays eager (that upload is an explicit "load into the assistant" action).

def _constraint_file_bytes():
    """A real, processor-readable constraint .xlsx as an in-memory file."""
    import io
    rows = T.generate_constraints([
        {"Priority Score": 90, "Carrier": "ABCD", "Maximum Container Count": 50},
    ])["constraints"]
    buf = io.BytesIO(T.constraints_to_excel_bytes(rows))
    buf.name = "main_constraints.xlsx"
    buf.size = len(buf.getvalue())
    return buf


def test_main_panel_file_does_not_seed_on_passive_render(sample_df, monkeypatch):
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self[k]
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)

    ss = _FakeSS()
    monkeypatch.setattr(ui.st, "session_state", ss, raising=False)
    # Stub every Streamlit surface show_chatbot_sidebar touches so it renders headlessly.
    monkeypatch.setattr(ui.st, "sidebar", _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "markdown", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ui.st, "caption", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ui.st, "success", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ui.st, "expander", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "file_uploader", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ui.st, "chat_message", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "chat_input", lambda *a, **k: None, raising=False)  # user typed nothing
    monkeypatch.setattr(ui.st, "button", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(ui, "_render_staged_panel", lambda: None)

    ui.show_chatbot_sidebar(sample_df, constraints_file=_constraint_file_bytes())

    # The working set must still be empty — nothing seeded on passive render.
    assert not ss.get("chatbot_staged_constraints")
    assert ss.get("chatbot_constraint_source_sig") is None


def test_main_panel_file_seeds_on_first_message(sample_df, monkeypatch):
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self[k]
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)

    ss = _FakeSS()
    ss["chatbot_display"] = []
    ss["chatbot_messages"] = []
    ss["chatbot_staged_constraints"] = []
    ss["chatbot_applied_constraints"] = []
    ss["chatbot_constraint_source_sig"] = None
    monkeypatch.setattr(ui.st, "session_state", ss, raising=False)
    monkeypatch.setattr(ui.st, "chat_message", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "container", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "empty", lambda *a, **k: _Empty(), raising=False)
    monkeypatch.setattr(ui.st, "markdown", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ui.st, "warning", lambda *a, **k: None, raising=False)

    class _FakeClient:
        has_credentials = True
        def stream_conversation(self, messages, system, tool_specs, tool_executor):
            yield {"type": "done", "text": "ok", "messages": messages, "tool_calls": []}

    monkeypatch.setattr(ui, "BedrockChatClient", lambda *a, **k: _FakeClient())

    ui._handle_user_message("summarize my constraints", sample_df,
                            constraints_file=_constraint_file_bytes())

    # Now the uploaded rule is in the working set, tagged as 'uploaded'.
    staged = ss.get("chatbot_staged_constraints")
    assert staged and len(staged) == 1
    assert staged[0]["Carrier"] == "ABCD"
    assert staged[0]["_origin"] == "uploaded"


# ==================== suggested follow-up pills ====================

def test_split_followups_extracts_and_strips_block():
    import components.chatbot.chat_ui as ui
    text = (
        "Cargomatic (ATMI) is cheapest at $410.\n\n"
        f"{ui._FOLLOWUP_MARKER}\n"
        "Price flipping all LAX volume to ATMI\n"
        "Compare ATMI vs RKNE on USLAXLGB4\n"
        "Who else is rated on this lane?"
    )
    visible, followups = ui._split_followups(text)
    assert ui._FOLLOWUP_MARKER not in visible
    assert visible == "Cargomatic (ATMI) is cheapest at $410."
    assert followups == [
        "Price flipping all LAX volume to ATMI",
        "Compare ATMI vs RKNE on USLAXLGB4",
        "Who else is rated on this lane?",
    ]


def test_split_followups_no_marker_returns_text_unchanged():
    import components.chatbot.chat_ui as ui
    visible, followups = ui._split_followups("Just an answer, no followups.")
    assert visible == "Just an answer, no followups."
    assert followups == []


def test_split_followups_tolerates_bullets_and_quotes_and_caps_at_four():
    import components.chatbot.chat_ui as ui
    text = (
        "ans\n"
        f"{ui._FOLLOWUP_MARKER}\n"
        '- "First suggestion"\n'
        "2) Second suggestion\n"
        "• Third suggestion\n"
        "Fourth suggestion\n"
        "Fifth suggestion (should be dropped)"
    )
    _, followups = ui._split_followups(text)
    assert followups == [
        "First suggestion",
        "Second suggestion",
        "Third suggestion",
        "Fourth suggestion",
    ]


def test_strip_partial_marker_hides_full_and_partial_marker():
    import components.chatbot.chat_ui as ui
    assert ui._strip_partial_marker("answer\n<<<FOLLOWUPS>>>\nopt") == "answer"
    assert ui._strip_partial_marker("answer\n<<<FOL") == "answer"
    assert ui._strip_partial_marker("answer <<<") == "answer"
    assert ui._strip_partial_marker("plain text") == "plain text"


def test_pill_selected_queues_prompt_and_clears_widget(monkeypatch):
    import components.chatbot.chat_ui as ui
    ss = {"hist_3_pills": "Compare ATMI vs RKNE on USLAXLGB4"}
    monkeypatch.setattr(ui.st, "session_state", ss, raising=False)
    ui._pill_selected("hist_3_pills")
    assert ss["chatbot_pending_prompt"] == "Compare ATMI vs RKNE on USLAXLGB4"
    # Widget reset so it does not re-fire on the next rerun.
    assert ss["hist_3_pills"] is None


# ==================== _heal_dangling_tool_use: wedged-transcript recovery ====================
#
# stream_conversation appends the assistant turn (with its toolUse blocks) to
# chatbot_messages IN PLACE before running the tools and appending the matching
# toolResult user turn. If the UI's event loop raises in between (an st.json
# render error, a logging failure), the transcript is left ending on a toolUse
# with no answering toolResult — a shape Bedrock 400s on, wedging EVERY later
# turn. _heal_dangling_tool_use repairs that at the start of the next turn.


def test_heal_no_dangling_tool_use_is_noop():
    import components.chatbot.chat_ui as ui
    # Clean transcript ending on an assistant text turn — nothing to repair.
    msgs = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]
    before = [dict(m) for m in msgs]
    assert ui._heal_dangling_tool_use(msgs) == 0
    assert msgs == before  # untouched


def test_heal_empty_and_user_ending_are_noop():
    import components.chatbot.chat_ui as ui
    assert ui._heal_dangling_tool_use([]) == 0
    # Ending on a user turn (e.g. the normal pre-send state) is valid as-is.
    msgs = [{"role": "user", "content": [{"text": "hi"}]}]
    assert ui._heal_dangling_tool_use(msgs) == 0
    assert len(msgs) == 1


def test_heal_completes_dangling_tool_use():
    import components.chatbot.chat_ui as ui
    # The wedged shape: assistant requested a tool, no toolResult followed.
    msgs = [
        {"role": "user", "content": [{"text": "summarize"}]},
        {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "tu_1", "name": "analyze_data",
                         "input": {"query_type": "overview"}}},
        ]},
    ]
    n = ui._heal_dangling_tool_use(msgs)
    assert n == 1
    # A toolResult user turn was synthesized, answering the exact toolUseId.
    assert len(msgs) == 3
    healed = msgs[-1]
    assert healed["role"] == "user"
    block = healed["content"][0]["toolResult"]
    assert block["toolUseId"] == "tu_1"
    assert block["status"] == "error"
    # The pair is now complete: every toolUseId has a matching toolResult.
    used = {b["toolUse"]["toolUseId"] for m in msgs
            for b in m.get("content", []) if "toolUse" in b}
    answered = {b["toolResult"]["toolUseId"] for m in msgs
                for b in m.get("content", []) if "toolResult" in b}
    assert used == answered


def test_heal_completes_all_parallel_tool_uses():
    import components.chatbot.chat_ui as ui
    # An assistant turn can request several tools at once; each needs a result.
    msgs = [
        {"role": "user", "content": [{"text": "x"}]},
        {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "a", "name": "analyze_data", "input": {}}},
            {"toolUse": {"toolUseId": "b", "name": "missing_rate_audit", "input": {}}},
        ]},
    ]
    assert ui._heal_dangling_tool_use(msgs) == 2
    answered = {b["toolResult"]["toolUseId"] for m in msgs
                for b in m.get("content", []) if "toolResult" in b}
    assert answered == {"a", "b"}


def test_heal_does_not_double_repair_completed_tool_turn():
    import components.chatbot.chat_ui as ui
    # Already-complete: toolUse followed by its toolResult. Ends on a user turn,
    # so there's nothing to repair — and the healer must not append a duplicate.
    msgs = [
        {"role": "user", "content": [{"text": "x"}]},
        {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "a", "name": "analyze_data", "input": {}}},
        ]},
        {"role": "user", "content": [
            {"toolResult": {"toolUseId": "a", "content": [{"json": {"ok": 1}}],
                            "status": "success"}},
        ]},
    ]
    assert ui._heal_dangling_tool_use(msgs) == 0
    assert len(msgs) == 3


def test_handle_user_message_heals_before_sending(sample_df, monkeypatch):
    # End-to-end: a transcript wedged on a dangling toolUse must be repaired
    # before the new user turn is appended, so the history sent to the model is
    # valid (toolUse answered) rather than the Bedrock-rejected dangling shape.
    import components.chatbot.chat_ui as ui

    class _FakeSS(dict):
        def __getattr__(self, k): return self[k]
        def __setattr__(self, k, v): self[k] = v
        def setdefault(self, k, d=None): return super().setdefault(k, d)

    ss = _FakeSS()
    ss["chatbot_display"] = []
    ss["chatbot_messages"] = [
        {"role": "user", "content": [{"text": "earlier question"}]},
        {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "tu_x", "name": "analyze_data", "input": {}}},
        ]},
    ]
    ss["chatbot_staged_constraints"] = []
    ss["chatbot_applied_constraints"] = []
    monkeypatch.setattr(ui.st, "session_state", ss, raising=False)
    monkeypatch.setattr(ui.st, "chat_message", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "container", lambda *a, **k: _nullctx(), raising=False)
    monkeypatch.setattr(ui.st, "empty", lambda *a, **k: _Empty(), raising=False)

    captured = {}

    class _FakeClient:
        has_credentials = True
        def stream_conversation(self, messages, system, tool_specs, tool_executor):
            captured["messages"] = [dict(m) for m in messages]
            yield {"type": "done", "text": "ok", "messages": messages, "tool_calls": []}

    monkeypatch.setattr(ui, "BedrockChatClient", lambda *a, **k: _FakeClient())

    ui._handle_user_message("new question", sample_df)

    sent = captured["messages"]
    # Order: original user, assistant toolUse, synthesized toolResult, NEW user.
    roles = [m["role"] for m in sent]
    assert roles == ["user", "assistant", "user", "user"]
    # The dangling toolUse now has its matching error toolResult.
    used = {b["toolUse"]["toolUseId"] for m in sent
            for b in m.get("content", []) if "toolUse" in b}
    answered = {b["toolResult"]["toolUseId"] for m in sent
                for b in m.get("content", []) if "toolResult" in b}
    assert used == answered == {"tu_x"}
