# Execution logs

One JSON file is written here **per chat turn** with the Tender Assistant, capturing
as much about the app and the LLM's work as possible. Use these to confirm the
assistant read the data correctly and to audit what it did, under exactly which
app configuration.

Filename: `YYYY-MM-DD_HH-MM-SS_<question-slug>.json`

## Folder layout

```
execution logs/
├── README.md                         ← this file (committed)
├── 2026-06-18_13-02-19_….json        ← one per chat turn (git-ignored)
├── data_snapshots/                   ← the data tables, linked from logs (git-ignored)
│   ├── comprehensive_data_<hash>.csv
│   └── rate_data_<hash>.csv
└── prompt_snapshots/                 ← the system prompts, linked from logs (git-ignored)
    └── system_<hash>.txt
```

**Data is never embedded in the JSON.** Each turn snapshots the data tables to CSV
files under `data_snapshots/` and the log links to them by path. Snapshots are
**deduplicated by content** — if the data hasn't changed, the same file is reused
(`reused_existing: true`) instead of rewritten, so 50 turns over the same upload
produce one CSV, not 50. Same for the system prompt under `prompt_snapshots/`.

## What's in each turn's JSON

| Field | Meaning |
|---|---|
| `schema_version` | Log format version (currently 2) |
| `timestamp` | When the turn started |
| `user_message` | The exact question asked |
| `app` | `version`, `git` (branch + commit), `platform`, `python` — which build answered |
| `model` | `model_id` + `region` that answered |
| `conversation` | `turn_index` and `prior_message_count` — where this sits in the chat |
| `session_context` | The live app state the turn ran under — see below |
| `data` | Links + checks for the data tables — see below |
| `system_prompt` | Size, token estimate, the per-turn "Session status" line, and a link to the full prompt snapshot |
| `tool_calls_count` | How many tools the LLM ran |
| `had_error` | True if any tool errored or the turn failed |
| `steps[]` | Every tool call in order: `tool`, `input`, `result_summary`, full `result`, `is_error` |
| `final_reply` | The answer shown to the user (the follow-up block is stripped out) |
| `suggested_followups` | The clickable follow-up pills offered after the answer |
| `error` | Set only if the turn failed |
| `duration_seconds` | Wall-clock time for the turn |

## `data` — the data tables (linked) + correctness checks

`data.comprehensive_data` and `data.rate_data` each record:

- `snapshot_file` / `absolute_path` — **the CSV you can open** to see the actual data.
- `rows`, `columns`, `fingerprint`, `reused_existing`, `bytes`.

`data.comprehensive_data` additionally carries:

- **`read_check`** — the data-correctness signal (see below).
- **`schema`** — column names + dtypes, `week_range`, `ocean_eta_range`, and the
  distinct values of dimension columns (ports, facilities, categories, ssls,
  terminals — each capped) with `*_count`. This makes the log self-describing
  without dumping rows.

### `read_check` — "did it read the data correctly?"

- `looks_ok` — quick pass/fail: there are rows **and** no key columns are missing.
- `rows`, `columns`.
- `key_columns_present` / `key_columns_missing` — the columns the tools depend on
  (`Dray SCAC(FL)`, `Container Count`, `Lane`, `Base Rate`, `Total Rate`, `CPC`,
  `Performance_Score`, `Week Number`). Anything missing means the assistant could
  not fully price flips / rank carriers.
- `n_carriers`, `sample_carriers`, `total_container_count`, `n_unique_lanes`,
  `rows_missing_rate` — sanity totals.
- `rate_data_provided`, `rate_type`.

If `looks_ok` is `false` or `key_columns_missing` is non-empty, start debugging there.

## `session_context` — what the optimizer was configured to do

- `rate_type` — `Base Rate` or `CPC`.
- `optimizer_weights` — `cost_weight_pct`, `performance_weight_pct`, `max_growth_pct` (0–100).
- `filters` — `applied`, plus selected `ports` / `facilities` / `weeks` / `carriers`.
- `constraints` — `staged_count`, `staged_with_problems`, `applied_count`,
  `source_signature` (the uploaded constraint file), `summary_rows`.
- `peel_pile` — `allocations`, `pending`.
- `scenarios_computed` — which scenarios were cached this session.
- `optimization_error` — any optimizer error string in session state.

Everything under `execution logs/` except this README is git-ignored — these are
local run logs, not source.
