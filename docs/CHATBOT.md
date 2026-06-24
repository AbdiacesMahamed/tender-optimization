# Tender Optimization Assistant (AI Chatbot)

A Bedrock-powered assistant embedded in the dashboard sidebar. It can:

1. **Analyze** the currently loaded data (carriers, lanes, ports, weeks, cost, performance).
2. **Price carrier flips** — "what does flipping these to ATMI cost?" (read-only simulation).
3. **Generate** new allocation constraints from a plain-English description.
4. **Edit / remove** the constraints you have uploaded (or drafted in chat).

Replies **stream** token-by-token, and each **tool call streams its result into the chat**
as it finishes — an expandable "🔧 \<tool\>" panel showing the tool's input and raw result,
rendered above the answer. These panels persist in the transcript across Streamlit reruns.
Proposed/edited constraints appear in an editable table in the sidebar. From there you can
**Apply** them to the live optimization (no re-upload needed) or **Download** them as an
`.xlsx` matching `docs/constraint_template.xlsx`.

## Constraint awareness (uploaded ↔ chat)

The assistant works against a single **working set** of constraints:

- If you uploaded a constraint file in the main panel, it is **seeded into the working
  set once** and tagged `origin: uploaded`. When you say *"edit my constraints"* the
  assistant edits **those** rows — it calls `describe_constraints` first to read the real
  rows + indices, then `edit_constraints`.
- If **nothing** is loaded, the assistant **asks** you to upload a file or describe the
  rule — it will not invent constraints to edit.
- Generating a new rule **appends** to the set; uploaded rows are never silently dropped.
- Anything you upload in the main panel (or the dashboard generates) is automatically
  reachable by the assistant — there is no separate in-chat uploader to manage.

**Apply semantics:** when you click *Apply* in the chat panel, the applied set (which
already includes any incorporated uploaded rows) becomes authoritative — the dashboard
uses it alone and does **not** re-process the raw uploaded file, so rows are never
double-counted.

## Architecture

```
dashboard.py
  ├─ show_chatbot_sidebar(comprehensive_data, rate_data, constraints_file)  # renders the panel,
  │                                                        # seeds uploaded constraints
  └─ get_applied_constraints_df()                          # injects applied constraints
                                                           # into apply_constraints_to_data()

components/chatbot/
  ├─ bedrock_client.py   Bedrock Converse wrapper: run_conversation (blocking) +
  │                      stream_conversation (token streaming, emits tool_use /
  │                      tool_result events carrying each tool's input + result) +
  │                      agentic tool loop
  ├─ skill.py            Always-loaded capability/reference card (SKILL) — maps the
  │                      whole report + agent surface area; appended to SYSTEM_PROMPT
  ├─ tool_specs.py       System prompt (deep constraint mechanics) + SKILL + Converse
  │                      tool schemas. SYSTEM_PROMPT = base prompt + SKILL.
  ├─ tools.py            Pure tool implementations (no Streamlit/Bedrock) — unit-testable
  └─ chat_ui.py          Sidebar UI, session state, tool executor,
                         streaming render (incl. live tool-result panels),
                         staging/apply/download
```

**Always-loaded skill card.** `skill.py` holds a single `SKILL` string — a reference
card covering everything the **report** (dashboard) and the **agent** can do: the four
scenarios, the LP optimizer steps, the constraint schema, peel piles, the metrics/columns
the planner sees, the full tool catalog, the carrier-SCAC glossary, and the hard limits.
It is appended to `SYSTEM_PROMPT`, so it is in the model's context on **every** turn (live
UI and the evals harness, which both import `SYSTEM_PROMPT`). Procedural rules (when to
call what, the apply protocol) stay in the base prompt; the card just maps what exists.
Edit `skill.py` to change what the assistant always knows about the product.

**Tools exposed to the model:** `analyze_data`, `describe_selection`, `simulate_flip`,
`compare_carriers`, `lane_rate_options`, `flip_report`, `describe_constraints`,
`preview_constraint_scope`, `generate_constraints`, `edit_constraints`
(and `read_constraints_summary` for explaining applied-constraint impact).

The tool functions in `tools.py` are pure (DataFrame in, JSON-serializable dict out), so they
are exercised directly by `tests/test_chatbot.py` without network access.

## Configuration (`tests/.env`)

| Variable | Purpose |
|---|---|
| `AWS_BEDROCK_API_KEY` | Bedrock bearer token (preferred auth). Exported as `AWS_BEARER_TOKEN_BEDROCK`. |
| `AWS_accessKeyId` / `AWS_secretAccessKey` | SigV4 fallback. Used automatically if the bearer token is rejected. |
| `BEDROCK_MODEL_ID` | Inference profile, e.g. `us.anthropic.claude-opus-4-8` or `us.anthropic.claude-opus-4-6-v1`. |
| `BEDROCK_REGION` / `AWS_REGION` / `S3_REGION` | Region (defaults to `us-east-1`). |

**Auth fallback:** the client tries the Bedrock bearer token first. If AWS returns
`AccessDeniedException`/`Authentication failed` and SigV4 access keys are present, it
transparently retries the call signed with the access keys. This means a stale/expired
API key in `.env` does not take the assistant down as long as valid access keys exist.

**Model IDs:** Bedrock requires a real inference-profile ID. Some hand-written values
(e.g. `us.anthropic.claude-opus-4-6-20251101-v1:0`) are not valid profiles and 400 with
"model identifier is invalid"; `bedrock_client._MODEL_ID_FIXUPS` rewrites the known-bad
forms to a valid profile. List valid profiles with
`boto3.client('bedrock').list_inference_profiles()`.

## Notes / gotchas (validated against live Bedrock)

- **No `temperature`.** Opus 4.7+ (incl. `opus-4-8`) reject sampling params; the Converse
  call sends only `maxTokens`.
- **Tool-schema keys use underscores** (`priority_score`, `week_number`). Bedrock's Converse
  API rejects property keys containing spaces. `tools.py` maps these back to the spaced
  column names (`Priority Score`, etc.) case/separator-insensitively, so the constraint
  Excel still uses the exact template column headers.
- The assistant **cannot apply constraints itself** — it stages proposals; the human clicks
  Apply or Download. Applied constraints are merged with any uploaded constraint file and
  processed together by priority.

## Tests

```
.venv/Scripts/python.exe -m pytest tests/test_chatbot.py -q
```

These are adversarial: hostile/edge-case inputs (SQL-ish query types, NaN performance,
out-of-range percents, junk keys, out-of-range edit indices, tool crashes, infinite
tool-use loops) confirming the tools and the conversation loop degrade safely. The Bedrock
loop is tested with a fake client, so no credentials are required.
```
