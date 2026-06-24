# Prompt-Intent Eval Harness

A harness for testing **whether the Tender Assistant's prompts steer the model
to match user intent** — then iterating on the prompt until they do.

Where the offline suites in `tests/` prove the *pure tools* are correct
(`test_chatbot.py`, `test_agent_simulation.py`), this harness proves the
**system prompt + tool specs** make a real model *use* those tools the way a
user means. It drives the actual Bedrock Converse tool-use loop — same
`BedrockChatClient`, `SYSTEM_PROMPT`, and `TOOL_SPECS` the dashboard uses.

## What it checks

For each natural-language prompt, the harness records every tool call the model
makes and scores three layers of intent-matching:

1. **Tool routing** — did it call the right tool(s)? (`expect_tools`,
   `expect_any_tool`, `forbid_tools`)
2. **Arguments / scope** — did it scope correctly? (`arg_checks` — predicates
   over the recorded calls, e.g. "scope is week 32", "proposal caps RKNE at 50")
3. **Final answer** — does the answer reflect the real tool result?
   (`answer_contains`, `answer_contains_any`, `answer_not_contains`,
   `answer_regex`, `answer_predicate`)

Checks are **predicates, not exact transcripts**, so they tolerate the natural
phrasing variation of a real model while still pinning down intent. Every
numeric expectation is computed from `fixture.py` ground-truth helpers, so the
cases can never silently drift from the data.

## Files

| File | Role |
|------|------|
| `fixture.py` | Deterministic working-data + rate-sheet fixture, plus computed ground-truth helpers. Includes a deliberate **unrated lane** (ATMI has no rate on `USNYCEWR9`) so cases can assert the assistant never prices unrated volume at $0. |
| `cases.py`   | The `IntentCase` list — one per intent, with routing/arg/answer checks. |
| `harness.py` | The runner: drives the real loop, records tool calls, scores, reports. |

## Running

Needs Bedrock credentials (`.env` — `AWS_BEDROCK_API_KEY` or
`AWS_accessKeyId`/`AWS_secretAccessKey`) and `boto3`:

```bash
python -m evals.harness                      # all cases, human-readable report
python -m evals.harness --case flip_week32_to_atmi   # one case
python -m evals.harness --repeat 3           # N runs per case (flakiness check)
python -m evals.harness --json out.json      # also dump structured results
python -m evals.harness --quiet              # summary only
```

Exit code is non-zero if any run fails, so it can gate CI or a retry loop.
Without credentials it exits early with a clear message — it never fakes a pass.

## The iterate-until-intent workflow

This is the loop the harness is built for:

1. **Run** the harness. Failing cases print the failed checks, the tools used,
   and the answer.
2. **Analyze** each failure. Is it a *prompt problem* (model routed wrong /
   scoped wrong / over-claimed) or a *harness problem* (a check too strict)?
   Inspect the exact tool inputs in the `--json` dump.
3. **Fix the root cause** — edit `SYSTEM_PROMPT` / a tool `description` in
   `components/chatbot/tool_specs.py` for a prompt problem; fix the predicate in
   `cases.py` for a harness problem.
4. **Re-run** the affected case with `--repeat` to confirm the fix is stable
   (model output varies run to run), then run the full suite.

### Findings this loop has already produced

- **`preview_constraint_scope` carrier smuggling** — the model put a carrier
  SCAC into the `ssl` field because that tool has no Carrier field. Fixed by
  making the tool description forbid it; guarded by an `arg_check`.
- **price-ranking routed to `by_carrier`** — the model used the volume-capped
  `by_carrier` query for "cheapest carrier?", which can hide the true cheapest
  on larger data. Fixed by steering the prompt to the purpose-built `cheapest`
  query_type.

## Offline machinery tests

The harness's own scoring/predicate/fixture logic is regression-tested without
Bedrock in `tests/test_evals_harness.py` (uses a scripted fake client). Run:

```bash
python -m pytest tests/test_evals_harness.py -q
```

## Adding a case

Append an `IntentCase` to `all_cases()` in `cases.py`. Pull every number from a
`fixture.py` helper (don't hand-copy), give it at least one routing check, and
prefer `arg_checks`/`answer_contains_any` over brittle exact-string matches.
