"""
Sidebar chat UI for the Tender Optimization Assistant.

Renders a persistent chat panel in the Streamlit sidebar, drives the Bedrock
Converse tool-use loop, and stages assistant-proposed constraints so the user
can review them in an editable table, Apply them to the live optimization, or
Download them as an Excel file matching the constraint template.

Session-state keys owned by this module:
  - chatbot_messages: Converse-format message history (LLM transcript)
  - chatbot_display: list of {role, text} for rendering the chat bubbles
  - chatbot_staged_constraints: the working set of constraints (uploaded + drafted)
  - chatbot_applied_constraints: list applied into the optimization pipeline
  - chatbot_constraint_source_sig: signature of the constraint file already seeded
    into the working set, so an upload is loaded exactly once (not on every rerun)

Session-state keys this module READS but does not own:
  - chatbot_constraint_summary: the Applied Constraints Summary (per-rule outcome
    list) the dashboard writes each run; read by the read_constraints_summary tool.
"""
from __future__ import annotations

import logging
import re

import pandas as pd
import streamlit as st

from .bedrock_client import BedrockChatClient, BedrockClientError
from .tool_specs import SYSTEM_PROMPT, TOOL_SPECS, build_system_prompt
from .execution_logger import ExecutionLogger
from . import tools as T

logger = logging.getLogger(__name__)

# Marker the model emits before its suggested follow-ups (see SUGGESTED FOLLOW-UPS
# in the system prompt). Everything after it is parsed into clickable pills and
# stripped from the displayed answer. ``<<<`` never collides with markdown.
_FOLLOWUP_MARKER = "<<<FOLLOWUPS>>>"
_MAX_FOLLOWUPS = 4

# Shown when the chat is empty, to seed the conversation with one click. Generic
# (no data loaded yet) on purpose; once a turn happens the model proposes
# context-specific follow-ups instead.
_STARTER_PROMPTS = [
    "Give me an overview of the loaded data",
    "Which lanes are most expensive?",
    "Where can I save money on carrier costs?",
    "Audit my rate coverage",
]


def _split_followups(text: str):
    """Split an assistant reply into (visible_text, [follow-up suggestions]).

    The model appends a ``<<<FOLLOWUPS>>>`` block of one-per-line next steps. We
    strip that block from what the user reads and return the lines as pills. If
    the marker is absent, returns the text unchanged and an empty list.
    """
    if not text or _FOLLOWUP_MARKER not in text:
        return text, []
    body, _, tail = text.partition(_FOLLOWUP_MARKER)
    suggestions = []
    for line in tail.splitlines():
        # Tolerate the model adding bullets/numbering/quotes despite instructions.
        s = line.strip().lstrip("-*•0123456789.) ").strip().strip('"').strip("'")
        if s:
            suggestions.append(s)
    return body.rstrip(), suggestions[:_MAX_FOLLOWUPS]


def _strip_partial_marker(text: str) -> str:
    """Hide the follow-up block (and any partial marker) while text streams in.

    During streaming the marker may arrive a few characters at a time, so we also
    trim a trailing prefix of the marker so the user never sees "<<<FOLL…".
    """
    if _FOLLOWUP_MARKER in text:
        return text.split(_FOLLOWUP_MARKER, 1)[0].rstrip()
    # Trim a partial marker forming at the very end (e.g. "…answer.\n<<<FOL").
    for cut in range(len(_FOLLOWUP_MARKER) - 1, 0, -1):
        if text.endswith(_FOLLOWUP_MARKER[:cut]):
            return text[:-cut].rstrip()
    return text


def _queue_followup(prompt_text: str):
    """on_click for a fallback button: queue the prompt for the next rerun."""
    st.session_state["chatbot_pending_prompt"] = prompt_text


def _pill_selected(widget_key: str):
    """on_change for a pills widget: queue the picked suggestion, then clear it.

    Resetting the widget's value to None in the same callback means it won't
    re-fire on subsequent reruns — the queued prompt is consumed once, by the
    chat-input handler, and sent as the next user message.
    """
    val = st.session_state.get(widget_key)
    if val:
        st.session_state["chatbot_pending_prompt"] = val
        st.session_state[widget_key] = None


def _render_followup_pills(suggestions, key_prefix: str):
    """Render follow-up suggestions as clickable pills that send on click.

    Uses st.pills when available (Streamlit >= 1.40); clicking one fires an
    on_change callback that queues the text and the fragment rerun sends it as
    the next user message. Falls back to buttons on older Streamlit.
    """
    suggestions = [s for s in (suggestions or []) if s]
    if not suggestions:
        return
    st.caption("Suggested follow-ups")
    pills = getattr(st, "pills", None)
    if pills is not None:
        widget_key = f"{key_prefix}_pills"
        pills(
            "Suggested follow-ups",
            options=suggestions,
            selection_mode="single",
            label_visibility="collapsed",
            key=widget_key,
            on_change=_pill_selected,
            args=(widget_key,),
        )
        return
    # Fallback for older Streamlit: one button per suggestion.
    for i, s in enumerate(suggestions):
        st.button(s, key=f"{key_prefix}_fu_{i}", use_container_width=True,
                  on_click=_queue_followup, args=(s,))


# ==================== session state ====================

def _init_state():
    ss = st.session_state
    ss.setdefault("chatbot_messages", [])
    ss.setdefault("chatbot_display", [])
    ss.setdefault("chatbot_staged_constraints", [])
    ss.setdefault("chatbot_applied_constraints", [])
    ss.setdefault("chatbot_constraint_source_sig", None)


def _reset_chat():
    """Clear only the conversation behind the 'New chat' button.

    Wipes the LLM transcript and the rendered chat bubbles, but deliberately
    LEAVES the constraint state untouched — staged (proposed) constraints,
    applied constraints, and the source signature all survive. So "New chat"
    starts a fresh conversation without disturbing the optimization or any
    constraints the user is still working with; the dashboard does not need to
    recompute.
    """
    ss = st.session_state
    ss.chatbot_messages = []
    ss.chatbot_display = []


def get_applied_constraints_df():
    """Return the applied-constraint DataFrame for the pipeline, or None.

    Called by dashboard.py to inject chatbot constraints into the optimizer
    alongside (or instead of) an uploaded constraint file.
    """
    applied = st.session_state.get("chatbot_applied_constraints") or []
    if not applied:
        return None
    return T.constraints_to_dataframe(applied)


def _seed_working_set_from_df(constraints_df, sig: str, df=None):
    """Load a processed constraint DataFrame into the chat working set once.

    `sig` uniquely identifies the source (file name + size). The working set is
    only (re)seeded when the signature changes, so the user's in-chat edits and
    drafted rules survive normal Streamlit reruns. Returns True if it seeded.
    """
    ss = st.session_state
    if constraints_df is None or len(constraints_df) == 0:
        return False
    if ss.get("chatbot_constraint_source_sig") == sig:
        return False
    rows = T.constraints_from_dataframe(
        constraints_df, origin="uploaded", valid_carriers=_valid_carriers(df) or None
    )
    if not rows:
        return False
    # Preserve any assistant-drafted rows not already represented by the upload.
    existing_drafted = [
        c for c in (ss.get("chatbot_staged_constraints") or [])
        if c.get("_origin") == "assistant"
    ]
    ss.chatbot_staged_constraints = rows + existing_drafted
    ss.chatbot_constraint_source_sig = sig
    return True


# ==================== tool executor ====================

def _valid_carriers(df) -> set:
    if df is None or len(df) == 0:
        return set()
    col = "Dray SCAC(FL)" if "Dray SCAC(FL)" in df.columns else "Carrier"
    if col not in df.columns:
        return set()
    return {str(c).strip() for c in df[col].dropna().unique()}


def _collect_session_context(rate_type="Base Rate") -> dict:
    """Gather the live app state a chat turn ran under, for the execution log.

    Pure read of session_state — filters, optimizer weights, constraint state,
    peel-pile/scenario caches, and the constraint source signature — so the log
    explains *what the optimizer was configured to do* when the LLM answered.
    """
    ss = st.session_state

    def _scenario_caches():
        # Scenarios are computed per-render and cached under _strategy_cache_<name>.
        return sorted(
            str(k).replace("_strategy_cache_", "")
            for k in ss.keys() if str(k).startswith("_strategy_cache_")
        )

    staged = ss.get("chatbot_staged_constraints") or []
    return {
        "rate_type": ss.get("rate_type", rate_type),
        "optimizer_weights": {
            "cost_weight_pct": ss.get("opt_cost_weight", 70),
            "performance_weight_pct": ss.get("opt_performance_weight", 30),
            "max_growth_pct": ss.get("opt_max_growth_pct", 30),
        },
        "filters": {
            "applied": ss.get("filters_applied", False),
            "ports": ss.get("filter_ports") or [],
            "facilities": ss.get("filter_fcs") or [],
            "weeks": ss.get("filter_weeks") or [],
            "carriers": ss.get("filter_scacs") or [],
        },
        "constraints": {
            "staged_count": len(staged),
            "staged_with_problems": sum(1 for c in staged if c.get("_problems")),
            "applied_count": len(ss.get("chatbot_applied_constraints") or []),
            "source_signature": ss.get("chatbot_constraint_source_sig"),
            "summary_rows": len(ss.get("chatbot_constraint_summary") or []),
        },
        "peel_pile": {
            "allocations": len(ss.get("peel_pile_allocations") or {}),
            "pending": len(ss.get("peel_pile_pending") or {}),
        },
        "scenarios_computed": _scenario_caches(),
        "optimization_error": ss.get("_optimization_error"),
    }


def _make_tool_executor(df, rate_data=None, rate_type="Base Rate"):
    """Build the callable the Converse loop uses to run tool calls."""

    def executor(name: str, tool_input: dict):
        carriers = _valid_carriers(df)
        # Live optimizer weights from the dashboard (0-100 ints -> 0-1 floats). The
        # closure may read session state; the pure handlers receive plain floats.
        ss = st.session_state
        cw = float(ss.get("opt_cost_weight", 70)) / 100.0
        pw = float(ss.get("opt_performance_weight", 30)) / 100.0
        mg = float(ss.get("opt_max_growth_pct", 30)) / 100.0
        try:
            if name == "analyze_data":
                return T.analyze_data(
                    df,
                    query_type=tool_input.get("query_type", "overview"),
                    top_n=int(tool_input.get("top_n", 10) or 10),
                ), False

            # ---- flip cost simulation (read-only) ----
            if name == "describe_selection":
                return T.describe_selection(
                    df, tool_input.get("scope"), rate_data, rate_type
                ), False

            if name == "simulate_flip":
                return T.simulate_flip(
                    df, tool_input.get("scope"), tool_input.get("target_carrier"),
                    rate_data, rate_type,
                ), False

            if name == "compare_carriers":
                return T.compare_carriers(
                    df, tool_input.get("scope"), tool_input.get("candidates"),
                    rate_data, rate_type,
                ), False

            if name == "lane_rate_options":
                return T.lane_rate_options(
                    df, tool_input.get("scope"), rate_data, rate_type
                ), False

            if name == "flip_report":
                return T.flip_report(
                    df, tool_input.get("scope"), tool_input.get("target_carrier"),
                    rate_data, rate_type, tool_input.get("max_rows", 200),
                ), False

            # ---- optimization-aware tools (read-only) ----
            if name == "get_optimization_settings":
                return T.get_optimization_settings(cw, pw, mg), False

            if name == "recommend_carrier":
                return T.recommend_carrier(
                    df, tool_input.get("scope"), cw, pw, mg,
                    top_n=tool_input.get("top_n", 5),
                ), False

            if name == "preview_optimization":
                return T.preview_optimization(
                    df, ss.get("chatbot_staged_constraints"), rate_data,
                    cw, pw, mg, historical_data=df,
                ), False

            if name == "optimization_summary":
                return T.optimization_summary(df, cw, pw, mg), False

            if name == "run_optimization":
                return T.run_optimization(
                    df, tool_input.get("scenario"), tool_input.get("scope"),
                    cost_weight=cw, performance_weight=pw, max_growth_pct=mg,
                    historical_data=df, top_n=tool_input.get("top_n", 25),
                ), False

            if name == "run_analysis":
                result = T.run_analysis(
                    df, tool_input.get("code"), tool_input.get("max_rows", 200),
                )
                # Surface a failed snippet as an error turn so the model can retry.
                return result, (not result.get("ok", False))

            # ---- data diagnostics (read-only) ----
            if name == "historic_volume_share":
                return T.historic_volume_share(
                    df, tool_input.get("scope"),
                    n_weeks=tool_input.get("n_weeks", 5),
                    top_n=tool_input.get("top_n", 25),
                ), False

            if name == "missing_rate_audit":
                return T.missing_rate_audit(df, top_n=tool_input.get("top_n", 25)), False

            if name == "trace_containers":
                return T.trace_containers(
                    df, tool_input.get("container_ids"),
                    max_rows=tool_input.get("max_rows", 100),
                ), False

            if name == "describe_constraints":
                return T.describe_constraints(
                    st.session_state.get("chatbot_staged_constraints"),
                    source=st.session_state.get("chatbot_constraint_source_sig"),
                ), False

            if name == "read_constraints_summary":
                return T.summarize_applied_constraints(
                    st.session_state.get("chatbot_constraint_summary"),
                ), False

            if name == "preview_constraint_scope":
                return T.preview_constraint_scope(df, tool_input), False

            if name == "generate_constraints":
                result = T.generate_constraints(
                    tool_input.get("proposals", []),
                    existing=st.session_state.get("chatbot_staged_constraints"),
                    valid_carriers=carriers or None,
                    df=df,  # composite: fold scope-match counts into the result
                )
                # Stage all returned rows (valid + invalid) for the review panel.
                if "constraints" in result:
                    st.session_state.chatbot_staged_constraints = result["constraints"]
                return result, False

            if name == "edit_constraints":
                result = T.edit_constraints(
                    st.session_state.get("chatbot_staged_constraints") or [],
                    tool_input.get("edits", []),
                    valid_carriers=carriers or None,
                    df=df,  # composite: fold scope-match counts into the result
                )
                if "constraints" in result:
                    st.session_state.chatbot_staged_constraints = result["constraints"]
                return result, False

            # ---- direct apply / remove (mutates the live optimization) ----
            if name == "apply_constraints":
                if tool_input.get("confirm") is not True:
                    return {"error": ("Apply requires explicit user confirmation. Ask the user to "
                                      "confirm, then call apply_constraints with confirm:true.")}, True
                result = T.apply_constraints(ss.get("chatbot_staged_constraints"))
                if result.get("applied_count", 0) > 0:
                    ss.chatbot_applied_constraints = result["to_apply"]
                    ss.chatbot_apply_happened = True
                    return {
                        "applied_count": result["applied_count"],
                        "applied": result.get("applied", []),
                        "rejected": result.get("rejected", []),
                        "note": ("Applied to the live optimization. The dashboard will recalculate "
                                 "on the next refresh."),
                    }, False
                # Nothing valid to apply — do NOT write session state.
                return result, True

            if name == "remove_applied_constraints":
                if tool_input.get("confirm") is not True:
                    return {"error": ("Removal requires explicit user confirmation. Ask the user to "
                                      "confirm, then call remove_applied_constraints with confirm:true.")}, True
                removed = len(ss.get("chatbot_applied_constraints") or [])
                ss.chatbot_applied_constraints = []
                ss.chatbot_apply_happened = True
                return {
                    "removed_count": removed,
                    "note": ("Removed the AI-applied constraints. The dashboard will recalculate on "
                             "the next refresh."),
                }, False

            return {"error": f"Unknown tool '{name}'."}, True
        except Exception as e:  # never let a tool crash kill the loop
            logger.exception("Tool %s failed", name)
            return {"error": f"Tool '{name}' failed: {e}"}, True

    return executor


# ==================== rendering ====================

def _render_staged_panel():
    """Editable table of staged constraints + Apply / Download / Clear actions."""
    staged = st.session_state.get("chatbot_staged_constraints") or []
    if not staged:
        return

    st.markdown("**📋 Proposed constraints**")

    invalid = [c for c in staged if c.get("_problems")]
    if invalid:
        st.warning(f"{len(invalid)} of {len(staged)} proposed constraint(s) have issues.")
        for i, c in enumerate(staged):
            if c.get("_problems"):
                st.caption(f"Row {i}: " + "; ".join(c["_problems"]))

    display_df = T.constraints_to_dataframe(staged)
    # Drop all-empty columns to keep the narrow sidebar readable.
    display_df = display_df.dropna(axis=1, how="all")
    edited = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=False,
        num_rows="dynamic",
        key="chatbot_constraint_editor",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Apply", use_container_width=True, key="chatbot_apply"):
            # Re-validate whatever the user left in the editor before applying.
            edited_rows = edited.to_dict("records")
            result = T.generate_constraints(edited_rows, valid_carriers=None)
            applicable = [c for c in result["constraints"] if not c.get("_problems")]
            if not applicable:
                st.error("No valid constraints to apply. Fix the issues above first.")
            else:
                st.session_state.chatbot_applied_constraints = applicable
                st.success(f"Applied {len(applicable)} constraint(s). Recalculating…")
                st.rerun()
    with col2:
        excel_bytes = T.constraints_to_excel_bytes(
            [c for c in staged if not c.get("_problems")]
        )
        st.download_button(
            "📥 Download",
            data=excel_bytes,
            file_name="ai_constraints.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="chatbot_download",
        )

    if st.button("🗑️ Clear proposals", use_container_width=True, key="chatbot_clear_staged"):
        st.session_state.chatbot_staged_constraints = []
        st.rerun()

    if st.session_state.get("chatbot_applied_constraints"):
        n = len(st.session_state.chatbot_applied_constraints)
        st.info(f"🔒 {n} AI constraint(s) currently applied to the optimization.")
        if st.button("Remove applied AI constraints", use_container_width=True,
                     key="chatbot_remove_applied"):
            st.session_state.chatbot_applied_constraints = []
            st.rerun()


_TOOL_LABELS = {
    "analyze_data": "Analyzing the data",
    "describe_selection": "Inspecting the selection",
    "simulate_flip": "Pricing the flip",
    "compare_carriers": "Comparing carriers",
    "lane_rate_options": "Looking up lane rates",
    "flip_report": "Building the flip report",
    "get_optimization_settings": "Reading the optimizer settings",
    "recommend_carrier": "Ranking carriers by the optimizer",
    "preview_optimization": "Previewing the optimization impact",
    "optimization_summary": "Summarizing the optimization",
    "run_optimization": "Running the scenario",
    "historic_volume_share": "Reading historical volume share",
    "missing_rate_audit": "Auditing rate coverage",
    "trace_containers": "Tracing containers",
    "run_analysis": "Running analysis",
    "describe_constraints": "Reading the constraints",
    "read_constraints_summary": "Reading the applied-constraints impact",
    "preview_constraint_scope": "Previewing constraint scope",
    "generate_constraints": "Drafting constraints",
    "edit_constraints": "Editing constraints",
    "apply_constraints": "Applying constraints to the optimization",
    "remove_applied_constraints": "Removing applied constraints",
}


def _typing_indicator_html(label: str = "Thinking") -> str:
    """Return an animated 'assistant is typing' indicator (three bouncing dots).

    The animation is pure CSS keyframes, so it keeps running in the browser even
    while the Python script is blocked waiting on the Bedrock stream — bridging
    the gap between the user submitting and the first token (or tool) arriving.
    Re-injecting the <style> on each call is harmless (identical rule).
    """
    return f"""
<div class="tender-typing">
  <span class="tender-typing__label">{label}</span>
  <span class="tender-typing__dots"><span></span><span></span><span></span></span>
</div>
<style>
@keyframes tender-bounce {{
  0%, 80%, 100% {{ transform: scale(0.4); opacity: 0.35; }}
  40%          {{ transform: scale(1);   opacity: 1; }}
}}
.tender-typing {{ display: inline-flex; align-items: center; gap: 8px; padding: 4px 0; }}
.tender-typing__label {{ opacity: 0.7; font-size: 0.9em; }}
.tender-typing__dots {{ display: inline-flex; gap: 4px; }}
.tender-typing__dots span {{
  width: 7px; height: 7px; border-radius: 50%; background: currentColor;
  animation: tender-bounce 1.4s infinite ease-in-out both;
}}
.tender-typing__dots span:nth-child(1) {{ animation-delay: -0.32s; }}
.tender-typing__dots span:nth-child(2) {{ animation-delay: -0.16s; }}
</style>
"""


def _render_tool_activity(name, tool_input, result, is_error, parent=None):
    """Render one tool call (its inputs + result) as a collapsible expander.

    Used both live (as a ``tool_result`` event streams in, into the assistant's
    ``parent`` container) and on replay (from the persisted transcript), so the
    rendering stays identical. The expander is collapsed by default to keep the
    narrow sidebar readable; the planner opens it to see the raw tool result.
    """
    target = parent if parent is not None else st
    label = _TOOL_LABELS.get(name, name)
    icon = "⚠️" if is_error else "🔧"
    with target.expander(f"{icon} {label}", expanded=False):
        if tool_input:
            st.caption("Input")
            st.json(tool_input, expanded=False)
        st.caption("Result")
        if isinstance(result, (dict, list)):
            st.json(result, expanded=False)
        else:
            st.write(result)


def _handle_user_message(user_text: str, df, rate_data=None, rate_type="Base Rate",
                         constraints_file=None):
    """Send a user message through the Converse loop and stream the reply."""
    ss = st.session_state

    # Seed the main-panel constraint file into the working set LAZILY — on the
    # first message that needs it, not on passive page load — so the chat opens
    # with a clean UI instead of a pre-filled table. The assistant still "uses
    # the uploaded file automatically": by the time it answers, the rules are in
    # the working set (and reflected in the system prompt below).
    if constraints_file is not None:
        _seed_from_uploaded_file(constraints_file, "main", df)

    ss.chatbot_display.append({"role": "user", "text": user_text})
    ss.chatbot_messages.append({"role": "user", "content": [{"text": user_text}]})

    # Render the just-submitted user bubble now — the transcript loop above ran
    # before this message was appended, so without this it'd vanish until rerun.
    with st.chat_message("user"):
        st.markdown(user_text)

    client = BedrockChatClient()
    if not client.has_credentials:
        msg = ("⚠️ No Bedrock credentials found. Add AWS_BEDROCK_API_KEY to "
               "tests/.env (or AWS_accessKeyId / AWS_secretAccessKey).")
        ss.chatbot_display.append({"role": "assistant", "text": msg})
        with st.chat_message("assistant"):
            st.markdown(msg)
        return

    executor = _make_tool_executor(df, rate_data, rate_type)

    # Compose a per-turn system prompt whose leading "Session status" line states
    # the GROUND TRUTH of what's loaded right now — so the model can't claim the
    # constraint working set is empty (or that nothing was uploaded) when it isn't.
    system_prompt = build_system_prompt(
        data_rows=(0 if df is None else len(df)),
        constraint_rows=len(ss.get("chatbot_staged_constraints") or []),
        constraint_source=ss.get("chatbot_constraint_source_sig"),
        applied_rows=len(ss.get("chatbot_applied_constraints") or []),
    )

    # Execution log: one JSON file per turn under execution logs/. Captures the
    # full app/session context, data snapshots (linked, not embedded), the system
    # prompt, every tool call, and the final answer. Best-effort — a logging
    # failure never interrupts the chat. ``chatbot_messages`` already holds the
    # just-appended user turn, so prior_message_count subtracts it.
    exec_log = ExecutionLogger(
        user_text, df=df, rate_data=rate_data, rate_type=rate_type,
        model_id=getattr(client, "model_id", None),
        region=getattr(client, "region", None),
        session_context=_collect_session_context(rate_type),
        turn_index=len(ss.chatbot_display),
        prior_message_count=max(0, len(ss.chatbot_messages) - 1),
    )
    exec_log.set_system_prompt(system_prompt, tool_specs_count=len(TOOL_SPECS))

    # Stream the assistant turn into a live placeholder so the user sees text as
    # it is generated rather than waiting for the whole reply.
    with st.chat_message("assistant") as assistant_msg:
        # Tool activity renders above the answer text, in call order, so the
        # planner sees each result stream in as it lands.
        tools_area = st.container()
        placeholder = st.empty()
        status = st.empty()
        rendered = ""
        reply = ""
        # Show the bouncing-dots indicator immediately, before the first token or
        # tool lands, so the wait never looks frozen. The CSS animation keeps
        # running while Python blocks on the stream.
        status.markdown(_typing_indicator_html(), unsafe_allow_html=True)
        # Each finished tool: {name, input, result, is_error}. Persisted into the
        # transcript so the expanders survive Streamlit reruns.
        tool_activity: list[dict] = []
        try:
            for event in client.stream_conversation(
                messages=ss.chatbot_messages,
                system=system_prompt,
                tool_specs=TOOL_SPECS,
                tool_executor=executor,
            ):
                etype = event.get("type")
                if etype == "text":
                    rendered += event["text"]
                    # First real text — drop the typing indicator, show the cursor.
                    if status is not None:
                        status.empty()
                    # Hide the follow-up marker/block while streaming, then show a
                    # trailing cursor to signal "still typing".
                    placeholder.markdown(_strip_partial_marker(rendered) + "▌")
                elif etype == "tool_use":
                    label = _TOOL_LABELS.get(event["name"], f"Running {event['name']}")
                    # Keep the animated dots, but relabel them to the live tool.
                    status.markdown(
                        _typing_indicator_html(label), unsafe_allow_html=True
                    )
                elif etype == "tool_result":
                    # A tool finished — stream its result into the chat now, and
                    # record it so it persists when the transcript re-renders.
                    activity = {
                        "name": event["name"],
                        "input": event.get("input") or {},
                        "result": event.get("result"),
                        "is_error": event.get("is_error", False),
                    }
                    tool_activity.append(activity)
                    exec_log.log_tool(
                        activity["name"], activity["input"],
                        activity["result"], activity["is_error"],
                    )
                    _render_tool_activity(
                        activity["name"], activity["input"], activity["result"],
                        activity["is_error"], parent=tools_area,
                    )
                    # Tool done — the model usually thinks again before the next
                    # text/tool, so keep the dots up to cover that gap.
                    status.markdown(_typing_indicator_html(), unsafe_allow_html=True)
                elif etype == "done":
                    ss.chatbot_messages = event["messages"]
                    reply = event["text"] or rendered or "(no response)"
            status.empty()
            raw_text = reply or rendered or "(no response)"
            # Split off the model's suggested follow-ups so the answer reads clean
            # and the suggestions become clickable pills.
            visible_text, followups = _split_followups(raw_text)
            visible_text = visible_text or "(no response)"
            placeholder.markdown(visible_text)
            ss.chatbot_display.append(
                {"role": "assistant", "text": visible_text, "tools": tool_activity,
                 "followups": followups}
            )
            # The caller reruns the fragment right after this returns, so the
            # transcript re-renders these as clickable pills under this turn.
            exec_log.set_reply(visible_text)
            exec_log.set_followups(followups)
        except BedrockClientError as e:
            status.empty()
            placeholder.markdown(f"⚠️ {e}")
            ss.chatbot_display.append(
                {"role": "assistant", "text": f"⚠️ {e}", "tools": tool_activity}
            )
            exec_log.set_error(str(e))
        except Exception as e:  # pragma: no cover
            logger.exception("Chatbot conversation failed")
            status.empty()
            placeholder.markdown(f"⚠️ Unexpected error: {e}")
            ss.chatbot_display.append(
                {"role": "assistant", "text": f"⚠️ Unexpected error: {e}", "tools": tool_activity}
            )
            exec_log.set_error(f"Unexpected error: {e}")
        finally:
            exec_log.write()


def _seed_from_uploaded_file(uploaded_file, source_label, df):
    """Process an uploaded constraint file and seed the working set from it."""
    from ..constraints import processor as cp
    try:
        size = getattr(uploaded_file, "size", None)
        sig = f"{source_label}:{getattr(uploaded_file, 'name', 'file')}:{size}"
        if st.session_state.get("chatbot_constraint_source_sig") == sig:
            return False
        cdf = cp.process_constraints_file(uploaded_file)
        try:
            uploaded_file.seek(0)  # reset for any other consumer
        except Exception:
            pass
        if cdf is None or len(cdf) == 0:
            return False
        seeded = _seed_working_set_from_df(cdf, sig, df)
        return seeded
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to seed constraints from %s", source_label)
        st.warning(f"Could not read constraint file: {e}")
        return False


def show_chatbot_sidebar(comprehensive_data=None, rate_data=None, rate_type=None,
                         constraints_file=None):
    """Render the assistant in the Streamlit sidebar.

    Call once per run from dashboard.py, passing the comprehensive data table so
    the assistant can analyze it. Pass the processed rate sheet (``rate_data``)
    and active ``rate_type`` so flip-cost simulation can price moves to carriers
    not currently on a lane. Pass ``constraints_file`` (the main uploader's
    constraint file, if any) so the assistant edits the user's actual uploaded
    constraints. Safe to call before data is loaded (df=None).
    """
    _init_state()
    ss = st.session_state

    # Active rate type comes from the dashboard's selector; default to Base Rate.
    if rate_type is None:
        rate_type = ss.get("rate_type", "Base Rate")

    # Streamlit forbids a fragment from calling ``st.sidebar`` itself; the supported
    # pattern is to DECLARE the fragment inside a ``with st.sidebar:`` block. The
    # fragment snapshots the sidebar as its render target at declaration, so its
    # reruns redraw into the sidebar. The static header is drawn here (once per app
    # run); the dynamic panel below is the fragment.
    with st.sidebar:
        st.markdown("## 🤖 Tender Assistant")
        if comprehensive_data is None or len(comprehensive_data) == 0:
            st.caption("Upload data to unlock analysis. You can still draft constraints.")
        else:
            st.caption(f"Connected to {len(comprehensive_data):,} rows of loaded data.")

        _chat_panel(comprehensive_data, rate_data, rate_type, constraints_file)


@st.fragment
def _chat_panel(comprehensive_data, rate_data, rate_type, constraints_file):
    """The dynamic chat panel, isolated as a fragment.

    Declared inside the caller's ``with st.sidebar:`` block (NOT calling
    ``st.sidebar`` here — Streamlit disallows that in a fragment). Because its
    widgets live in the fragment body, interacting with them (sending a message,
    "New chat") reruns ONLY this panel, not all of ``main()`` — so clearing the
    chat is instant instead of recomputing the whole dashboard. "New chat" clears
    only the conversation via an ``on_click`` callback; constraints (staged +
    applied) are left untouched, so the optimization never has to recompute.
    """
    ss = st.session_state

    # The assistant applied/removed constraints last turn; this run reflects the
    # recalculated optimization. Surface a one-shot confirmation, then clear it.
    if ss.pop("chatbot_apply_happened", False):
        st.success("✅ Optimization recalculated with the assistant's constraint change.")

    # Constraints come from the MAIN uploader, not a separate in-chat control:
    # whatever the user uploads (or the dashboard generates) is already reachable
    # by the assistant. The main-panel file is seeded into the working set lazily
    # on the first chat message (see _handle_user_message), so the assistant opens
    # with a clean UI and still "uses the uploaded file automatically".

    # Conversation transcript. Assistant turns re-render their tool activity
    # (above the answer, in call order) so it persists across reruns. The pills
    # for the LAST assistant turn re-render below it so they survive reruns and
    # stay clickable; older turns' pills are dropped to avoid a cluttered scroll.
    last_assistant_idx = max(
        (i for i, m in enumerate(ss.chatbot_display) if m["role"] == "assistant"),
        default=None,
    )
    for i, msg in enumerate(ss.chatbot_display):
        with st.chat_message(msg["role"]):
            for activity in msg.get("tools") or []:
                _render_tool_activity(
                    activity.get("name"), activity.get("input") or {},
                    activity.get("result"), activity.get("is_error", False),
                )
            st.markdown(msg["text"])
            if i == last_assistant_idx and msg.get("followups"):
                _render_followup_pills(msg["followups"], key_prefix=f"hist_{i}")

    # Empty chat: offer starter prompts as pills so a first click gets things going.
    if not ss.chatbot_display:
        _render_followup_pills(_STARTER_PROMPTS, key_prefix="starter")

    # Proposed-constraints review panel.
    _render_staged_panel()

    # Input — typed message, or a follow-up/starter pill queued via _queue_followup.
    typed = st.chat_input("Ask about the data, price a carrier flip, or describe a constraint…")
    user_text = ss.pop("chatbot_pending_prompt", None) or typed
    if user_text:
        _handle_user_message(user_text, comprehensive_data, rate_data, rate_type,
                             constraints_file=constraints_file)
        st.rerun()

    # "New chat" clears only the conversation, leaving constraints (staged +
    # applied) in place. The on_click callback clears state BEFORE the rerun;
    # since this button lives in the fragment, the click triggers a fragment-only
    # rerun automatically — instant, no full dashboard recompute, no explicit
    # st.rerun() needed.
    if ss.chatbot_display:
        st.button("🧹 New chat", use_container_width=True,
                  key="chatbot_reset", on_click=_reset_chat)
