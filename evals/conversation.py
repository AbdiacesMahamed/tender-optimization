"""Multi-turn conversation driver for the Tender Optimization Assistant.

Where ``evals.harness`` scores *single-turn* prompt-intent cases, this drives a
*stateful, multi-turn* session against the real Bedrock Converse loop — the same
``BedrockChatClient`` / ``SYSTEM_PROMPT`` / ``TOOL_SPECS`` the dashboard uses —
so you can watch the assistant generate constraints from a hypothetical upload
and then *edit them over several turns*, exactly as a port manager would in the
sidebar.

It is also a **timing probe**: every turn records wall-clock split into model
time vs tool time, and every tool call is timed individually. That data is what
tells us which operations are slow enough to be worth caching or pre-computing
into reusable tools for future runs.

Usage
-----
    python -m evals.conversation                 # default generate->edit script
    python -m evals.conversation --seed-upload    # start from an uploaded file
    python -m evals.conversation --json out.json  # dump full structured trace
    python -m evals.conversation --quiet          # timing summary only

It needs Bedrock credentials (``.env``) and ``boto3``. Without them it
exits early rather than faking a run.

Reusing the engine
-------------------
``Conversation`` is importable and scriptable:

    convo = Conversation(working_data=df, rate_data=rd)
    convo.seed_uploaded_constraints(constraint_df)   # optional
    turn = convo.send("Cap RKNE at 50 for NYC, high priority.")
    print(turn.answer, turn.tools_used, turn.seconds)
    convo.send("Actually make it 40 and add a 90% floor for ABCD on BAL.")
    print(convo.staged_constraints())               # current working set
    convo.print_timing_report()
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

# The Windows console is often cp1252; model answers carry smart quotes/bullets.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Sibling modules import streamlit at import time; mock it before they load.
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
    """Dict with attribute access, mirroring st.session_state.

    The constraint tools in ``chat_ui._make_tool_executor`` both ``.get(...)``
    and attribute-assign on session state, so a plain MagicMock would silently
    swallow writes. A real dict-backed object makes the generate/edit path
    behave exactly as it does in the live app — and persists across turns.
    """
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


_st.session_state = _SessionState()

from components.chatbot.bedrock_client import BedrockChatClient, BedrockClientError  # noqa: E402
from components.chatbot.chat_ui import _make_tool_executor  # noqa: E402
from components.chatbot.tool_specs import SYSTEM_PROMPT, TOOL_SPECS  # noqa: E402
from components.chatbot import tools as T  # noqa: E402

from . import fixture as F  # noqa: E402


# ===========================================================================
# records
# ===========================================================================

@dataclass
class ToolEvent:
    name: str
    input: dict
    result: Any
    is_error: bool
    seconds: float


@dataclass
class Turn:
    index: int
    user: str
    answer: str
    tool_events: List[ToolEvent] = field(default_factory=list)
    seconds: float = 0.0          # total wall-clock for the turn
    model_calls: int = 0          # Bedrock round-trips this turn (the cost driver)
    error: Optional[str] = None

    @property
    def tools_used(self) -> List[str]:
        return [e.name for e in self.tool_events]

    @property
    def tool_seconds(self) -> float:
        return sum(e.seconds for e in self.tool_events)

    @property
    def model_seconds(self) -> float:
        # Everything not spent inside a tool handler is model + transport time.
        return max(0.0, self.seconds - self.tool_seconds)


# ===========================================================================
# the driver
# ===========================================================================

class Conversation:
    """A stateful multi-turn session against the real assistant loop.

    Holds the Converse message history AND the streamlit-style session state
    (so staged constraints persist across turns, exactly like the sidebar). Each
    :meth:`send` runs one user turn through the real ``run_conversation`` loop,
    records every tool call with its individual timing, and returns a
    :class:`Turn`.
    """

    def __init__(self, working_data=None, rate_data=None, rate_type: str = "Base Rate",
                 client: Optional[BedrockChatClient] = None, max_iterations: int = 8):
        self.working_data = F.working_data() if working_data is None else working_data
        self.rate_data = F.rate_data() if rate_data is None else rate_data
        self.rate_type = rate_type
        self.client = client or BedrockChatClient()
        self.max_iterations = max_iterations

        # Persistent across the whole conversation.
        self.session_state = _SessionState()
        self.messages: List[dict] = []
        self.turns: List[Turn] = []

    # ---- working-set helpers ----------------------------------------------

    def seed_uploaded_constraints(self, constraint_df) -> int:
        """Pre-load constraints into the working set as if a file was uploaded.

        Mirrors ``chat_ui._seed_working_set_from_df`` so the assistant sees the
        same 'uploaded' rows (origin tag included) it would in the app.
        """
        valid = self._valid_carriers()
        rows = T.constraints_from_dataframe(
            constraint_df, origin="uploaded", valid_carriers=valid or None
        )
        self.session_state.chatbot_staged_constraints = rows
        self.session_state.chatbot_constraint_source_sig = "seed:hypothetical_upload"
        return len(rows)

    def staged_constraints(self) -> List[dict]:
        return list(self.session_state.get("chatbot_staged_constraints") or [])

    def _valid_carriers(self) -> set:
        df = self.working_data
        if df is None or len(df) == 0 or "Dray SCAC(FL)" not in df.columns:
            return set()
        return {str(c).strip() for c in df["Dray SCAC(FL)"].dropna().unique()}

    # ---- the core loop -----------------------------------------------------

    def send(self, user_text: str) -> Turn:
        """Run one user turn and return its :class:`Turn` record."""
        # Bind the session state the executor reads/writes to OUR persistent one,
        # so staged constraints survive between turns.
        _st.session_state = self.session_state

        base_executor = _make_tool_executor(
            self.working_data, self.rate_data, self.rate_type
        )
        events: List[ToolEvent] = []

        def timing_executor(name: str, tool_input: dict):
            t0 = time.time()
            result, is_error = base_executor(name, tool_input)
            dt = time.time() - t0
            events.append(ToolEvent(name=name, input=tool_input, result=result,
                                    is_error=is_error, seconds=dt))
            return result, is_error

        # Count Bedrock round-trips this turn — the real cost driver, since each
        # sequential tool call forces another full model call. Wrap converse().
        call_counter = {"n": 0}
        real_converse = self.client.converse

        def counting_converse(*a, **kw):
            call_counter["n"] += 1
            return real_converse(*a, **kw)

        self.messages.append({"role": "user", "content": [{"text": user_text}]})
        turn = Turn(index=len(self.turns) + 1, user=user_text, answer="")
        t0 = time.time()
        try:
            self.client.converse = counting_converse
            out = self.client.run_conversation(
                messages=self.messages, system=SYSTEM_PROMPT, tool_specs=TOOL_SPECS,
                tool_executor=timing_executor, max_iterations=self.max_iterations,
            )
            turn.answer = out.get("text", "")
            self.messages = out["messages"]
        except BedrockClientError as e:
            turn.error = f"Bedrock error: {e}"
        except Exception as e:  # pragma: no cover - defensive
            turn.error = f"Unexpected: {e}"
        finally:
            self.client.converse = real_converse
        turn.seconds = time.time() - t0
        turn.model_calls = call_counter["n"]
        turn.tool_events = events
        self.turns.append(turn)
        return turn

    # ---- reporting ---------------------------------------------------------

    def print_turn(self, turn: Turn, verbose: bool = True) -> None:
        print(f"\n{'─' * 70}")
        print(f"TURN {turn.index}  ({turn.seconds:.1f}s "
              f"= model {turn.model_seconds:.1f}s + tools {turn.tool_seconds:.1f}s"
              f"  |  {turn.model_calls} model round-trip(s))")
        print(f"  USER : {turn.user}")
        if turn.error:
            print(f"  ERROR: {turn.error}")
            return
        if turn.tool_events:
            print(f"  TOOLS:")
            for e in turn.tool_events:
                flag = " [ERROR]" if e.is_error else ""
                summary = _short_tool_summary(e)
                print(f"    • {e.name} ({e.seconds * 1000:.0f}ms){flag}  {summary}")
        else:
            print(f"  TOOLS: none")
        ans = (turn.answer or "").strip()
        if not verbose and len(ans) > 400:
            ans = ans[:400] + "…"
        print(f"  ASSISTANT:\n{_indent(ans or '(empty)', 4)}")

    def print_timing_report(self) -> None:
        print(f"\n{'=' * 70}")
        print("TIMING REPORT")
        print(f"  Model: {self.client.model_id}  |  Region: {self.client.region}")
        total = sum(t.seconds for t in self.turns)
        tool_total = sum(t.tool_seconds for t in self.turns)
        model_total = max(0.0, total - tool_total)
        rt_total = sum(t.model_calls for t in self.turns)
        print(f"  Turns: {len(self.turns)}  |  Total: {total:.1f}s  "
              f"(model {model_total:.1f}s, tools {tool_total:.1f}s)")
        if self.turns:
            print(f"  Avg/turn: {total / len(self.turns):.1f}s  |  "
                  f"Slowest turn: {max(t.seconds for t in self.turns):.1f}s")
            print(f"  Model round-trips: {rt_total} total, "
                  f"{rt_total / len(self.turns):.1f}/turn  "
                  f"(~{model_total / rt_total:.1f}s each)"
                  if rt_total else "")
            print("  → Latency is ~100% model round-trips; tool code is "
                  "negligible. Fewer round-trips/turn = faster, not faster tools.")

        # Per-tool aggregate — the data that tells us what's worth caching.
        agg: dict = {}
        for t in self.turns:
            for e in t.tool_events:
                a = agg.setdefault(e.name, {"calls": 0, "seconds": 0.0, "errors": 0})
                a["calls"] += 1
                a["seconds"] += e.seconds
                a["errors"] += int(e.is_error)
        if agg:
            print(f"\n  {'tool':<28}{'calls':>6}{'total_s':>10}{'avg_ms':>10}{'errors':>8}")
            for name, a in sorted(agg.items(), key=lambda kv: -kv[1]["seconds"]):
                avg_ms = (a["seconds"] / a["calls"] * 1000) if a["calls"] else 0
                print(f"  {name:<28}{a['calls']:>6}{a['seconds']:>10.2f}"
                      f"{avg_ms:>10.0f}{a['errors']:>8}")

    def to_dict(self) -> dict:
        return {
            "model": self.client.model_id,
            "region": self.client.region,
            "turns": [
                {
                    "index": t.index, "user": t.user, "answer": t.answer,
                    "seconds": round(t.seconds, 3),
                    "model_seconds": round(t.model_seconds, 3),
                    "tool_seconds": round(t.tool_seconds, 3),
                    "model_calls": t.model_calls,
                    "error": t.error,
                    "tools": [
                        {"name": e.name, "input": e.input, "is_error": e.is_error,
                         "seconds": round(e.seconds, 4),
                         "result": _json_safe(e.result)}
                        for e in t.tool_events
                    ],
                }
                for t in self.turns
            ],
            "final_staged_constraints": [
                {k: _json_safe(v) for k, v in c.items()}
                for c in self.staged_constraints()
            ],
        }


# ===========================================================================
# helpers
# ===========================================================================

def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.splitlines())


def _json_safe(v):
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


def _short_tool_summary(e: ToolEvent) -> str:
    """One-line gist of what a tool call did, for the transcript."""
    r = e.result if isinstance(e.result, dict) else {}
    if e.name in ("generate_constraints", "edit_constraints"):
        n = len(r.get("constraints", []) or [])
        valid = r.get("valid_count")
        applied = r.get("applied")
        bits = [f"working set={n}"]
        if valid is not None:
            bits.append(f"valid={valid}")
        if applied is not None:
            bits.append(f"applied={applied}")
        if r.get("errors"):
            bits.append(f"errors={len(r['errors'])}")
        if "working_set" in r:  # composite: scope counts folded in
            counts = [w.get("scope_containers") for w in r["working_set"]
                      if w.get("scope_containers") is not None]
            if counts:
                bits.append(f"scope_counts={counts}")
        return ", ".join(bits)
    if e.name == "describe_constraints":
        return f"count={r.get('count')}"
    if e.name == "analyze_data":
        inp = e.input or {}
        return f"query={inp.get('query_type')}"
    if e.name == "preview_constraint_scope":
        return f"matched={r.get('matched_containers')}"
    if e.name == "simulate_flip":
        return (f"delta={r.get('cost_delta')}, "
                f"unrated={r.get('unrated_containers')}")
    return ""


# ===========================================================================
# default scenario + ground-truth upload
# ===========================================================================

def hypothetical_upload_df():
    """A small, deliberately-imperfect constraint file to upload and then edit.

    Two rules, both referencing carriers that exist in the fixture data, so the
    assistant can describe them, reason about scope, and edit them on request:
      1. Cap RKNE at 100 containers, priority 80.
      2. Give ABCD at least 1 container on the BAL/HGR6 lane, priority 60.
    """
    import pandas as pd
    return pd.DataFrame([
        {"Priority Score": 80, "Carrier": "RKNE", "Port": "NYC",
         "Maximum Container Count": 100},
        {"Priority Score": 60, "Carrier": "ABCD", "Lane": "USBALHGR6",
         "Minimum Container Count": 1},
    ])


def default_script(seed_upload: bool) -> List[str]:
    """The turns to drive. Generate-then-edit, optionally from an upload."""
    if seed_upload:
        return [
            "What constraints are currently loaded? Summarize each one.",
            "Change the RKNE NYC cap to 50 containers and bump its priority to 95.",
            "Add a new rule: ABCD must get at least 30% of the BAL HGR6 lane, "
            "priority 70. Before you draft it, check how many containers that "
            "lane has.",
            "Drop the ABCD minimum-count rule — the percent rule replaces it. "
            "Then show me the final set.",
        ]
    return [
        "Give me an overview of the loaded data — carriers, lanes, weeks, total "
        "containers.",
        "I want RKNE capped at 50 containers for the NYC port at high priority. "
        "Draft that constraint.",
        "Good. Now also cap HJBT at 1 container on the NYC ABE8 lane, priority "
        "85, and add a rule giving ABCD at least 30% of the Baltimore HGR6 lane.",
        "Actually raise the RKNE cap to 60 and delete the HJBT rule. Then show "
        "me the final constraint set.",
    ]


# ===========================================================================
# main
# ===========================================================================

def run_script(script: List[str], seed_upload: bool = False,
               verbose: bool = True) -> Conversation:
    client = BedrockChatClient()
    if not client.has_credentials:
        print("ERROR: No Bedrock credentials found. Add AWS_BEDROCK_API_KEY (or "
              "AWS_accessKeyId / AWS_secretAccessKey) to .env.")
        sys.exit(2)

    convo = Conversation(client=client)
    if seed_upload:
        n = convo.seed_uploaded_constraints(hypothetical_upload_df())
        print(f"Seeded {n} constraint(s) from a hypothetical upload.\n")

    if verbose:
        print(f"Model: {client.model_id}  |  Region: {client.region}")
        print(f"Driving {len(script)} turn(s)…")

    for text in script:
        turn = convo.send(text)
        if verbose:
            convo.print_turn(turn, verbose=verbose)
        if turn.error:
            break

    convo.print_timing_report()
    return convo


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Multi-turn conversation + timing probe for the Tender Assistant")
    ap.add_argument("--seed-upload", action="store_true",
                    help="start from a hypothetical uploaded constraint file")
    ap.add_argument("--json", help="write the full structured trace to this path")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-turn transcript (timing summary only)")
    args = ap.parse_args(argv)

    convo = run_script(default_script(args.seed_upload),
                       seed_upload=args.seed_upload, verbose=not args.quiet)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(convo.to_dict(), fh, indent=2)
        print(f"\nWrote structured trace to {args.json}")

    # Non-zero if any turn errored, so this can gate a loop.
    return 0 if all(t.error is None for t in convo.turns) else 1


if __name__ == "__main__":
    sys.exit(main())
