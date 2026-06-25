"""
Execution logging for the Tender Optimization chatbot.

Writes one self-contained JSON file per chat turn into the top-level
``execution logs/`` folder, capturing as much about the app and the LLM's work
as we can without bloating the log with raw data:

  - the user's question and where it sits in the conversation,
  - app metadata: version, git branch/commit, platform, model + region,
  - the full session context the turn ran under: active filters, optimizer
    weights, rate type, staged/applied constraints, peel-pile + scenario state,
  - a ``data`` section that LINKS to the data rather than embedding it — each
    DataFrame (comprehensive data, rate sheet) is snapshotted to a CSV under
    ``execution logs/data_snapshots/`` (deduplicated by content fingerprint) and
    the log records the file path, the column schema, and a ``read_check`` that
    confirms the assistant saw the data correctly,
  - the system prompt, snapshotted to ``execution logs/prompt_snapshots/`` with
    its size and the per-turn "Session status" line,
  - the turn's ``steps`` in chronological order — the model's reasoning before a
    round of tool calls (``type: reasoning``) interleaved with each tool call
    (``type: tool``) carrying its inputs, a compact result summary, the full
    result, whether it errored, and how long it took (``duration_ms``),
  - the final answer (or the error that stopped the turn).

Design rules:
  - Logging is best-effort: a failure to write a log NEVER interrupts the chat.
  - No raw data tables are embedded — they are written to snapshot files and
    referenced by path, so the JSON stays small and the data stays linkable.
  - This module does NOT import streamlit, so it stays pure and unit-testable;
    chat_ui.py reads session_state and passes a plain dict in.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# execution logs/ lives at the repo root. This file is at
# <repo>/components/chatbot/execution_logger.py, so go up two parents.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _REPO_ROOT / "execution logs"
_SNAPSHOT_DIR = _LOG_DIR / "data_snapshots"
_PROMPT_DIR = _LOG_DIR / "prompt_snapshots"

# Columns the chatbot's tools depend on. Their presence is the core signal for
# "did the assistant read the data correctly?" — if these are missing, the
# tools can't price flips, rank carriers, or trace containers.
_KEY_COLUMNS = [
    "Dray SCAC(FL)", "Container Count", "Lane", "Base Rate",
    "Total Rate", "CPC", "Performance_Score", "Week Number",
]

# Dimension columns we list distinct values for in the schema summary (metadata
# only — never the full data).
_DIMENSION_COLUMNS = {
    "Discharged Port": "ports",
    "Facility": "facilities",
    "Category": "categories",
    "SSL": "ssls",
    "Terminal": "terminals",
}

_MAX_LIST_ITEMS = 50      # truncate long lists in the stored result
_MAX_STRING_LEN = 5000    # truncate very long strings
_MAX_DISTINCT = 60        # cap distinct-value lists in the schema summary


# ==================== JSON-safe serialization ====================

def _safe(obj, _depth: int = 0):
    """Best-effort conversion to JSON-serializable data.

    Truncates long lists and strings so a single huge tool result can't bloat
    the log. Anything exotic (numpy scalars, timestamps) falls back to str().
    """
    if _depth > 8:
        return "<max depth>"
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return obj if len(obj) <= _MAX_STRING_LEN else obj[:_MAX_STRING_LEN] + "…<truncated>"
    if isinstance(obj, dict):
        return {str(k): _safe(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        seq = list(obj)
        items = [_safe(v, _depth + 1) for v in seq[:_MAX_LIST_ITEMS]]
        if len(seq) > _MAX_LIST_ITEMS:
            items.append(f"…<{len(seq) - _MAX_LIST_ITEMS} more items truncated>")
        return items
    # numpy / pandas scalars, Decimals, timestamps, etc.
    if hasattr(obj, "item"):  # numpy scalar -> python scalar
        try:
            return _safe(obj.item(), _depth + 1)
        except Exception:
            pass
    return str(obj)


# ==================== app metadata (computed once) ====================

def _app_version() -> str | None:
    try:
        text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*["\']([^"\']+)', text, re.MULTILINE)
        return m.group(1) if m else None
    except Exception:
        return None


def _git_info() -> dict:
    """Read branch + commit straight from .git (no subprocess)."""
    git_dir = _REPO_ROOT / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            branch = ref.rsplit("/", 1)[-1]
            ref_path = git_dir / ref
            commit = None
            if ref_path.exists():
                commit = ref_path.read_text(encoding="utf-8").strip()
            else:  # packed-refs fallback
                packed = git_dir / "packed-refs"
                if packed.exists():
                    for line in packed.read_text(encoding="utf-8").splitlines():
                        if line.endswith(ref):
                            commit = line.split(" ", 1)[0]
                            break
            return {"branch": branch, "commit": commit[:12] if commit else None}
        return {"branch": "(detached)", "commit": head[:12]}
    except Exception:
        return {"branch": None, "commit": None}


_APP_INFO = {
    "name": "Tender Optimization",
    "version": _app_version(),
    "git": _git_info(),
    "platform": platform.platform(),
    "python": sys.version.split()[0],
}


# ==================== data snapshots (link, don't embed) ====================

def _fingerprint(df) -> str:
    """Cheap, stable content fingerprint for snapshot dedup.

    Hashes shape + columns + dtypes + a sample of head/tail rows. Two genuinely
    different datasets colliding is astronomically unlikely; even if it happened
    the only cost is a stale snapshot, which is acceptable for a log.
    """
    import pandas as pd  # local import keeps the module import light

    h = hashlib.sha1()
    h.update(str(df.shape).encode())
    h.update("|".join(map(str, df.columns)).encode())
    h.update("|".join(str(t) for t in df.dtypes).encode())
    try:
        sample = pd.concat([df.head(500), df.tail(500)])
        h.update(pd.util.hash_pandas_object(sample, index=False).values.tobytes())
    except Exception:
        pass
    return h.hexdigest()[:12]


def snapshot_dataframe(df, label: str) -> dict:
    """Write ``df`` to a deduplicated CSV under data_snapshots/ and describe it.

    Returns the snapshot file path (relative + absolute) plus row/column counts.
    The same data written on a later turn reuses the existing file
    (``reused_existing: true``) — it is never rewritten. Returns a present=False
    stub when there is no data.
    """
    if df is None or len(df) == 0:
        return {"present": False, "rows": 0, "snapshot_file": None}

    out: dict = {
        "present": True,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
    }
    try:
        fp = _fingerprint(df)
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        fname = f"{label}_{fp}.csv"
        path = _SNAPSHOT_DIR / fname
        reused = path.exists()
        if not reused:
            df.to_csv(path, index=False)
        out.update({
            "snapshot_file": f"execution logs/data_snapshots/{fname}",
            "absolute_path": str(path),
            "fingerprint": fp,
            "reused_existing": reused,
            "bytes": path.stat().st_size if path.exists() else None,
        })
    except Exception as e:  # snapshot failure must not break logging
        out["snapshot_error"] = str(e)
        out["snapshot_file"] = None
    return out


def schema_summary(df) -> dict:
    """Column-level metadata (NOT the data): names, dtypes, week range, and the

    distinct values of the dimension columns (capped). This is what makes the
    log self-describing without embedding rows.
    """
    if df is None or len(df) == 0:
        return {}
    out: dict = {}
    try:
        out["columns"] = list(map(str, df.columns))
        out["dtypes"] = {str(c): str(t) for c, t in df.dtypes.items()}

        if "Week Number" in df.columns:
            wk = df["Week Number"].dropna()
            if len(wk):
                try:
                    weeks = sorted({int(w) for w in wk.unique()})
                    out["week_range"] = [weeks[0], weeks[-1]]
                    out["weeks_present"] = weeks[:_MAX_DISTINCT]
                except Exception:
                    pass

        if "Ocean ETA" in df.columns:
            try:
                eta = df["Ocean ETA"].dropna()
                if len(eta):
                    out["ocean_eta_range"] = [str(eta.min()), str(eta.max())]
            except Exception:
                pass

        for col, key in _DIMENSION_COLUMNS.items():
            if col in df.columns:
                try:
                    vals = sorted({str(v) for v in df[col].dropna().unique()})
                    out[key] = vals[:_MAX_DISTINCT]
                    out[f"{key}_count"] = len(vals)
                except Exception:
                    pass
    except Exception as e:
        out["schema_error"] = str(e)
    return out


# ==================== data-read verification ====================

def inspect_data(df, rate_data=None, rate_type="Base Rate") -> dict:
    """Snapshot what the assistant was handed, to confirm it read data correctly.

    Returns row/column counts, which key columns are present vs missing, how
    many distinct carriers are visible, total container volume, and whether the
    rate sheet was supplied. ``looks_ok`` is a quick pass/fail: there are rows
    and no key columns are missing.
    """
    info: dict = {
        "data_loaded": df is not None and len(df) > 0,
        "rows": 0,
        "columns": 0,
        "key_columns_present": [],
        "key_columns_missing": [],
        "n_carriers": 0,
        "sample_carriers": [],
        "total_container_count": None,
        "n_unique_lanes": None,
        "rate_data_provided": (rate_data is not None and len(rate_data) > 0)
        if rate_data is not None else False,
        "rate_type": rate_type,
        "looks_ok": False,
        "notes": [],
    }

    if df is None or len(df) == 0:
        info["notes"].append("No data was provided to the assistant for this turn.")
        return info

    try:
        info["rows"] = int(len(df))
        info["columns"] = int(len(df.columns))

        present = [c for c in _KEY_COLUMNS if c in df.columns]
        missing = [c for c in _KEY_COLUMNS if c not in df.columns]
        info["key_columns_present"] = present
        info["key_columns_missing"] = missing

        # Carrier visibility (mirror chat_ui._valid_carriers' column fallback).
        carrier_col = (
            "Dray SCAC(FL)" if "Dray SCAC(FL)" in df.columns
            else "Carrier" if "Carrier" in df.columns else None
        )
        if carrier_col:
            carriers = sorted({str(c).strip() for c in df[carrier_col].dropna().unique()})
            info["n_carriers"] = len(carriers)
            info["sample_carriers"] = carriers[:15]
        else:
            info["notes"].append("No carrier column found (Dray SCAC(FL) / Carrier).")

        if "Container Count" in df.columns:
            try:
                info["total_container_count"] = int(df["Container Count"].fillna(0).sum())
            except Exception:
                info["notes"].append("Container Count column is not numeric.")

        if "Lane" in df.columns:
            info["n_unique_lanes"] = int(df["Lane"].dropna().nunique())

        if "Missing_Rate" in df.columns:
            try:
                info["rows_missing_rate"] = int(df["Missing_Rate"].fillna(False).sum())
            except Exception:
                pass

        if missing:
            info["notes"].append("Missing expected columns: " + ", ".join(missing))

        info["looks_ok"] = info["rows"] > 0 and not missing and bool(carrier_col)
    except Exception as e:  # never let inspection break logging
        info["notes"].append(f"Inspection error: {e}")

    return info


# ==================== per-tool result summary ====================

def _summarize_result(result) -> dict:
    """A compact, scannable summary of a tool result for the log header.

    Surfaces the things that matter when checking data reads: did it error,
    is it empty, how many rows/items came back, and any error message.
    """
    summary: dict = {"type": type(result).__name__}
    if isinstance(result, dict):
        if "error" in result:
            summary["error"] = str(result["error"])[:500]
        if "ok" in result:
            summary["ok"] = result.get("ok")
        # Common count-ish fields tools return.
        for k in ("count", "rows", "n_rows", "total", "applied_count",
                  "removed_count", "matched", "n_matched"):
            if k in result:
                summary[k] = result[k]
        # Any list field: report its length (e.g. results, constraints, carriers).
        list_lens = {k: len(v) for k, v in result.items() if isinstance(v, list)}
        if list_lens:
            summary["list_lengths"] = list_lens
        summary["keys"] = list(result.keys())[:25]
    elif isinstance(result, list):
        summary["length"] = len(result)
    return summary


# ==================== the logger ====================

class ExecutionLogger:
    """Accumulates one chat turn's activity and writes it to a JSON file.

    Usage::

        ex = ExecutionLogger(
            user_text, df=df, rate_data=rate_data, rate_type=rate_type,
            model_id=client.model_id, region=client.region,
            session_context=ctx, turn_index=n, prior_message_count=m,
        )
        ex.set_system_prompt(system_prompt, tool_specs_count=len(TOOL_SPECS))
        ...
        ex.log_tool(name, tool_input, result, is_error)   # per tool call
        ex.set_reply(final_text)                          # on success
        ex.set_error(message)                             # on failure
        ex.write()                                        # always, in a finally
    """

    def __init__(self, user_message: str, df=None, rate_data=None,
                 rate_type: str = "Base Rate", model_id=None, region=None,
                 session_context: dict | None = None, turn_index=None,
                 prior_message_count=None):
        self.started = datetime.now()
        self.user_message = user_message or ""
        # The reasoning text of the most-recent tool round, so a round that fires
        # several tools logs its shared narration once (see log_tool).
        self._last_reasoning = None
        self.record: dict = {
            "schema_version": 3,
            "timestamp": self.started.isoformat(timespec="seconds"),
            "user_message": self.user_message,
            "app": _APP_INFO,
            "model": {"model_id": model_id, "region": region},
            "conversation": {
                "turn_index": turn_index,
                "prior_message_count": prior_message_count,
            },
            "session_context": _safe(session_context or {}),
            "data": {
                "comprehensive_data": {
                    **snapshot_dataframe(df, "comprehensive_data"),
                    "read_check": inspect_data(df, rate_data, rate_type),
                    "schema": schema_summary(df),
                },
                "rate_data": snapshot_dataframe(rate_data, "rate_data"),
            },
            "system_prompt": None,
            "tool_calls_count": 0,
            "tool_time_ms_total": None,
            "had_error": False,
            "steps": [],
            "final_reply": None,
            "suggested_followups": [],
            "error": None,
            "duration_seconds": None,
        }

    def set_system_prompt(self, text: str, tool_specs_count=None):
        """Record the system prompt's size + status line, snapshot it to a file.

        The prompt is ~27 KB and nearly identical every turn, so it is written
        to a deduplicated file under prompt_snapshots/ and only the size and the
        per-turn "Session status" line are kept inline.
        """
        text = text or ""
        info: dict = {
            "chars": len(text),
            "lines": text.count("\n") + 1,
            "tokens_estimate": round(len(text) / 4),
            "tool_specs_count": tool_specs_count,
        }
        for line in text.splitlines():
            if "Session status" in line:
                info["session_status_line"] = line.strip()[:_MAX_STRING_LEN]
                break
        try:
            fp = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
            _PROMPT_DIR.mkdir(parents=True, exist_ok=True)
            path = _PROMPT_DIR / f"system_{fp}.txt"
            reused = path.exists()
            if not reused:
                path.write_text(text, encoding="utf-8")
            info["snapshot_file"] = f"execution logs/prompt_snapshots/system_{fp}.txt"
            info["reused_existing"] = reused
        except Exception as e:
            info["snapshot_error"] = str(e)
        self.record["system_prompt"] = info

    def log_tool(self, name, tool_input, result, is_error,
                 duration_ms=None, reasoning=None):
        """Record one tool call: the model's reasoning for it, what it was asked,
        what it returned, whether it failed, and how long it took.

        ``reasoning`` is the assistant's narration that preceded this round of
        tool calls — its rationale for the call. The model emits it once per
        round even when it then fires several tools, so it is logged as its own
        ``reasoning`` step the FIRST time a round's text is seen and elided on the
        sibling tool steps; this keeps the steps reading in true chronological
        order (thought -> tool -> tool -> thought -> final reply) without
        repeating the same paragraph on every tool.
        """
        reasoning = (reasoning or "").strip()
        if reasoning and reasoning != self._last_reasoning:
            self._last_reasoning = reasoning
            self.record["steps"].append({
                "step": len(self.record["steps"]) + 1,
                "type": "reasoning",
                "thought": reasoning[:_MAX_STRING_LEN],
            })

        self.record["steps"].append({
            "step": len(self.record["steps"]) + 1,
            "type": "tool",
            "tool": name,
            "is_error": bool(is_error),
            "duration_ms": duration_ms,
            "input": _safe(tool_input or {}),
            "result_summary": _summarize_result(result),
            "result": _safe(result),
        })
        self.record["tool_calls_count"] += 1
        if duration_ms is not None:
            self.record["tool_time_ms_total"] = round(
                (self.record.get("tool_time_ms_total") or 0) + duration_ms, 1
            )
        if is_error:
            self.record["had_error"] = True

    def set_reply(self, text):
        self.record["final_reply"] = (text or "")[:_MAX_STRING_LEN]

    def set_followups(self, suggestions):
        """Record the clickable follow-up suggestions offered after this turn."""
        self.record["suggested_followups"] = [
            str(s)[:200] for s in (suggestions or [])
        ]

    def set_error(self, message):
        self.record["error"] = str(message)[:_MAX_STRING_LEN]
        self.record["had_error"] = True

    def _filename(self) -> str:
        stamp = self.started.strftime("%Y-%m-%d_%H-%M-%S")
        slug = re.sub(r"[^a-z0-9]+", "-", self.user_message.lower()).strip("-")[:40]
        slug = slug or "turn"
        return f"{stamp}_{slug}.json"

    def write(self) -> Path | None:
        """Write the turn's JSON file. Never raises — logging must not break chat."""
        try:
            self.record["duration_seconds"] = round(
                (datetime.now() - self.started).total_seconds(), 2
            )
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            path = _LOG_DIR / self._filename()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.record, f, indent=2, ensure_ascii=False, default=str)
            logger.info("Wrote chatbot execution log: %s", path)
            return path
        except Exception:
            logger.exception("Failed to write chatbot execution log")
            return None
