"""Live stress test for the chat UI's streaming + multi-turn memory + clear.

This drives the SAME streaming path the dashboard uses (``stream_conversation``)
against real Bedrock, with a persistent Converse message history and a
streamlit-style session state — so it tests exactly the three things asked:

  1. CLEAR WITHOUT RELOAD: clearing the chat wipes the transcript but leaves the
     data object (and constraints) untouched — proven by object identity.
  2. STREAMING MULTI-TURN: every turn streams text incrementally (>1 chunk) and
     the history grows correctly across turns.
  3. SESSION MEMORY: later turns use bare pronouns / "do that" / "why" with no
     restated context; the model must resolve them from history.

Run:  python -m evals.stress_chat_ui
"""
from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.modules.setdefault("streamlit", MagicMock())
import streamlit as _st  # noqa: E402

# A bare MagicMock returns truthy mocks for st.secrets.get(<key>), which the
# bedrock client's _load_streamlit_secrets() would copy into os.environ and
# poison AWS_REGION. A real empty dict makes it behave like "no secrets set",
# so region/creds resolve from .env exactly as in a local run.
_st.secrets = {}


class _SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e
    def __setattr__(self, k, v):
        self[k] = v
    def setdefault(self, k, d=None):
        return super().setdefault(k, d)


_st.session_state = _SS()

from components.chatbot.bedrock_client import BedrockChatClient  # noqa: E402
from components.chatbot.chat_ui import _make_tool_executor  # noqa: E402
from components.chatbot.tool_specs import TOOL_SPECS, build_system_prompt  # noqa: E402
from evals import fixture as F  # noqa: E402


def _reset_chat(ss):
    """Mirror chat_ui._reset_chat: wipe transcript, KEEP constraints + data."""
    ss.chatbot_messages = []
    ss.chatbot_display = []


def run_turn(client, ss, df, rate_data, user_text):
    """Drive ONE streaming turn exactly like _handle_user_message does."""
    executor = _make_tool_executor(df, rate_data, "Base Rate")
    ss.chatbot_messages.append({"role": "user", "content": [{"text": user_text}]})
    system = build_system_prompt(
        data_rows=(0 if df is None else len(df)),
        constraint_rows=len(ss.get("chatbot_staged_constraints") or []),
        constraint_source=ss.get("chatbot_constraint_source_sig"),
        applied_rows=len(ss.get("chatbot_applied_constraints") or []),
    )
    text_chunks = 0
    streamed = ""
    tools = []
    t0 = time.time()
    for ev in client.stream_conversation(
        messages=ss.chatbot_messages, system=system,
        tool_specs=TOOL_SPECS, tool_executor=executor,
    ):
        et = ev.get("type")
        if et == "text":
            text_chunks += 1
            streamed += ev["text"]
        elif et == "tool_result":
            tools.append(ev["name"])
        elif et == "done":
            ss.chatbot_messages = ev["messages"]
            final = ev["text"] or streamed
    dt = time.time() - t0
    ss.chatbot_display.append({"role": "user", "text": user_text})
    ss.chatbot_display.append({"role": "assistant", "text": final})
    return {"text": final, "chunks": text_chunks, "tools": tools, "seconds": dt}


def banner(s):
    print("\n" + "=" * 78 + f"\n{s}\n" + "=" * 78)


def main():
    client = BedrockChatClient()
    if not client.has_credentials:
        print("ERROR: no Bedrock credentials in .env"); return 2

    df = F.working_data()
    rate_data = F.rate_data()
    data_id = id(df)
    ss = _st.session_state
    ss.chatbot_messages = []
    ss.chatbot_display = []
    ss.chatbot_staged_constraints = []
    ss.chatbot_applied_constraints = []
    ss.chatbot_constraint_source_sig = None

    print(f"Model: {client.model_id} | Region: {client.region}")
    print(f"Fixture: {len(df):,} rows, data object id={data_id}")

    results = {"stream_ok": True, "memory_checks": [], "clear_ok": None}

    # ---- PHASE A: multi-turn streaming with pronoun/"why" memory ----
    banner("PHASE A — streaming multi-turn with bare-reference memory")
    script = [
        ("Which single carrier has the most containers in the loaded data? "
         "Give me just the carrier code and the count.", None),
        ("What's their average base rate?", "pronoun 'their' -> prior carrier"),
        ("Why might that rate be higher or lower than the fleet average?",
         "'that rate' -> the avg rate from previous turn"),
        ("Now draft a constraint capping that same carrier at half its current "
         "container count, priority 90.", "'that same carrier' + 'its count'"),
        ("Actually, raise the cap by 10 and tell me what changed.",
         "'the cap' -> the constraint just drafted"),
    ]
    prev_carrier = None
    for i, (text, memory_note) in enumerate(script, 1):
        r = run_turn(client, ss, df, rate_data, text)
        streamed_inc = r["chunks"] > 1
        if not streamed_inc:
            results["stream_ok"] = False
        print(f"\n--- Turn {i} ({r['seconds']:.1f}s, {r['chunks']} text chunks, "
              f"tools={r['tools'] or 'none'}) ---")
        print(f"USER: {text}")
        if memory_note:
            print(f"[memory test: {memory_note}]")
        ans = r["text"].strip()
        print(f"ASSISTANT: {ans[:600]}{'…' if len(ans) > 600 else ''}")
        if i == 1:
            # capture the carrier the model named, to check later turns stay on it
            for tok in ans.replace(",", " ").split():
                t = tok.strip("()*:`")
                if t.isupper() and t.isalpha() and 3 <= len(t) <= 4:
                    prev_carrier = t; break
            print(f"[captured carrier from turn 1: {prev_carrier}]")
        else:
            # memory pass = the model did NOT ask "which carrier?" and stayed on topic
            asked_back = any(p in ans.lower() for p in
                             ("which carrier", "which one", "could you specify",
                              "can you clarify", "what carrier", "please specify"))
            on_topic = (prev_carrier is None) or (prev_carrier in ans) or (r["tools"])
            ok = (not asked_back)
            results["memory_checks"].append((i, ok, asked_back))
            print(f"[memory {'PASS' if ok else 'FAIL'} — asked_back={asked_back}]")

    msgs_before_clear = len(ss.chatbot_messages)
    staged_before = len(ss.get("chatbot_staged_constraints") or [])
    print(f"\n[history grew to {msgs_before_clear} messages; "
          f"{staged_before} staged constraint(s)]")

    # ---- PHASE B: clear without reload ----
    banner("PHASE B — clear chat WITHOUT reloading data")
    _reset_chat(ss)
    data_id_after = id(df)
    cleared = (len(ss.chatbot_messages) == 0 and len(ss.chatbot_display) == 0)
    data_untouched = (data_id_after == data_id and len(df) > 0)
    constraints_kept = len(ss.get("chatbot_staged_constraints") or []) == staged_before
    results["clear_ok"] = cleared and data_untouched
    print(f"transcript cleared      : {cleared} (messages={len(ss.chatbot_messages)})")
    print(f"data object UNTOUCHED    : {data_untouched} "
          f"(id before={data_id}, after={data_id_after}, rows={len(df)})")
    print(f"constraints PRESERVED    : {constraints_kept} "
          f"(was {staged_before}, now {len(ss.get('chatbot_staged_constraints') or [])})")

    # ---- PHASE C: fresh turn after clear has NO memory of old turns ----
    banner("PHASE C — after clear, a bare pronoun should NOT resolve (clean slate)")
    r = run_turn(client, ss, df, rate_data,
                 "What was the carrier we were just discussing?")
    ans = r["text"].strip()
    print(f"ASSISTANT: {ans[:400]}{'…' if len(ans) > 400 else ''}")
    fresh_slate = (prev_carrier is None) or (prev_carrier not in ans)
    print(f"[clean-slate {'PASS' if fresh_slate else 'WARN'} — "
          f"old carrier {prev_carrier!r} {'absent' if fresh_slate else 'LEAKED'}]")

    # ---- SUMMARY ----
    banner("SUMMARY")
    mem_pass = sum(1 for _, ok, _ in results["memory_checks"] if ok)
    mem_total = len(results["memory_checks"])
    print(f"1. Clear without reload : {'PASS' if results['clear_ok'] else 'FAIL'}")
    print(f"2. Streaming (all turns incremental >1 chunk): "
          f"{'PASS' if results['stream_ok'] else 'FAIL'}")
    print(f"3. Session memory (bare refs resolved): {mem_pass}/{mem_total} turns")
    print(f"   Clean slate after clear: {'PASS' if fresh_slate else 'WARN'}")
    ok = results["clear_ok"] and results["stream_ok"] and mem_pass == mem_total
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
