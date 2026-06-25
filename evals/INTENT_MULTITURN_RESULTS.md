# Multi-turn intent-tracking evaluation

`python -m evals.intent_multiturn` drives the **live** Bedrock Converse loop
through hard multi-turn conversations and asks one question: *does the assistant
track what the user means across turns* — carrying scope/referents forward,
switching cleanly when the user pivots, and **asking ONE clarifying question
when (and only when) a request is genuinely ambiguous**?

It reuses `evals/conversation.py`'s stateful `Conversation` driver (same client,
SYSTEM_PROMPT, TOOL_SPECS, session-state persistence as the dashboard sidebar).
Each `Scenario` is an ordered list of `Step`s; a step is a user utterance plus
predicates over the resulting turn (tools called, their scope, the answer text).

## Run it

```
python -m evals.intent_multiturn                       # all scenarios
python -m evals.intent_multiturn --scenario week_carryover
python -m evals.intent_multiturn --repeat 2            # flakiness check
python -m evals.intent_multiturn --json out.json       # structured trace
```

Needs Bedrock creds (`.env` / `tests/.env`) + boto3, like the other live harnesses.

## The 12 scenarios

| id | what it stresses |
|---|---|
| `week_carryover` | the canonical "wk32 then follow-ups" — scope must carry, then a "what about 33?" switches cleanly and does NOT drag 32 along |
| `carrier_referent_carryover` | "the cheaper one" / "flip it to them" resolve from the prior comparison, no re-asking |
| `ambiguous_best_then_resolve` | "which carrier?" with no scope → must ASK; once scoped, must ACT (no over-asking loop) |
| `total_request_no_overask` | "total containers" clearly means everything → answer, do NOT over-ask |
| `correction_wins` | user revises a cap 50→30 → the corrected value wins, nothing applied |
| `result_referent_carryover` | "the most expensive one" points at whatever the prior ranking surfaced |
| `dangling_these_clarify` | opening "flip these" with no selection → ask what "these" means, don't flip everything |
| `progressive_narrowing` | NYC → EWR9 → wk32 accumulate; the final flip carries all three |
| `topic_switch_drops_referent` | "forget that" pivots subject; later "it" tracks the NEW subject, old lane doesn't leak |
| `impossible_rule_flagged` | a min-500 on a tiny lane is staged AND flagged as exceeding the pool |
| `soft_ack_does_not_apply` | a soft "ok looks fine" must NOT apply; an explicit "apply it" does (confirm:true) |
| `which_number_carryover` | with a cap (50) and priority (60) in play, "bump the priority to 95" hits priority, leaves the cap |

Two failure modes are checked symmetrically: **under-asking** (guessing a scope
when the request is ambiguous) and **over-asking** (posing a clarifying question
when the request is clearly total). The clarify check requires a `?` AND that no
scoped action tool fired.

## What the iteration found

The assistant tracked intent correctly across all 12 scenarios. Iteration
surfaced two distinct kinds of issue:

1. **Harness-predicate over-fitting (4 scenarios), fixed in the eval.** The model
   answered "show me the week 32 data" with `describe_selection` rather than
   `analyze_data`, did a correction with `edit_constraints` rather than
   `generate_constraints`, and ranked carriers with `run_analysis` — all valid
   ways to satisfy the intent. The intent assertions (scope carryover, the
   corrected value) passed; only the rigid single-tool check failed. Loosened to
   accept the tool *family* (`used_any`), since this harness evaluates intent
   understanding, not a pinned tool choice.

2. **A real product bug (`soft_ack_does_not_apply`), fixed in the app.** Every
   turn errored with a Converse `ValidationException` at
   `messages.N.content.0.toolResult.content.0.json`. Root cause: a tool result
   contained an **empty-string object key** — `preview_optimization` produced a
   `carrier_mix[""]` bucket for a container with no assigned carrier SCAC, and
   Bedrock forbids `""` as a property name. Because the bad toolResult is
   persisted in history, it 400'd *every later turn* too — the conversation
   wedged permanently. Fixed at the Converse boundary in `bedrock_client.py`
   (`_as_tool_result_json` / `_json_sanitize`): tool results are now deep-scrubbed
   to (a) rename empty/whitespace keys to `"(unassigned)"` and (b) replace
   non-finite floats (NaN/Infinity, e.g. a percent delta over a zero baseline)
   with `null`, and non-dict results are wrapped. Locked in with offline unit
   tests in `tests/test_chatbot.py`.

The boundary scrub generalizes beyond this one tool: no tool can now wedge a
session with a value it happens to produce on an edge-case input.
