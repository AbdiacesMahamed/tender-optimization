"""
Sandboxed pandas execution for the Tender Optimization assistant.

This module lets the assistant answer open-ended analytical questions that the
fixed tools (``analyze_data``, ``simulate_flip``, …) can't express, by running a
*small* snippet of model-written pandas against a **read-only copy** of the
loaded data. Like ``simulation.py`` it is deliberately **pure**: no Streamlit, no
Bedrock, no network — so it can be unit-tested and adversarially probed in
isolation.

SECURITY MODEL — read before extending
---------------------------------------
In-process Python is not a true security boundary, so this is *defense in
depth*, layered so an escape has to beat all of them:

  1. **Static AST denylist** (``check_code``): rejects ``import``, attribute
     access to any ``_``/dunder name (kills the
     ``().__class__.__bases__[0].__subclasses__()`` escape), ``.format`` /
     ``.format_map`` (kills the ``"{0.__class__}".format(x)`` escape), and the
     dangerous builtins by name (``eval``/``exec``/``open``/``__import__``/
     ``getattr``/…).
  2. **Restricted builtins**: the snippet runs with a curated ``__builtins__``
     containing only safe, pure functions — no ``open``, no ``__import__``, no
     ``eval``. No module (not even ``pandas``) is in scope; a small ``pd`` shim
     exposes only safe constructors/helpers.
  3. **Read-only data**: the snippet sees ``df``, a *copy* of the working data,
     so it cannot mutate what the dashboard holds.
  4. **Output caps**: results are truncated to ``max_rows`` / ``max_cells`` and
     serialized defensively; truncation is reported, never silent.
  5. **Best-effort timeout**: the snippet runs in a daemon thread joined with a
     timeout. NOTE: Python cannot forcibly kill a thread, so a deliberate
     infinite loop keeps running in the background until the process exits — the
     *result* is abandoned and an error returned. This is acceptable here
     because the dashboard is single-user (a runaway hangs only that analyst's
     own session), but it is the one guarantee this sandbox does NOT make.

Because credentials live in this process's environment (see ``bedrock_client``),
layers 1–2 are what stop snippet code from reaching ``os.environ`` / the
filesystem / the network. Treat any change that weakens them as a security
change.

Contract for the snippet
-------------------------
The snippet must assign its answer to a variable named ``result`` (a DataFrame,
Series, scalar, dict, or list). ``df`` is the data. Example::

    result = (df.groupby("Dray SCAC(FL)")["Container Count"].sum()
                .sort_values(ascending=False).head(10))
"""
from __future__ import annotations

import ast
import io
import math
import threading
from contextlib import redirect_stdout
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Hard limits — also a backstop against a snippet that returns something huge.
MAX_CODE_LEN = 8_000
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAX_ROWS = 200
DEFAULT_MAX_CELLS = 20_000  # rows * cols ceiling for a returned DataFrame
MAX_STDOUT_CHARS = 10_000

# ---------------------------------------------------------------------------
# Layer 1: static AST analysis
# ---------------------------------------------------------------------------

# Attribute names that are never allowed (beyond the blanket "_*" rule below).
# .format / .format_map evaluate attribute-access expressions inside the format
# string at runtime, bypassing this AST walk — so they must be blocked here.
_ATTR_DENY = {"format", "format_map"}

# pandas I/O + expression methods reachable on a DataFrame/Series WITHOUT an
# import or a dunder — so the other layers don't catch them. They are the real
# escape surface:
#   * df.to_csv('/path') / to_pickle / to_sql / to_clipboard ... WRITE files /
#     network / clipboard as a side effect (an adversarial probe confirmed
#     to_csv wrote a file even though it returned None).
#   * df.eval(...) / df.query(...) / pipe(...) run pandas' own expression engine
#     (an un-audited eval surface) or hand control to an arbitrary callable.
# Safe in-memory converters (to_dict, to_numpy, to_frame, to_list, to_records,
# to_timestamp, to_period) are deliberately NOT here — they don't touch the
# outside world. Add any new pandas writer to this set, not to the allowlist.
_ATTR_DENY |= {
    # writers (filesystem / network / clipboard)
    "to_csv", "to_excel", "to_json", "to_pickle", "to_parquet", "to_feather",
    "to_hdf", "to_stata", "to_html", "to_xml", "to_latex", "to_markdown",
    "to_string", "to_clipboard", "to_sql", "to_gbq", "to_orc",
    # readers (defensive — not instance methods, but block the names anyway)
    "read_csv", "read_excel", "read_json", "read_pickle", "read_parquet",
    "read_sql", "read_html", "read_table", "read_feather", "read_hdf",
    # expression evaluators / arbitrary-callable handoff
    "eval", "query", "pipe",
}

# Builtin/global names that must never be reachable, even though most are absent
# from the restricted builtins — a static error gives a clearer message than a
# downstream NameError and double-locks the door.
_NAME_DENY = {
    "eval", "exec", "compile", "open", "__import__", "import",
    "getattr", "setattr", "delattr", "hasattr",
    "globals", "locals", "vars", "dir",
    "input", "exit", "quit", "help", "breakpoint",
    "memoryview", "object", "type", "super", "classmethod", "staticmethod",
    "property", "vars", "id",
}

# AST node types that are categorically rejected.
_NODE_DENY = (
    ast.Import,
    ast.ImportFrom,
    ast.With,        # context managers (e.g. open(...)) — not needed for analysis
    ast.AsyncWith,
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.Global,
    ast.Nonlocal,
    ast.Yield,
    ast.YieldFrom,
)


def check_code(code: str) -> List[str]:
    """Static-analyze ``code`` and return a list of policy violations.

    Empty list == the snippet passed every static check. Never raises on user
    input — a syntax error is returned as a violation, not an exception.
    """
    violations: List[str] = []

    if not isinstance(code, str) or not code.strip():
        return ["No code provided."]
    if len(code) > MAX_CODE_LEN:
        return [f"Code is too long ({len(code)} chars; limit {MAX_CODE_LEN})."]

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return [f"Syntax error: {e.msg} (line {e.lineno})."]

    for node in ast.walk(tree):
        if isinstance(node, _NODE_DENY):
            violations.append(f"'{type(node).__name__}' is not allowed in analysis code.")
            continue

        if isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("_"):
                violations.append(f"Access to dunder/private attribute '{attr}' is not allowed.")
            elif attr in _ATTR_DENY:
                violations.append(f"Access to attribute '{attr}' is not allowed.")

        elif isinstance(node, ast.Name):
            name = node.id
            if name in _NAME_DENY:
                violations.append(f"Use of '{name}' is not allowed.")
            elif name.startswith("__"):
                violations.append(f"Access to '{name}' is not allowed.")

        # Keyword-argument names like func(__import__=...) and **{} unpacking.
        elif isinstance(node, ast.keyword):
            if node.arg and node.arg.startswith("__"):
                violations.append(f"Keyword '{node.arg}' is not allowed.")

    # De-dup while preserving order so repeated offenses don't spam the model.
    seen = set()
    deduped = []
    for v in violations:
        if v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped


# ---------------------------------------------------------------------------
# Layer 2: restricted execution namespace
# ---------------------------------------------------------------------------

# Only pure, side-effect-free builtins. Notably absent: open, eval, exec,
# compile, __import__, getattr/setattr, globals/locals, input, type, object.
_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "divmod": divmod, "enumerate": enumerate, "filter": filter, "float": float,
    "frozenset": frozenset, "int": int, "len": len, "list": list, "map": map,
    "max": max, "min": min, "print": print, "range": range, "repr": repr,
    "reversed": reversed, "round": round, "set": set, "slice": slice,
    "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "True": True, "False": False, "None": None, "abs": abs,
}


class _SafePandas:
    """A minimal ``pd`` shim exposing only safe, pure pandas helpers.

    The full pandas module is deliberately NOT exposed: ``pd.read_pickle`` /
    ``pd.read_csv`` / ``pd.read_sql`` / ``pd.eval`` are file/network/eval vectors.
    This shim carries just the constructors and elementwise helpers an analysis
    snippet legitimately needs.
    """

    DataFrame = staticmethod(pd.DataFrame)
    Series = staticmethod(pd.Series)
    concat = staticmethod(pd.concat)
    merge = staticmethod(pd.merge)
    to_numeric = staticmethod(pd.to_numeric)
    to_datetime = staticmethod(pd.to_datetime)
    cut = staticmethod(pd.cut)
    qcut = staticmethod(pd.qcut)
    isna = staticmethod(pd.isna)
    notna = staticmethod(pd.notna)
    pivot_table = staticmethod(pd.pivot_table)
    date_range = staticmethod(pd.date_range)
    NA = pd.NA
    NaT = pd.NaT


def _deep_copy_memory_value(val: Any) -> Any:
    """Recursively copy a recalled-memory value so a snippet can't mutate the store.

    A shallow ``dict(val)`` / ``list(val)`` still shares NESTED mutables (a list
    inside a dict, a DataFrame inside a list), so a snippet doing
    ``memory['x']['rows'].append(...)`` would corrupt what a future turn recalls.
    pandas objects get ``.copy()`` (deepcopy of a big frame is needlessly slow and
    .copy() already detaches the data); dict/list/tuple/set recurse; everything
    else is returned as-is (scalars are immutable).
    """
    if isinstance(val, (pd.DataFrame, pd.Series)):
        return val.copy()
    if isinstance(val, dict):
        return {k: _deep_copy_memory_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_deep_copy_memory_value(v) for v in val]
    if isinstance(val, tuple):
        return tuple(_deep_copy_memory_value(v) for v in val)
    if isinstance(val, set):
        return set(val)
    return val


def _build_namespace(df: pd.DataFrame,
                     memory: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # ``memory`` exposes named results from EARLIER analysis turns (the
    # XBE-Wizard ``_df_context`` pattern) so a later snippet can build on prior
    # work — e.g. ``result = memory['lax_breakdown'].head()``. The values are
    # prior snippet outputs (DataFrames/Series/scalars), so they add no new
    # external surface; they are DEEP-copied (incl. nested containers) so a
    # snippet can't mutate what a future turn will recall.
    safe_memory: Dict[str, Any] = {
        str(name): _deep_copy_memory_value(val)
        for name, val in (memory or {}).items()
    }
    return {
        "__builtins__": dict(_SAFE_BUILTINS),
        "df": df,
        "pd": _SafePandas(),
        "memory": safe_memory,
        "result": None,
    }


# ---------------------------------------------------------------------------
# Layer 4: defensive serialization of whatever the snippet produced
# ---------------------------------------------------------------------------

def _scalar(v: Any) -> Any:
    """Coerce a numpy/pandas scalar to a JSON-safe Python scalar."""
    if v is None:
        return None
    if isinstance(v, (bool, int, str)):
        return v
    # numpy b/ pandas scalars expose .item(); guard NaN/Inf which aren't JSON.
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 6)
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return _scalar(item())
        except (TypeError, ValueError):
            pass
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return str(v)


# How deep jsonify_result will descend into nested containers before bailing.
# Bounds both pathologically deep nesting AND self-referential cycles (a dict
# that contains itself) so serialization can never blow the stack.
_MAX_JSON_DEPTH = 12


def jsonify_result(result: Any, max_rows: int = DEFAULT_MAX_ROWS,
                   max_cells: int = DEFAULT_MAX_CELLS, _depth: int = 0) -> Dict[str, Any]:
    """Turn an arbitrary snippet result into a capped, JSON-serializable dict.

    ``_depth`` guards against self-referential / pathologically nested results:
    past ``_MAX_JSON_DEPTH`` the structure is summarized instead of recursed, so
    a snippet returning ``d={}; d['self']=d`` is serialized, never a stack blow-up.
    """
    if _depth >= _MAX_JSON_DEPTH:
        return {"type": "truncated", "note": "nesting too deep to serialize",
                "repr": _scalar(result)}
    if isinstance(result, pd.DataFrame):
        n_rows, n_cols = result.shape
        ncols = max(1, n_cols)
        row_cap = min(max_rows, max(1, max_cells // ncols))
        head = result.head(row_cap)
        records = [
            {str(c): _scalar(v) for c, v in row.items()}
            for _, row in head.iterrows()
        ]
        return {
            "type": "dataframe",
            "columns": [str(c) for c in result.columns],
            "row_count": int(n_rows),
            "rows_returned": len(records),
            "rows_omitted": int(max(0, n_rows - len(records))),
            "rows": records,
        }

    if isinstance(result, pd.Series):
        n = len(result)
        head = result.head(max_rows)
        return {
            "type": "series",
            "name": None if result.name is None else str(result.name),
            "length": int(n),
            "rows_returned": int(len(head)),
            "rows_omitted": int(max(0, n - len(head))),
            "data": [{"index": _scalar(idx), "value": _scalar(v)}
                     for idx, v in head.items()],
        }

    if isinstance(result, dict):
        items = list(result.items())[:max_rows]
        return {
            "type": "dict",
            "length": len(result),
            "rows_omitted": max(0, len(result) - len(items)),
            "data": {str(k): _scalar_or_nested(v, max_rows, _depth + 1) for k, v in items},
        }

    if isinstance(result, (list, tuple, set, frozenset)):
        seq = list(result)
        head = seq[:max_rows]
        return {
            "type": "list",
            "length": len(seq),
            "rows_omitted": max(0, len(seq) - len(head)),
            "data": [_scalar_or_nested(v, max_rows, _depth + 1) for v in head],
        }

    # Scalar / unknown.
    return {"type": "scalar", "value": _scalar(result)}


def _scalar_or_nested(v: Any, max_rows: int, _depth: int = 0) -> Any:
    """Used inside dict/list serialization: recurse with the depth guard carried."""
    if isinstance(v, (pd.DataFrame, pd.Series, dict, list, tuple, set, frozenset)):
        return jsonify_result(v, max_rows=min(max_rows, 50), _depth=_depth)
    return _scalar(v)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_sandboxed_code(
    df: Optional[pd.DataFrame],
    code: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cells: int = DEFAULT_MAX_CELLS,
    memory: Optional[Dict[str, Any]] = None,
    return_raw: bool = False,
) -> Dict[str, Any]:
    """Run an analysis snippet against a read-only copy of ``df``.

    Returns a dict that is always JSON-serializable and never raises on snippet
    input. On success: ``{"ok": True, "result": {...}, "stdout": "..."}``. On any
    failure (policy violation, snippet exception, timeout): ``{"ok": False,
    "error": ...}`` — plus ``"violations"`` for static-check failures.

    ``memory`` is an optional dict of named results from earlier turns, exposed to
    the snippet as a read-only ``memory`` dict (the multi-turn analysis-memory
    pattern). When ``return_raw`` is True the success payload also carries the
    *raw* result object under ``"raw"`` (not JSON-coerced) so the caller can store
    it in memory for a later turn to recall.
    """
    if df is None or len(df) == 0:
        return {"ok": False, "error": "No data is loaded. Upload GVT and Rate files first."}

    violations = check_code(code)
    if violations:
        return {
            "ok": False,
            "error": "Code rejected by the analysis sandbox policy.",
            "violations": violations,
        }

    # Layer 3: the snippet only ever sees a copy.
    namespace = _build_namespace(df.copy(), memory=memory)

    holder: Dict[str, Any] = {}
    stdout_buf = io.StringIO()

    def _target():
        try:
            compiled = compile(code, "<analysis>", "exec")
            with redirect_stdout(stdout_buf):
                exec(compiled, namespace)  # namespace carries restricted builtins
            holder["result"] = namespace.get("result")
            holder["ok"] = True
        except Exception as e:  # noqa: BLE001 — any snippet error is reported, not raised
            holder["ok"] = False
            holder["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        return {
            "ok": False,
            "error": (
                f"Analysis timed out after {timeout_s:g}s and was abandoned. "
                "Simplify the computation (avoid unbounded loops)."
            ),
        }

    stdout = stdout_buf.getvalue()
    if len(stdout) > MAX_STDOUT_CHARS:
        stdout = stdout[:MAX_STDOUT_CHARS] + "\n…[stdout truncated]"

    if not holder.get("ok"):
        out = {"ok": False, "error": holder.get("error", "Unknown execution error.")}
        if stdout.strip():
            out["stdout"] = stdout
        return out

    result = holder.get("result")
    if result is None:
        return {
            "ok": False,
            "error": ("The snippet ran but did not assign a `result` variable. "
                      "Assign your answer to `result` (a DataFrame, Series, "
                      "number, dict, or list)."),
            **({"stdout": stdout} if stdout.strip() else {}),
        }

    # Honour the "never raises" contract even if serialization hits something
    # pathological the depth-guard didn't anticipate (e.g. an object whose repr
    # itself throws). Fall back to a clean error dict rather than propagating.
    try:
        serialized = jsonify_result(result, max_rows=max_rows, max_cells=max_cells)
    except Exception as e:  # noqa: BLE001 — serialization must never escape
        out = {"ok": False,
               "error": f"Result could not be serialized ({type(e).__name__})."}
        if stdout.strip():
            out["stdout"] = stdout
        return out

    payload: Dict[str, Any] = {"ok": True, "result": serialized}
    if return_raw:
        # The un-coerced result, for the caller to stash in analysis memory.
        payload["raw"] = result
    if stdout.strip():
        payload["stdout"] = stdout
    return payload
