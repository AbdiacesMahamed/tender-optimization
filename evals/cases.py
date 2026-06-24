"""Declarative prompt-intent cases for the Tender Optimization Assistant.

Each :class:`IntentCase` pairs a natural-language prompt with checks on three
layers of "did the assistant match intent?":

  * **tool routing** — which tool(s) the model must call (and must NOT call)
  * **arguments / scope** — predicates over the recorded tool calls
  * **final answer** — substrings/regexes the answer must (or must not) contain

Checks are predicates, not exact transcripts, so they tolerate the natural
variation in a real model's phrasing while still pinning down intent. Every
numeric expectation is pulled from :mod:`evals.fixture` ground-truth helpers,
so the cases can never drift from the data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from . import fixture as F


# A recorded tool call: {"name": str, "input": dict, "result": Any, "is_error": bool}
ToolCall = dict


@dataclass
class IntentCase:
    id: str
    prompt: str
    intent: str  # human-readable statement of what "matching intent" means

    # Multi-turn follow-ups ----------------------------------------------
    # Additional user turns sent AFTER the first prompt, reusing the conversation
    # so far (the same transcript the model built). Lets a case test context
    # carryover ("apply it", "flip those instead") and confirmation flows. Tool
    # calls accumulate across all turns; the scored answer is the LAST turn's text.
    followups: List[str] = field(default_factory=list)

    # Pre-run session-state seed -----------------------------------------
    # Keys to install into st.session_state AFTER the harness's per-run reset but
    # BEFORE the loop runs. Lets a case set up state a tool reads (e.g.
    # chatbot_constraint_summary for read_constraints_summary), since the harness
    # otherwise starts every run from an empty session.
    seed_session_state: dict = field(default_factory=dict)

    # Tool routing -------------------------------------------------------
    expect_tools: List[str] = field(default_factory=list)   # all must appear
    expect_any_tool: List[str] = field(default_factory=list)  # at least one must appear
    forbid_tools: List[str] = field(default_factory=list)   # none may appear

    # Argument / scope predicates over the list of recorded ToolCalls ----
    # Each is (label, predicate(calls) -> bool).
    arg_checks: List[tuple] = field(default_factory=list)

    # Final-answer checks ------------------------------------------------
    answer_contains: List[str] = field(default_factory=list)       # all (case-insensitive)
    answer_contains_any: List[str] = field(default_factory=list)   # at least one
    answer_not_contains: List[str] = field(default_factory=list)   # none
    answer_regex: Optional[str] = None
    answer_predicate: Optional[Callable[[str], bool]] = None


# ---- small predicate helpers ----------------------------------------------

def _calls_named(calls: List[ToolCall], name: str) -> List[ToolCall]:
    return [c for c in calls if c.get("name") == name]


def _scope_of(call: ToolCall) -> dict:
    inp = call.get("input") or {}
    scope = inp.get("scope")
    return scope if isinstance(scope, dict) else {}


def _norm_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (str, int, float)):
        return [v]
    return list(v)


def _coerce(v):
    """Tiny numeric coercion shared by the arg checks (no tools import needed)."""
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _canon(key) -> str:
    """Fold a key to separator/case-insensitive form, mirroring tools._canonical_key.

    Bedrock's Converse API forbids spaces in tool-schema property keys, so the
    model sends 'priority_score' / 'maximum_container_count'. The real handler
    normalizes these to the title-case constraint columns — the harness must read
    them the same way, or it would flag a perfectly valid constraint as wrong.
    """
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def pget(proposal: dict, column: str):
    """Read a constraint field from a proposal regardless of key casing/separators."""
    want = _canon(column)
    for k, v in proposal.items():
        if _canon(k) == want:
            return v
    return None


def flip_targets(calls: List[ToolCall], tool: str = "simulate_flip"):
    """All target_carrier strings the model passed to a flip-style tool."""
    return [str((c.get("input") or {}).get("target_carrier", "")).strip()
            for c in _calls_named(calls, tool)]


def any_scope_has(calls: List[ToolCall], tool: str, key: str, wanted) -> bool:
    """True if some call to `tool` has scope[key] containing `wanted` (case-insensitive)."""
    want = str(wanted).strip().upper()
    for c in _calls_named(calls, tool):
        vals = [str(x).strip().upper() for x in _norm_list(_scope_of(c).get(key))]
        if want in vals:
            return True
    return False


# ===========================================================================
# The cases
# ===========================================================================

def all_cases() -> List[IntentCase]:
    total = F.total_containers()
    wk32 = F.containers_in_week(32)
    rkne = F.containers_for_carrier("RKNE")
    opt_winner_wk34 = F.optimizer_winner_in_week(34)   # ABCD (best performer)
    cheapest_wk34 = F.cheapest_carrier_in_week(34)     # RKNE (lowest rate)
    cheapest_scenario_wk34 = F.cheapest_scenario_winner_in_week(34)  # RKNE (lowest rate)
    holder_c8 = F.carrier_holding_container("C8")      # HJBT (NYC/ABE8)

    return [
        # ---- 1. plain data overview ----
        IntentCase(
            id="overview_total_containers",
            prompt="How many containers are loaded right now in total?",
            intent="Answer the total container count from analyze_data, not a guess.",
            expect_tools=["analyze_data"],
            forbid_tools=["simulate_flip", "generate_constraints"],
            arg_checks=[(
                "analyze_data query_type is overview",
                lambda c: any((x.get("input") or {}).get("query_type") == "overview"
                              for x in _calls_named(c, "analyze_data")),
            )],
            answer_contains=[str(total)],
        ),

        # ---- 2. cheapest carrier (ranking intent) ----
        IntentCase(
            id="cheapest_carrier_ranking",
            prompt="Which carrier has the cheapest average base rate?",
            intent="Use analyze_data 'cheapest' ranking; name a real carrier from the data.",
            expect_tools=["analyze_data"],
            arg_checks=[(
                "analyze_data query_type is cheapest",
                lambda c: any((x.get("input") or {}).get("query_type") == "cheapest"
                              for x in _calls_named(c, "analyze_data")),
            )],
            # RKNE/ABCD/HJBT are the in-data carriers; the cheapest-avg one must be named.
            answer_contains_any=["RKNE", "HJBT", "ABCD"],
        ),

        # ---- 3. flip pricing, single carrier + week scope ----
        IntentCase(
            id="flip_week32_to_atmi",
            prompt="What would it cost to flip everything in week 32 to Cargomatic?",
            intent="simulate_flip scoped to week 32, target resolves to ATMI (Cargomatic).",
            expect_tools=["simulate_flip"],
            forbid_tools=["generate_constraints"],
            arg_checks=[
                ("target resolves to Cargomatic/ATMI",
                 lambda c: any(t.upper() in ("ATMI", "CARGOMATIC")
                               for t in flip_targets(c))),
                ("scope is week 32",
                 lambda c: any_scope_has(c, "simulate_flip", "weeks", 32)),
            ],
            # ATMI is unrated on USNYCEWR9 — the answer must flag unpriced volume,
            # never imply those containers are free.
            answer_contains_any=["unpriced", "no published", "unrated", "could not be priced"],
            answer_not_contains=["dispatched", "booked", "I have flipped"],
        ),

        # ---- 4. compare two carriers on a lane ----
        IntentCase(
            id="compare_atmi_vs_frqt_bal",
            prompt="For the Baltimore HGR6 lane, is Cargomatic or Forrest cheaper?",
            intent="compare_carriers on the BAL/HGR6 scope with both candidates.",
            expect_any_tool=["compare_carriers", "lane_rate_options"],
            arg_checks=[(
                "both ATMI and FRQT considered as candidates",
                lambda c: any(
                    {"ATMI", "FRQT"}.issubset(
                        {str(x).upper() for x in _norm_list((cc.get("input") or {}).get("candidates"))}
                        | {t.upper() for t in flip_targets(c, "compare_carriers")}
                    )
                    for cc in _calls_named(c, "compare_carriers")
                ) or len(_calls_named(c, "lane_rate_options")) > 0,
            )],
            # ATMI 80 < FRQT 95 on USBALHGR6 → ATMI/Cargomatic is the cheaper answer.
            answer_contains_any=["ATMI", "Cargomatic"],
        ),

        # ---- 5. who can serve a lane ----
        IntentCase(
            id="lane_rate_options_nyc_ewr9",
            prompt="Who can serve the NYC EWR9 lane and at what rate?",
            intent="lane_rate_options for the EWR9 facility / NYC port scope.",
            expect_tools=["lane_rate_options"],
            answer_contains_any=["FRQT", "Forrest", "RKNE"],
            # ATMI has NO EWR9 rate; it must not be listed as a rated option there.
            answer_not_contains=["ATMI is the cheapest", "Cargomatic is the cheapest"],
        ),

        # ---- 6. constraint generation (intent: draft a rule) ----
        IntentCase(
            id="constraint_cap_rkne_nyc",
            prompt=("Cap RKNE at 50 containers for the NYC port, high priority. "
                    "Draft that constraint for me."),
            intent="generate_constraints with a Max=50, Carrier=RKNE, Port=NYC rule.",
            expect_tools=["generate_constraints"],
            arg_checks=[
                ("a proposal has Carrier=RKNE, Max=50, Port=NYC",
                 lambda c: any(
                     str(pget(p, "Carrier") or "").upper() == "RKNE"
                     and _coerce(pget(p, "Maximum Container Count")) == 50
                     and str(pget(p, "Port") or "").upper() == "NYC"
                     for cc in _calls_named(c, "generate_constraints")
                     for p in _norm_list((cc.get("input") or {}).get("proposals"))
                     if isinstance(p, dict)
                 )),
                # The model must not smuggle the carrier into a scope-only preview
                # field (it stuffed RKNE into `ssl` before the tool-spec fix).
                ("preview_constraint_scope not given a carrier in any field",
                 lambda c: all(
                     "RKNE" not in {str(v).strip().upper()
                                    for v in (cc.get("input") or {}).values()}
                     for cc in _calls_named(c, "preview_constraint_scope")
                 )),
            ],
            # The assistant must tell the user to review/apply — it cannot apply itself.
            answer_contains_any=["review", "Apply", "panel", "download", "Download"],
            answer_not_contains=["I applied", "I have applied", "now in effect"],
        ),

        # ---- 7. refuse to fabricate a number without a tool ----
        IntentCase(
            id="no_fabricated_cost",
            prompt="What's the total cost of all loaded containers?",
            intent="Ground the cost in analyze_data; do not invent a figure.",
            expect_tools=["analyze_data"],
            answer_predicate=lambda a: any(ch.isdigit() for ch in a),
        ),

        # ---- 8. scope to a single carrier (describe, not flip) ----
        IntentCase(
            id="describe_rkne_holdings",
            prompt="What do I currently have on RKNE?",
            intent="describe_selection (or analyze_data by_carrier) scoped to RKNE.",
            expect_any_tool=["describe_selection", "analyze_data"],
            arg_checks=[(
                "RKNE is the scope/subject",
                lambda c: any_scope_has(c, "describe_selection", "carriers", "RKNE")
                or any((x.get("input") or {}).get("query_type") == "by_carrier"
                       for x in _calls_named(c, "analyze_data")),
            )],
            answer_contains=[str(rkne)],
        ),

        # ---- 9. read the impact of applied constraints + explain a shortfall ----
        IntentCase(
            id="constraint_impact_shortfall",
            prompt=("My constraints are applied. Did FRQT get its minimum on the NYC "
                    "EWR9 lane, and if not, why?"),
            intent=("read_constraints_summary, then explain FRQT's shortfall from the "
                    "outcome (higher-priority RKNE cap + thin eligible pool), not a guess."),
            seed_session_state={"chatbot_constraint_summary": F.applied_constraints_summary()},
            expect_tools=["read_constraints_summary"],
            forbid_tools=["generate_constraints", "simulate_flip"],
            # The honest answer: FRQT fell short of its min-5 (got 1), because P95
            # capped RKNE and only 1 container remained eligible.
            answer_contains_any=["short", "partial", "did not", "didn't", "only 1", "1 of"],
            answer_predicate=lambda a: "frqt" in a.lower() or "forrest" in a.lower(),
            answer_not_contains=["I applied", "I have applied"],
        ),

        # ---- 10. no applied constraints -> don't fabricate an impact report ----
        IntentCase(
            id="constraint_impact_none_applied",
            prompt="What impact did my applied constraints have on the allocation?",
            intent=("read_constraints_summary returns applied=false; the assistant must "
                    "tell the user to apply constraints, not invent an outcome."),
            # No seed: chatbot_constraint_summary is absent -> applied=false.
            expect_tools=["read_constraints_summary"],
            forbid_tools=["generate_constraints"],
            answer_contains_any=["no constraints", "haven't applied", "not applied",
                                 "apply", "none"],
            answer_not_contains=["I applied", "shortfall of"],
        ),

        # ---- 11. "best carrier" uses the optimizer blend, NOT naive cheapest ----
        IntentCase(
            id="recommend_best_carrier_uses_optimizer",
            prompt=("For the Baltimore HGR6 lane in week 34, which carrier should we "
                    "use to get the best overall outcome?"),
            intent=("recommend_carrier (optimizer cost+performance blend) scoped to wk34 "
                    "BAL/HGR6; the answer names the blend winner, not the cheapest rate."),
            expect_tools=["recommend_carrier"],
            forbid_tools=["simulate_flip"],
            arg_checks=[(
                "recommend_carrier scoped to week 34",
                lambda c: any_scope_has(c, "recommend_carrier", "weeks", 34),
            )],
            # ABCD (best performer) wins the 70/30 blend even though RKNE is cheaper.
            answer_contains=[opt_winner_wk34],
            answer_contains_any=["performance", "blend", "optimiz", "score"],
        ),

        # ---- 12. cite the LIVE configured weights ----
        IntentCase(
            id="get_settings_cites_real_weights",
            prompt="What cost and performance weights is the optimization using right now?",
            intent="get_optimization_settings; answer cites the configured weights.",
            seed_session_state={"opt_cost_weight": 70, "opt_performance_weight": 30,
                                "opt_max_growth_pct": 30},
            expect_tools=["get_optimization_settings"],
            answer_contains_any=["70", "30"],
        ),

        # ---- 13. explain WHY cheapest isn't always recommended (business reasoning) ----
        IntentCase(
            id="explain_cheapest_not_always_best",
            prompt=("Why don't we just always send everything to the cheapest carrier "
                    "on each lane?"),
            intent=("Explain the cost+performance blend and the historical-growth / "
                    "supplier-diversity cap; may read get_optimization_settings."),
            forbid_tools=["simulate_flip", "generate_constraints"],
            answer_contains_any=["performance", "diversity", "growth", "concentrat",
                                 "historical", "balance"],
        ),

        # ---- 14. preview the cost impact of a constraint BEFORE applying ----
        IntentCase(
            id="preview_impact_before_apply",
            prompt=("Draft a rule capping HJBT at 0 on the Baltimore HGR6 lane in week 34, "
                    "then tell me what it would do to total cost before I apply it."),
            intent=("generate_constraints then preview_optimization; report the cost impact "
                    "from the tool, and do NOT apply (no confirmation given)."),
            expect_tools=["generate_constraints", "preview_optimization"],
            forbid_tools=["apply_constraints"],
            answer_predicate=lambda a: any(ch.isdigit() for ch in a),
            answer_not_contains=["I applied", "I have applied", "now in effect"],
        ),

        # ---- 15. multi-turn: draft, then APPLY on explicit confirmation ----
        IntentCase(
            id="apply_flow_with_confirmation",
            prompt=("Cap RKNE at 2 containers on the NYC EWR9 lane, priority 95. "
                    "Draft it for me."),
            followups=["Yes, apply that to the live optimization."],
            intent=("Turn 1 drafts via generate_constraints (no apply). Turn 2 the user "
                    "confirms, so the model calls apply_constraints with confirm:true and "
                    "reports it applied / is recalculating."),
            expect_tools=["generate_constraints", "apply_constraints"],
            arg_checks=[(
                "apply_constraints called with confirm:true",
                lambda c: any((cc.get("input") or {}).get("confirm") is True
                              for cc in _calls_named(c, "apply_constraints")),
            )],
            # On the FINAL (apply) turn the model SHOULD say it applied — the opposite
            # of the draft-only case #6, which forbids those phrases.
            answer_contains_any=["applied", "recalculat", "in effect"],
        ),

        # ---- 16. run a scenario and compare it to today ----
        IntentCase(
            id="run_cheapest_scenario_week34",
            prompt=("If I ran the Cheapest scenario on the Baltimore HGR6 lane in week 34, "
                    "how much would it save and who would gain volume?"),
            intent=("run_optimization scenario 'cheapest' scoped to wk34; report savings and "
                    "the carrier that gains volume (the lowest-rate carrier), not a guess."),
            expect_tools=["run_optimization"],
            forbid_tools=["simulate_flip", "apply_constraints"],
            arg_checks=[
                ("run_optimization scenario is cheapest",
                 lambda c: any((cc.get("input") or {}).get("scenario") == "cheapest"
                               for cc in _calls_named(c, "run_optimization"))),
                ("scoped to week 34",
                 lambda c: any_scope_has(c, "run_optimization", "weeks", 34)),
            ],
            # RKNE has the lowest rate (100) in wk34 BAL, so it gains the volume.
            answer_contains_any=[cheapest_scenario_wk34, "cheapest"],
            # It's a proposal, not an action — must not claim to have applied/dispatched.
            answer_not_contains=["I applied", "dispatched", "booked", "now in effect"],
        ),

        # ---- 17. historical volume share (baseline, not current view) ----
        IntentCase(
            id="historic_share_rkne",
            prompt="What's RKNE's historical volume share on the lanes it serves?",
            intent=("historic_volume_share (last-N-week baseline), not analyze_data "
                    "'by_carrier' (current-view volume). Name a share %."),
            expect_tools=["historic_volume_share"],
            forbid_tools=["simulate_flip", "generate_constraints"],
            answer_predicate=lambda a: "rkne" in a.lower() and any(ch.isdigit() for ch in a),
        ),

        # ---- 18. rate-coverage audit ----
        IntentCase(
            id="missing_rate_coverage_audit",
            prompt="Are there any containers we can't price because they have no rate?",
            intent=("missing_rate_audit; report the coverage honestly. The fixture is fully "
                    "rated, so the correct answer is 'none / all priced' — not a fabrication."),
            expect_tools=["missing_rate_audit"],
            forbid_tools=["simulate_flip"],
            answer_contains_any=["no ", "none", "all", "0", "fully", "every"],
        ),

        # ---- 19. locate specific containers (no hallucination) ----
        IntentCase(
            id="trace_named_containers",
            prompt="Which carrier currently has containers C8 and C9?",
            intent=("trace_containers for the named IDs; report the real holding carrier "
                    "(HJBT), never invent a location."),
            expect_tools=["trace_containers"],
            forbid_tools=["simulate_flip", "generate_constraints"],
            arg_checks=[(
                "trace_containers asked for C8 / C9",
                lambda c: any(
                    {"C8", "C9"} & {str(x).upper() for x in
                                    _norm_list((cc.get("input") or {}).get("container_ids"))}
                    for cc in _calls_named(c, "trace_containers")
                ),
            )],
            answer_contains_any=[holder_c8, "JB Hunt"],
        ),
    ]
