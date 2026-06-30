"""Multi-turn INTENT-tracking evaluator for the Tender Assistant.

Where ``evals.harness`` scores single-turn tool routing and ``evals.conversation``
is a free-form driver + timing probe, THIS module asks one focused question:

    Across a real multi-turn conversation, does the assistant correctly track
    what the user means — carrying scope/referents across turns ("week 32" then
    "what about 33?", "flip those to them") — and, when a request is GENUINELY
    ambiguous, ask ONE clarifying question instead of guessing?

Each :class:`Scenario` is an ordered list of :class:`Step`s. A step is a user
utterance plus a list of checks on the resulting :class:`Turn` (tools the model
called, their scope, and the answer text). Two check kinds matter most here:

  * carryover checks — turn N must act on a dimension the user only stated in an
    EARLIER turn (the model must have carried it), and must NOT silently widen or
    drop scope.
  * clarify checks — a deliberately under-determined turn must produce a
    clarifying QUESTION and NOT a scoped action tool. Over-asking on a clearly
    total/overview request is also a failure (the opposite trap).

Usage
-----
    python -m evals.intent_multiturn                 # all scenarios
    python -m evals.intent_multiturn --scenario week_carryover
    python -m evals.intent_multiturn --json out.json
    python -m evals.intent_multiturn --repeat 2      # flakiness check

Needs Bedrock creds (.env) + boto3, like the other live harnesses.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

# UTF-8 console (model answers carry smart quotes/bullets) — match siblings.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .conversation import Conversation, Turn  # noqa: E402  (sets up the st mock)
from components.chatbot.bedrock_client import BedrockChatClient  # noqa: E402


# ===========================================================================
# check helpers — predicates over a single Turn
# ===========================================================================

# A check is (label, predicate(turn) -> bool). Failing checks are reported.
Check = Tuple[str, Callable[[Turn], bool]]

# Scoped ACTION tools — calling one of these answers a scoped request. If a turn
# is supposed to ask a clarifying question instead, none of these may appear.
_SCOPED_ACTION_TOOLS = {
    "simulate_flip", "flip_report", "recommend_carrier", "run_optimization",
    "compare_carriers", "describe_selection", "generate_constraints",
    "edit_constraints", "preview_optimization", "apply_constraints",
}


def _norm(v) -> list:
    if v is None:
        return []
    if isinstance(v, (str, int, float)):
        return [v]
    return list(v)


def _scope_vals(turn: Turn, tool: str, key: str) -> set:
    """All values seen under scope[key] across every call to `tool` this turn."""
    out = set()
    for e in turn.tool_events:
        if e.name != tool:
            continue
        scope = (e.input or {}).get("scope")
        if isinstance(scope, dict):
            for x in _norm(scope.get(key)):
                out.add(str(x).strip().upper())
    return out


def used(tool: str) -> Check:
    return (f"called '{tool}'", lambda t: tool in t.tools_used)


def used_any(tools: List[str]) -> Check:
    return (f"called any of {tools}",
            lambda t: any(x in t.tools_used for x in tools))


def not_used(tool: str) -> Check:
    return (f"did NOT call '{tool}'", lambda t: tool not in t.tools_used)


def scope_has(tool: str, key: str, wanted) -> Check:
    want = str(wanted).strip().upper()
    return (f"{tool} scope[{key}] has {wanted}",
            lambda t: want in _scope_vals(t, tool, key))


def scope_lacks(tool: str, key: str, unwanted) -> Check:
    """The tool must NOT be scoped to `unwanted` (e.g. a week from an old turn)."""
    bad = str(unwanted).strip().upper()
    return (f"{tool} scope[{key}] does NOT carry {unwanted}",
            lambda t: bad not in _scope_vals(t, tool, key))


def answer_has_any(subs: List[str]) -> Check:
    low = [s.lower() for s in subs]
    return (f"answer mentions any of {subs}",
            lambda t: any(s in (t.answer or "").lower() for s in low))


def answer_lacks(subs: List[str]) -> Check:
    low = [s.lower() for s in subs]
    return (f"answer avoids all of {subs}",
            lambda t: not any(s in (t.answer or "").lower() for s in low))


def asks_clarifying() -> Check:
    """Turn must pose a question AND not fire a scoped action tool.

    A clarifying turn ends with (or contains) a '?', and the model held off on
    any scoped action — a read-only peek (analyze_data overview) is tolerated,
    but committing to a scoped flip/recommend/draft is a guess, which is the
    failure we are probing for.
    """
    def _pred(t: Turn) -> bool:
        has_q = "?" in (t.answer or "")
        no_action = not any(x in t.tools_used for x in _SCOPED_ACTION_TOOLS)
        return has_q and no_action
    return ("asks a clarifying question, no scoped action", _pred)


def no_error() -> Check:
    return ("turn completed without error", lambda t: t.error is None)


# ===========================================================================
# scenario model
# ===========================================================================

@dataclass
class Step:
    user: str
    checks: List[Check] = field(default_factory=list)
    note: str = ""  # what this step is probing


@dataclass
class Scenario:
    id: str
    intent: str
    steps: List[Step]
    seed_upload: bool = False  # start from the hypothetical constraint upload
    # Pre-set the dashboard's Data Filters before the conversation starts, so the
    # assistant's data view is scoped exactly as if the user had filtered the
    # dashboard. Keys mirror the filter UI: filter_ports / filter_fcs /
    # filter_weeks / filter_scacs. Empty/absent = no filter (the default).
    seed_filters: dict = field(default_factory=dict)


@dataclass
class StepResult:
    user: str
    answer: str
    tools: List[str]
    failed: List[str]
    error: Optional[str]

    @property
    def passed(self) -> bool:
        return self.error is None and not self.failed


@dataclass
class ScenarioResult:
    id: str
    intent: str
    steps: List[StepResult]

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.steps)


# ===========================================================================
# the scenarios — deliberately hard multi-turn intent tracking
# ===========================================================================
#
# Fixture recap (evals/fixture.py): carriers RKNE/HJBT/ABCD in the data, ATMI &
# FRQT rated-only; weeks 32, 33, 34; lanes USBALHGR6, USNYCEWR9, USNYCABE8.
# ATMI = Cargomatic, FRQT = Forrest, HJBT = JB Hunt (see SCAC mapping memory).

def _answer_count_is(turn: Turn, n: int) -> bool:
    """True if the answer states the integer ``n`` as a standalone number.

    Tolerates thousands separators but not substring matches (so 9 doesn't match
    "90" or "229"). Used to assert the assistant reported the FILTERED total.
    """
    import re
    text = (turn.answer or "").replace(",", "")
    return bool(re.search(rf"(?<!\d){n}(?!\d)", text))


def all_scenarios() -> List[Scenario]:
    return [
        # -------------------------------------------------------------------
        # 0. FILTER AWARENESS. The dashboard is filtered to week 32. "How many
        #    containers / which carriers" must answer about that SLICE (9 conts,
        #    RKNE+HJBT) — NOT the whole 22-container file, and NOT ABCD (which has
        #    no week-32 volume). Then a flip "all of it" must inherit week 32.
        # -------------------------------------------------------------------
        Scenario(
            id="filter_awareness_week32",
            intent=("With the dashboard filtered to week 32, the assistant's data view "
                    "is that slice: totals/carriers must reflect 9 containers across "
                    "RKNE+HJBT, never the full 22-row file or the absent ABCD."),
            seed_filters={"filter_weeks": [32]},
            steps=[
                Step("How many containers are loaded right now, and which carriers?",
                     [no_error(), used_any(["analyze_data", "describe_selection"]),
                      ("answer reports the filtered total (9), not the full 22",
                       lambda t: _answer_count_is(t, 9) and not _answer_count_is(t, 22)),
                      answer_has_any(["RKNE", "HJBT"]),
                      answer_lacks(["ABCD"]),
                      answer_has_any(["week 32", "wk 32", "wk32", "filter"])],
                     note="must answer about the week-32 slice and acknowledge the filter"),
                Step("Which of those carriers is cheaper on average?",
                     [no_error(),
                      answer_has_any(["RKNE", "HJBT"]),
                      answer_lacks(["ABCD"])],
                     note="comparison stays within the filtered carriers, not ABCD"),
            ],
        ),
        # -------------------------------------------------------------------
        # 1. The canonical "wk27 then follow-ups" pattern: state the week once,
        #    then refer back to it elliptically. Scope must carry, not reset.
        # -------------------------------------------------------------------
        Scenario(
            id="week_carryover",
            intent=("User scopes to week 32, then asks elliptical follow-ups that "
                    "must inherit week 32 — and a later 'what about 33?' must "
                    "switch to 33 without dragging 32 along."),
            steps=[
                Step("Show me the week 32 data — how many containers and which carriers?",
                     [no_error(), used_any(["analyze_data", "describe_selection"]),
                      answer_has_any(["RKNE", "HJBT", "ABCD"])],
                     note="establishes week 32 as the active scope"),
                Step("What would it cost to flip all of that to Cargomatic?",
                     [no_error(), used("simulate_flip"),
                      scope_has("simulate_flip", "weeks", 32),
                      answer_has_any(["unpriced", "unrated", "no published",
                                      "could not be priced"])],
                     note="'all of that' must resolve to week 32 from turn 1"),
                Step("Okay, now what about week 33 instead?",
                     [no_error(),
                      scope_has("simulate_flip", "weeks", 33),
                      scope_lacks("simulate_flip", "weeks", 32)],
                     note="switch to 33; must NOT still carry 32"),
            ],
        ),

        # -------------------------------------------------------------------
        # 2. Pronoun + carrier referent carryover. "them"/"the cheaper one"
        #    must resolve from the prior comparison, not be re-asked.
        # -------------------------------------------------------------------
        Scenario(
            id="carrier_referent_carryover",
            intent=("After comparing two carriers on a lane, 'the cheaper one' and "
                    "'flip it to them' must resolve to the winner (ATMI) and the "
                    "lane already in context — no re-asking which carrier/lane."),
            steps=[
                Step("On the Baltimore HGR6 lane, who's cheaper — Cargomatic or Forrest?",
                     [no_error(), used_any(["compare_carriers", "lane_rate_options"]),
                      answer_has_any(["ATMI", "Cargomatic"])],
                     note="ATMI 80 < FRQT 95 on USBALHGR6"),
                Step("Great — price flipping that lane to the cheaper one.",
                     [no_error(), used("simulate_flip"),
                      ("flip target is ATMI/Cargomatic",
                       lambda t: any("ATMI" in str((e.input or {}).get("target_carrier", "")).upper()
                                     for e in t.tool_events if e.name == "simulate_flip"))],
                     note="'the cheaper one' = ATMI; 'that lane' = BAL/HGR6"),
            ],
        ),

        # -------------------------------------------------------------------
        # 3. GENUINELY ambiguous opener -> must ask, not guess. Then once the
        #    user answers, must ACT (not keep asking — the over-ask trap).
        # -------------------------------------------------------------------
        Scenario(
            id="ambiguous_best_then_resolve",
            intent=("'What's the best carrier?' with no lane/week is genuinely "
                    "ambiguous -> ask ONE question. After the user supplies the "
                    "scope, ACT with recommend_carrier — do not re-ask."),
            steps=[
                Step("Which carrier should I be using?",
                     [no_error(), asks_clarifying(),
                      not_used("recommend_carrier"), not_used("simulate_flip")],
                     note="no scope at all -> must clarify"),
                Step("For the Baltimore HGR6 lane in week 34.",
                     [no_error(), used("recommend_carrier"),
                      scope_has("recommend_carrier", "weeks", 34),
                      answer_has_any(["ABCD", "performance", "blend", "score"])],
                     note="now scoped -> act, name the blend winner ABCD"),
            ],
        ),

        # -------------------------------------------------------------------
        # 4. Over-ask trap: a clearly-total request must NOT trigger a
        #    clarifying question. Empty scope is the correct reading.
        # -------------------------------------------------------------------
        Scenario(
            id="total_request_no_overask",
            intent=("'total containers loaded' clearly means everything — the "
                    "assistant must answer with analyze_data overview, NOT ask "
                    "which subset."),
            steps=[
                Step("How many containers are loaded in total across everything?",
                     [no_error(), used("analyze_data"),
                      ("answer is not just a clarifying question",
                       lambda t: not ("?" in (t.answer or "")
                                      and not t.tools_used))],
                     note="must not over-ask on a clearly-total request"),
            ],
        ),

        # -------------------------------------------------------------------
        # 5. Mid-conversation correction: user gives a number, then revises it.
        #    The revised value must win; the stale one must not persist.
        # -------------------------------------------------------------------
        Scenario(
            id="correction_wins",
            intent=("User drafts a cap, then corrects the number in the next turn. "
                    "The final staged rule must reflect the CORRECTED value, and "
                    "nothing is applied without explicit confirmation."),
            steps=[
                Step("Draft a rule capping RKNE at 50 containers on the NYC port, priority 90.",
                     [no_error(), used("generate_constraints"),
                      answer_lacks(["i applied", "now in effect"])],
                     note="initial draft, max 50"),
                Step("Actually make that 30, not 50.",
                     [no_error(),
                      used_any(["generate_constraints", "edit_constraints"]),
                      ("a staged RKNE rule now caps at 30",
                       lambda t: _staged_cap_is(t, "RKNE", 30)),
                      answer_lacks(["i applied", "now in effect"])],
                     note="correction to 30 must win (generate or edit)"),
            ],
        ),

        # -------------------------------------------------------------------
        # 6. Referent to a tool RESULT, not just a noun: "the most expensive
        #    one" points at whatever the prior analysis surfaced.
        # -------------------------------------------------------------------
        Scenario(
            id="result_referent_carryover",
            intent=("After ranking carriers by cost, 'show me what's on the most "
                    "expensive one' must scope to the carrier the ranking named — "
                    "resolved from the result, not re-derived from a guess."),
            steps=[
                Step("Rank the carriers from most to least expensive by average base rate.",
                     [no_error(), used_any(["analyze_data", "run_analysis"]),
                      answer_has_any(["RKNE", "HJBT", "ABCD"])],
                     note="surfaces the priciest carrier (analyze_data or run_analysis)"),
                Step("Show me everything currently on that most expensive carrier.",
                     [no_error(), used_any(["describe_selection", "analyze_data"])],
                     note="'that most expensive carrier' refers to the ranking"),
            ],
        ),

        # -------------------------------------------------------------------
        # 7. Ambiguous "flip these" with NOTHING selected -> must ask what
        #    'these' refers to rather than flipping all data.
        # -------------------------------------------------------------------
        Scenario(
            id="dangling_these_clarify",
            intent=("An opening 'flip these to FRQT' with no prior selection has no "
                    "referent -> ask what 'these' means; do not silently flip the "
                    "entire dataset."),
            steps=[
                Step("Go ahead and flip these over to Forrest.",
                     [no_error(), asks_clarifying(), not_used("simulate_flip")],
                     note="no referent for 'these' -> must clarify"),
            ],
        ),

        # -------------------------------------------------------------------
        # 8. Scope NARROWING across turns: start broad (a port), then narrow
        #    to a lane, then to a week — each turn must combine, not forget.
        # -------------------------------------------------------------------
        Scenario(
            id="progressive_narrowing",
            intent=("User progressively narrows NYC -> the EWR9 lane -> week 32. The "
                    "final flip must be scoped to the accumulated NYC/EWR9/wk32, "
                    "not just the last dimension mentioned."),
            steps=[
                Step("Let's look at the NYC port. What carriers and volume are there?",
                     [no_error(), used_any(["analyze_data", "describe_selection"])],
                     note="establish NYC"),
                Step("Narrow that to just the EWR9 lane.",
                     [no_error()],
                     note="add EWR9 to the running scope"),
                Step("Now price flipping just that — week 32 only — to Forrest.",
                     [no_error(), used("simulate_flip"),
                      scope_has("simulate_flip", "weeks", 32),
                      ("flip target is FRQT/Forrest",
                       lambda t: any("FRQT" in str((e.input or {}).get("target_carrier", "")).upper()
                                     for e in t.tool_events if e.name == "simulate_flip"))],
                     note="final scope must carry the EWR9 lane + week 32"),
            ],
        ),

        # -------------------------------------------------------------------
        # 9. Topic SWITCH must drop the old referent. After discussing one lane,
        #    the user pivots to a totally different question; "it" in the pivot
        #    refers to the NEW subject, and the old lane must not leak in.
        # -------------------------------------------------------------------
        Scenario(
            id="topic_switch_drops_referent",
            intent=("After pricing a flip on USBALHGR6, the user changes the subject "
                    "to RKNE's holdings. A follow-up about 'it' must track RKNE, not "
                    "drag the BAL/HGR6 flip context along."),
            steps=[
                Step("Price flipping the Baltimore HGR6 lane to Cargomatic.",
                     [no_error(), used("simulate_flip"),
                      scope_has("simulate_flip", "facilities", "HGR6")],
                     note="set BAL/HGR6 as context"),
                Step("Forget that for now. How many containers does RKNE hold overall?",
                     [no_error(), used_any(["analyze_data", "describe_selection"]),
                      answer_has_any(["RKNE", "RoadOne"])],
                     note="hard topic switch to RKNE totals"),
                Step("And what's its average base rate?",
                     [no_error(),
                      answer_has_any(["RKNE", "RoadOne"]),
                      ("did not re-scope a flip to the old HGR6 lane",
                       lambda t: "HGR6" not in _scope_vals(t, "simulate_flip", "facilities"))],
                     note="'its' = RKNE, not the abandoned HGR6 flip"),
            ],
        ),

        # -------------------------------------------------------------------
        # 10. Contradiction within one turn -> must surface it, not silently
        #     pick one. A min above the eligible pool is self-defeating; the
        #     assistant should still stage but flag the conflict.
        # -------------------------------------------------------------------
        Scenario(
            id="impossible_rule_flagged",
            intent=("A rule demanding a 500-container minimum for ABCD on a lane that "
                    "holds only a handful is impossible. The assistant must stage it "
                    "AND flag that the minimum exceeds the eligible pool — not claim "
                    "it will be satisfied."),
            steps=[
                Step("Add a rule: ABCD must get at least 500 containers on the "
                     "Baltimore HGR6 lane, priority 80.",
                     [no_error(), used("generate_constraints"),
                      answer_has_any(["exceed", "more than", "only", "pool",
                                      "won't", "cannot", "can't", "not enough",
                                      "impossible", "available"]),
                      answer_lacks(["i applied", "now in effect"])],
                     note="must stage AND flag the min>pool conflict"),
            ],
        ),

        # -------------------------------------------------------------------
        # 11. Multi-turn apply guard: draft, then a VAGUE "ok sounds good" that
        #     is NOT an explicit apply instruction. The assistant must not apply
        #     on a soft acknowledgement — only on an explicit yes/apply.
        # -------------------------------------------------------------------
        Scenario(
            id="soft_ack_does_not_apply",
            intent=("After a draft, a soft 'ok looks fine' is NOT an explicit apply "
                    "instruction. apply_constraints must NOT fire; an explicit 'apply "
                    "it' on the next turn does."),
            steps=[
                Step("Draft a cap of RKNE at 2 on the NYC EWR9 lane, priority 95.",
                     [no_error(), used("generate_constraints"),
                      not_used("apply_constraints")],
                     note="draft only"),
                Step("Ok, that looks fine.",
                     [no_error(), not_used("apply_constraints"),
                      answer_lacks(["i applied", "i've applied", "now in effect",
                                    "recalculat"])],
                     note="soft ack must NOT trigger apply"),
                Step("Apply it to the live optimization.",
                     [no_error(), used("apply_constraints"),
                      ("apply_constraints had confirm:true",
                       lambda t: any((e.input or {}).get("confirm") is True
                                     for e in t.tool_events
                                     if e.name == "apply_constraints")),
                      answer_has_any(["applied", "recalculat", "in effect"])],
                     note="explicit apply -> now it fires with confirm:true"),
            ],
        ),

        # -------------------------------------------------------------------
        # 12. Ambiguous quantity reference across turns: two numbers in play
        #     (a cap and a priority); a later "bump it to 95" must hit the
        #     priority, not the cap — disambiguated by the noun.
        # -------------------------------------------------------------------
        Scenario(
            id="which_number_carryover",
            intent=("With both a container cap (50) and a priority (60) in play, "
                    "'bump the priority to 95' must change priority to 95 and leave "
                    "the cap at 50 — not confuse the two numbers."),
            steps=[
                Step("Draft a rule capping RKNE at 50 containers on NYC, priority 60.",
                     [no_error(), used("generate_constraints")],
                     note="cap=50, priority=60 both in play"),
                Step("Bump the priority on that to 95.",
                     [no_error(),
                      used_any(["generate_constraints", "edit_constraints"]),
                      ("RKNE rule still caps at 50 (cap untouched)",
                       lambda t: _staged_cap_is(t, "RKNE", 50)),
                      ("RKNE rule priority is now 95",
                       lambda t: _staged_priority_is(t, "RKNE", 95))],
                     note="change priority only; cap must stay 50"),
            ],
        ),
    ]


def _staged_priority_is(turn: Turn, carrier: str, value) -> bool:
    """True if the staged rule for `carrier` now has Priority Score == value."""
    want_c = str(carrier).strip().upper()

    def canon(k):
        return "".join(ch for ch in str(k).lower() if ch.isalnum())

    def pget(p, col):
        target = canon(col)
        for k, v in p.items():
            if canon(k) == target:
                return v
        return None

    for e in turn.tool_events:
        if e.name not in ("generate_constraints", "edit_constraints"):
            continue
        r = e.result if isinstance(e.result, dict) else {}
        rows = r.get("constraints") or r.get("working_set") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(pget(row, "Carrier") or "").upper() != want_c:
                continue
            pr = pget(row, "Priority Score")
            try:
                if pr is not None and float(pr) == float(value):
                    return True
            except (TypeError, ValueError):
                pass
    return False


def _staged_cap_is(turn: Turn, carrier: str, value) -> bool:
    """True if the conversation's staged constraints now cap `carrier` at `value`.

    Reads the generate_constraints result on this turn (the model re-stages the
    whole working set each edit), tolerant of snake_case / title-case keys.
    """
    want_c = str(carrier).strip().upper()

    def canon(k):
        return "".join(ch for ch in str(k).lower() if ch.isalnum())

    def pget(p, col):
        target = canon(col)
        for k, v in p.items():
            if canon(k) == target:
                return v
        return None

    for e in turn.tool_events:
        if e.name not in ("generate_constraints", "edit_constraints"):
            continue
        r = e.result if isinstance(e.result, dict) else {}
        rows = r.get("constraints") or r.get("working_set") or []
        # working_set entries may wrap the row under a key; flatten dicts.
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(pget(row, "Carrier") or "").upper() != want_c:
                continue
            cap = pget(row, "Maximum Container Count")
            try:
                if cap is not None and float(cap) == float(value):
                    return True
            except (TypeError, ValueError):
                pass
    return False


# ===========================================================================
# running
# ===========================================================================

def run_scenario(scenario: Scenario, client: BedrockChatClient,
                 verbose: bool = True) -> ScenarioResult:
    convo = Conversation(client=client)
    if scenario.seed_upload:
        from .conversation import hypothetical_upload_df
        convo.seed_uploaded_constraints(hypothetical_upload_df())
    # Pre-apply the dashboard's Data Filters, so the assistant's data view is
    # scoped exactly as it would be if the user had filtered the dashboard. The
    # executor reads these keys (via chat_ui._filtered_view) on every turn.
    if scenario.seed_filters:
        for k, v in scenario.seed_filters.items():
            convo.session_state[k] = v

    steps: List[StepResult] = []
    if verbose:
        print(f"\n{'━' * 72}\nSCENARIO [{scenario.id}]\n  {scenario.intent}")

    for i, step in enumerate(scenario.steps, 1):
        turn = convo.send(step.user)
        failed: List[str] = []
        for label, pred in step.checks:
            try:
                ok = bool(pred(turn))
            except Exception as e:  # a check must never crash the run
                ok = False
                label = f"{label} [predicate raised: {e}]"
            if not ok:
                failed.append(label)
        sr = StepResult(user=step.user, answer=turn.answer or "",
                        tools=turn.tools_used, failed=failed, error=turn.error)
        steps.append(sr)
        if verbose:
            tag = "PASS" if sr.passed else "FAIL"
            print(f"\n  [{tag}] turn {i}: {step.user}")
            if step.note:
                print(f"        probe : {step.note}")
            print(f"        tools : {sr.tools or 'none'}")
            if turn.error:
                print(f"        ERROR : {turn.error}")
            for f in failed:
                print(f"        x {f}")
            if not sr.passed:
                ans = (sr.answer or "").replace("\n", " ")
                if len(ans) > 280:
                    ans = ans[:280] + "…"
                print(f"        answer: {ans or '(empty)'}")
        # If a step errored we keep going — later steps reveal whether the
        # whole session wedged or just one turn tripped.

    return ScenarioResult(id=scenario.id, intent=scenario.intent, steps=steps)


def run_all(scenario_filter: Optional[str] = None, repeat: int = 1,
            verbose: bool = True) -> List[ScenarioResult]:
    client = BedrockChatClient()
    if not client.has_credentials:
        print("ERROR: No Bedrock credentials found. Add AWS_BEDROCK_API_KEY (or "
              "AWS_accessKeyId / AWS_secretAccessKey) to .env / tests/.env.")
        sys.exit(2)

    selected = [s for s in all_scenarios()
                if scenario_filter is None or s.id == scenario_filter]
    if not selected:
        print(f"ERROR: No scenario matches id '{scenario_filter}'. "
              f"Known: {[s.id for s in all_scenarios()]}")
        sys.exit(2)

    if verbose:
        print(f"Model: {client.model_id}  |  Region: {client.region}")
        print(f"Running {len(selected)} scenario(s) x {repeat}")

    results: List[ScenarioResult] = []
    for s in selected:
        for _ in range(repeat):
            results.append(run_scenario(s, client, verbose=verbose))
    return results


def summarize(results: List[ScenarioResult]) -> dict:
    by_id: dict = {}
    for r in results:
        by_id.setdefault(r.id, []).append(r.passed)
    passed = sum(1 for r in results if r.passed)
    return {
        "passed": passed, "total": len(results),
        "by_scenario": {sid: f"{sum(v)}/{len(v)}" for sid, v in by_id.items()},
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Multi-turn intent-tracking evaluator for the Tender Assistant")
    ap.add_argument("--scenario", help="run a single scenario by id")
    ap.add_argument("--repeat", type=int, default=1, help="runs per scenario")
    ap.add_argument("--json", help="write structured results to this path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    results = run_all(scenario_filter=args.scenario, repeat=args.repeat,
                      verbose=not args.quiet)
    summary = summarize(results)

    print(f"\n{'=' * 72}")
    print(f"RESULT: {summary['passed']}/{summary['total']} scenarios passed "
          f"({time.time() - t0:.0f}s)")
    for sid, ratio in summary["by_scenario"].items():
        mark = "OK " if ratio.split("/")[0] == ratio.split("/")[1] else "!! "
        print(f"  {mark}{sid}: {ratio}")

    if args.json:
        payload = {
            "summary": summary,
            "results": [
                {
                    "id": r.id, "intent": r.intent, "passed": r.passed,
                    "steps": [
                        {"user": s.user, "tools": s.tools, "passed": s.passed,
                         "failed_checks": s.failed, "error": s.error,
                         "answer": s.answer}
                        for s in r.steps
                    ],
                }
                for r in results
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nWrote structured results to {args.json}")

    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
