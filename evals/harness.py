"""Prompt-intent evaluation harness.

Runs each :class:`~evals.cases.IntentCase` through the *real* Bedrock Converse
tool-use loop (same ``BedrockChatClient`` + ``SYSTEM_PROMPT`` + ``TOOL_SPECS``
the dashboard uses), records every tool call the model made, and scores three
layers of intent-matching: tool routing, argument/scope, and final answer.

Usage
-----
    python -m evals.harness                 # run all cases, print a report
    python -m evals.harness --case flip_week32_to_atmi   # one case
    python -m evals.harness --json out.json # also dump structured results
    python -m evals.harness --repeat 3      # run each case N times (flakiness)

It needs Bedrock credentials (``.env`` — ``AWS_BEDROCK_API_KEY`` or
``AWS_accessKeyId``/``AWS_secretAccessKey``) and ``boto3`` installed. Without
credentials it exits early with a clear message rather than pretending to pass.

The harness is deliberately separate from the offline ``tests/`` suites: those
prove the pure tools are correct; this proves the *prompt* steers the model to
use them the way a user intends — the part you iterate on by editing
``SYSTEM_PROMPT`` / ``TOOL_SPECS`` and re-running.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

# The Windows console is often cp1252; model answers contain non-ASCII (smart
# quotes, bullets). Degrade unencodable chars instead of crashing the run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from dataclasses import dataclass, field
from typing import Any, List, Optional

# Sibling modules import streamlit at package-import time; mock it before they load.
from unittest.mock import MagicMock
sys.modules.setdefault("streamlit", MagicMock())
import streamlit as _st  # noqa: E402

# A bare MagicMock returns truthy mocks for st.secrets.get(<key>), which the
# bedrock client's _load_streamlit_secrets() would copy into os.environ and
# poison AWS_REGION (resolving it to a MagicMock string -> InvalidRegionError).
# A real empty dict makes secrets look "unconfigured", so region/creds resolve
# from tests/.env exactly as in a local run.
_st.secrets = {}


class _SessionState(dict):
    """Dict that also supports attribute access, like st.session_state.

    The constraint tools in ``chat_ui._make_tool_executor`` both ``.get(...)``
    and attribute-assign on session state; a bare MagicMock would silently
    accept attribute writes but return MagicMocks on reads. A real dict-backed
    object makes the ``generate_constraints`` path behave exactly as in the app.
    """
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


# Give the executor a clean, realistic session state before each run.
_st.session_state = _SessionState()

from components.chatbot.bedrock_client import BedrockChatClient, BedrockClientError
import components.chatbot.chat_ui as _chat_ui
from components.chatbot.chat_ui import _make_tool_executor
from components.chatbot.tool_specs import SYSTEM_PROMPT, TOOL_SPECS

from . import cases as C
from . import fixture as F


# ===========================================================================
# scoring
# ===========================================================================

@dataclass
class CheckResult:
    label: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    prompt: str
    intent: str
    answer: str
    tool_calls: List[dict]
    checks: List[CheckResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)

    @property
    def tools_used(self) -> List[str]:
        return [c.get("name") for c in self.tool_calls]


def _contains(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def score_case(case: "C.IntentCase", answer: str, tool_calls: List[dict],
               error: Optional[str]) -> CaseResult:
    """Apply all of a case's checks against one run's answer + tool calls."""
    res = CaseResult(case_id=case.id, prompt=case.prompt, intent=case.intent,
                     answer=answer, tool_calls=tool_calls, error=error)
    if error:
        res.checks.append(CheckResult("run completed", False, error))
        return res

    used = [c.get("name") for c in tool_calls]

    # ---- tool routing ----
    for t in case.expect_tools:
        res.checks.append(CheckResult(
            f"called tool '{t}'", t in used,
            "" if t in used else f"tools used: {used or 'none'}"))
    if case.expect_any_tool:
        ok = any(t in used for t in case.expect_any_tool)
        res.checks.append(CheckResult(
            f"called one of {case.expect_any_tool}", ok,
            "" if ok else f"tools used: {used or 'none'}"))
    for t in case.forbid_tools:
        res.checks.append(CheckResult(
            f"did NOT call '{t}'", t not in used,
            "" if t not in used else f"forbidden tool was called"))

    # ---- argument / scope predicates ----
    for label, pred in case.arg_checks:
        try:
            ok = bool(pred(tool_calls))
            detail = "" if ok else "predicate false"
        except Exception as e:  # a predicate must never crash the harness
            ok, detail = False, f"predicate raised: {e}"
        res.checks.append(CheckResult(f"arg: {label}", ok, detail))

    # ---- final answer ----
    for s in case.answer_contains:
        res.checks.append(CheckResult(
            f"answer contains '{s}'", _contains(answer, s),
            "" if _contains(answer, s) else "missing"))
    if case.answer_contains_any:
        ok = any(_contains(answer, s) for s in case.answer_contains_any)
        res.checks.append(CheckResult(
            f"answer contains any of {case.answer_contains_any}", ok,
            "" if ok else "none present"))
    for s in case.answer_not_contains:
        ok = not _contains(answer, s)
        res.checks.append(CheckResult(
            f"answer does NOT contain '{s}'", ok,
            "" if ok else "forbidden phrase present"))
    if case.answer_regex:
        import re
        ok = bool(re.search(case.answer_regex, answer, re.IGNORECASE))
        res.checks.append(CheckResult(
            f"answer matches /{case.answer_regex}/", ok,
            "" if ok else "no regex match"))
    if case.answer_predicate:
        try:
            ok = bool(case.answer_predicate(answer))
        except Exception as e:
            ok = False
        res.checks.append(CheckResult("answer predicate", ok))

    return res


# ===========================================================================
# running
# ===========================================================================

def run_case(client: BedrockChatClient, case: "C.IntentCase",
             working_data, rate_data, rate_type: str = "Base Rate",
             max_iterations: int = 6) -> CaseResult:
    """Drive one case through the real tool-use loop and score it."""
    # Fresh session state per case so staged constraints never leak between runs.
    state = _SessionState()
    _st.session_state = state
    # Seed any state a tool reads (e.g. chatbot_constraint_summary), applied after
    # the reset so it does not leak into other cases.
    for k, v in (case.seed_session_state or {}).items():
        state[k] = v
    # The executor reads chat_ui's OWN `st` reference. Under the full test suite,
    # another module can have reassigned sys.modules['streamlit'], leaving
    # chat_ui.st a different object than this module's `_st` — so install the same
    # state object there too, or a seeded tool (read_constraints_summary) would
    # read an empty session. Mirrors the cross-module gotcha in evals/README.
    _chat_ui.st.session_state = state
    # Wrap the real executor so we capture the tool calls the model makes.
    base_executor = _make_tool_executor(working_data, rate_data, rate_type)
    captured: List[dict] = []

    def recording_executor(name: str, tool_input: dict):
        result, is_error = base_executor(name, tool_input)
        captured.append({"name": name, "input": tool_input,
                         "result": result, "is_error": is_error})
        return result, is_error

    # First user turn, then any follow-ups reusing the rebuilt transcript so the
    # model carries context across turns (e.g. "apply it" after a draft). Tool
    # calls accumulate in `captured`; only the LAST turn's text is scored.
    turns = [case.prompt, *(case.followups or [])]
    messages = [{"role": "user", "content": [{"text": turns[0]}]}]
    answer = ""
    try:
        for i, turn in enumerate(turns):
            if i > 0:
                messages.append({"role": "user", "content": [{"text": turn}]})
            out = client.run_conversation(
                messages=messages, system=SYSTEM_PROMPT, tool_specs=TOOL_SPECS,
                tool_executor=recording_executor, max_iterations=max_iterations,
            )
            messages = out.get("messages", messages)
            answer = out.get("text", "")
        return score_case(case, answer, captured, error=None)
    except BedrockClientError as e:
        return score_case(case, "", captured, error=f"Bedrock error: {e}")
    except Exception as e:  # pragma: no cover - defensive
        return score_case(case, "", captured, error=f"Unexpected: {e}")


def run_all(case_filter: Optional[str] = None, repeat: int = 1,
            verbose: bool = True) -> List[CaseResult]:
    client = BedrockChatClient()
    if not client.has_credentials:
        print("ERROR: No Bedrock credentials found. Add AWS_BEDROCK_API_KEY (or "
              "AWS_accessKeyId / AWS_secretAccessKey) to .env.")
        sys.exit(2)

    wd, rd = F.working_data(), F.rate_data()
    selected = [c for c in C.all_cases()
                if case_filter is None or c.id == case_filter]
    if not selected:
        print(f"ERROR: No case matches id '{case_filter}'.")
        sys.exit(2)

    if verbose:
        print(f"Model: {client.model_id}  |  Region: {client.region}")
        print(f"Running {len(selected)} case(s) x {repeat} -> "
              f"{len(selected) * repeat} call(s)\n")

    results: List[CaseResult] = []
    for case in selected:
        for i in range(repeat):
            t0 = time.time()
            r = run_case(client, case, wd, rd)
            dt = time.time() - t0
            results.append(r)
            if verbose:
                _print_case(r, dt, run_idx=i if repeat > 1 else None)
    return results


# ===========================================================================
# reporting
# ===========================================================================

def _print_case(r: CaseResult, dt: float, run_idx: Optional[int] = None):
    tag = f"[{r.case_id}]" + (f" run {run_idx + 1}" if run_idx is not None else "")
    status = "PASS" if r.passed else "FAIL"
    print(f"[{status}] {tag}  ({dt:.1f}s)")
    print(f"    intent : {r.intent}")
    print(f"    tools  : {r.tools_used or 'none'}")
    if not r.passed:
        for ch in r.checks:
            if not ch.passed:
                extra = f" - {ch.detail}" if ch.detail else ""
                print(f"      x {ch.label}{extra}")
        ans = (r.answer or "").replace("\n", " ")
        if len(ans) > 240:
            ans = ans[:240] + "…"
        print(f"    answer : {ans or '(empty)'}")
    print()


def summarize(results: List[CaseResult]) -> dict:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    # Per-case aggregation (useful when --repeat > 1).
    by_case: dict = {}
    for r in results:
        by_case.setdefault(r.case_id, []).append(r.passed)
    return {
        "passed": passed, "total": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_case": {cid: f"{sum(v)}/{len(v)}" for cid, v in by_case.items()},
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Tender Assistant prompt-intent eval harness")
    ap.add_argument("--case", help="run a single case by id")
    ap.add_argument("--repeat", type=int, default=1, help="runs per case (flakiness check)")
    ap.add_argument("--json", help="write structured results to this path")
    ap.add_argument("--quiet", action="store_true", help="suppress per-case output")
    args = ap.parse_args(argv)

    results = run_all(case_filter=args.case, repeat=args.repeat, verbose=not args.quiet)
    summary = summarize(results)

    print("=" * 60)
    print(f"RESULT: {summary['passed']}/{summary['total']} checks-passing runs "
          f"({summary['pass_rate'] * 100:.0f}%)")
    if args.repeat > 1:
        for cid, ratio in summary["by_case"].items():
            print(f"  {cid}: {ratio}")

    if args.json:
        payload = {
            "summary": summary,
            "results": [
                {
                    "case_id": r.case_id, "prompt": r.prompt, "intent": r.intent,
                    "passed": r.passed, "tools_used": r.tools_used,
                    "answer": r.answer, "error": r.error,
                    "tool_calls": [{"name": c["name"], "input": c["input"]}
                                   for c in r.tool_calls],
                    "failed_checks": [
                        {"label": ch.label, "detail": ch.detail}
                        for ch in r.checks if not ch.passed
                    ],
                }
                for r in results
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nWrote structured results to {args.json}")

    # Exit non-zero if any run failed, so this can gate CI / a loop.
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
