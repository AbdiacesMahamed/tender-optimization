"""Streamlit UI for the JBH Allocation Model.

Self-contained dashboard section. The model needs a per-container Inbound
Container Milestone file (different schema from the dashboard's aggregated GVT),
so it has its own uploader and runs independently of the tender-optimization
flow. Reuses the in-app GVT only as a convenience default when its columns
happen to match.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd

from config.port_allocation_rules import available_ports, get_port_rules
from .model import run_allocation_model


def _read_milestone(file) -> pd.DataFrame:
    name = getattr(file, "name", "uploaded")
    if name.lower().endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)


def _build_excel(result: dict) -> bytes | None:
    """Multi-sheet workbook: per-week allocations, exclusions, triggers, removals."""
    sheets: list[tuple[str, pd.DataFrame]] = []
    if isinstance(result.get("allocated"), pd.DataFrame) and not result["allocated"].empty:
        sheets.append(("Suggested Allocation", result["allocated"]))
    if isinstance(result.get("excluded"), pd.DataFrame) and not result["excluded"].empty:
        sheets.append(("Excluded", result["excluded"]))

    # Overflow review + HJBT suggested removals, gathered across weeks.
    overflow_parts, removal_parts = [], []
    for wk, wkres in result.get("weeks", {}).items():
        un = wkres.get("unallocated")
        if isinstance(un, pd.DataFrame) and "alloc_pass" in un.columns:
            ov = un[un["alloc_pass"] == "Overflow"]
            if not ov.empty:
                overflow_parts.append(ov.assign(horizon_week=wk))
        rem = wkres.get("hjbt_removals")
        if isinstance(rem, pd.DataFrame) and not rem.empty:
            removal_parts.append(rem.assign(horizon_week=wk))
    if overflow_parts:
        sheets.append(("Overflow Review", pd.concat(overflow_parts, ignore_index=True)))
    if removal_parts:
        sheets.append(("Suggested Removals", pd.concat(removal_parts, ignore_index=True)))

    if result.get("triggers"):
        sheets.append(("Trigger Log", pd.DataFrame(result["triggers"])))

    if not sheets:
        return None

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets:
            safe = df.copy()
            for col in safe.columns:
                if pd.api.types.is_datetime64_any_dtype(safe[col]):
                    try:
                        safe[col] = safe[col].dt.tz_localize(None) if safe[col].dt.tz else safe[col]
                    except (AttributeError, TypeError):
                        pass
            safe.to_excel(writer, sheet_name=name[:31], index=False)
    buf.seek(0)
    return buf.getvalue()


def show_jbh_allocation_report(in_app_gvt: pd.DataFrame | None = None):
    """Render the JBH Allocation Model section in the dashboard."""
    import streamlit as st
    from components.core.config_styling import section_header

    section_header("📦 JBH Allocation Model")

    with st.expander("ℹ️ What this does", expanded=False):
        st.markdown(
            "Runs the **JB Hunt allocation model** on the **GVT file** (a.k.a. the "
            "*Inbound Container Milestone* — per-container inbound ocean data). It "
            "applies the full rule set — eligibility filters, lead-time/expected-outgate "
            "scheduling, the 5-pass terminal allocation engine, capacity caps, and "
            "trigger thresholds.\n\n"
            "By default it uses the **GVT already loaded at the top of the dashboard**; "
            "you can also upload a different milestone file below. Multi-container cells "
            "are split to one row per container, and the data is restricted to the "
            "selected port automatically.\n\n"
            "All port-specific rules live in `config/port_allocation_rules.py`. "
            "**Adding a new port is a one-entry config edit — no code change.**"
        )

    ports = available_ports()
    col1, col2 = st.columns([2, 3])
    with col1:
        port = st.selectbox(
            "Port", ports,
            help="Ports configured in config/port_allocation_rules.py. "
                 "Add a dict entry there to enable more.",
            key="jbh_port",
        )
    with col2:
        st.caption(
            f"Configured ports: **{', '.join(ports)}**. "
            "To add one, copy the LAX block in `config/port_allocation_rules.py`."
        )

    milestone_file = st.file_uploader(
        "Upload a milestone / GVT file (.xlsx / .xlsm / .csv) — optional",
        type=["xlsx", "xlsm", "csv"],
        key="jbh_milestone_upload",
        help="Leave empty to use the GVT already loaded at the top of the dashboard. "
             "Per-container file with terminal, facility, ssl, vessel, category, "
             "container_id (or Container Numbers), scac, ocean_eta, and optionally "
             "term_avail / actual_pu / priority_code.",
    )

    # Resolve the input frame: uploaded file takes priority, else the in-app GVT.
    milestone_df = None
    source = None
    if milestone_file is not None:
        try:
            milestone_df = _read_milestone(milestone_file)
            source = f"uploaded file ({milestone_file.name})"
        except Exception as exc:  # noqa: BLE001 — surface any read error to the user
            st.error(f"❌ Could not read the milestone file: {exc}")
            return
    elif isinstance(in_app_gvt, pd.DataFrame) and not in_app_gvt.empty:
        milestone_df = in_app_gvt
        source = "the GVT loaded at the top of the dashboard"

    if milestone_df is None:
        st.info("Load a GVT at the top of the dashboard, or upload a milestone file here, "
                "to run the allocation model.")
        with st.expander(f"🔧 Active rules for {port}", expanded=False):
            _show_rules(st, get_port_rules(port))
        return

    st.caption(f"Running on **{source}** for port **{port}**.")
    with st.spinner("📦 Running JBH allocation model..."):
        result = run_allocation_model(milestone_df, port)

    if result.get("errors"):
        for err in result["errors"]:
            st.error(f"❌ {err}")
        return

    # ---- Summary metrics ----
    allocated = result["allocated"]
    eligible = result["eligible"]
    excluded = result["excluded"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📥 Input rows", f"{len(milestone_df):,}")
    c2.metric("✅ Eligible", f"{len(eligible):,}")
    c3.metric("📦 Allocated", f"{len(allocated):,}")
    c4.metric("🚫 Excluded", f"{len(excluded):,}")

    st.caption(f"Horizon anchor week **{result['anchor_week']}** · "
               f"weeks {result['horizon_weeks']} (last is the restricted +3 extended week).")

    # ---- Trigger log ----
    if result["triggers"]:
        st.warning(f"⚠️ {len(result['triggers'])} trigger threshold breach(es) — see Trigger Log below.")
        st.dataframe(pd.DataFrame(result["triggers"]), use_container_width=True, hide_index=True)
    else:
        st.success("✅ No trigger thresholds breached.")

    # ---- Per-week breakdown ----
    for wk in result["horizon_weeks"]:
        wkres = result["weeks"].get(wk, {})
        alloc = wkres.get("allocated")
        n = 0 if alloc is None else len(alloc)
        ext = " (extended +3)" if wkres.get("is_extended") else ""
        with st.expander(f"Week {wk}{ext} — {n} allocated (target {wkres.get('target', '?')})",
                         expanded=False):
            for line in wkres.get("phase_log", []):
                st.text(line)
            if alloc is not None and not alloc.empty:
                st.dataframe(alloc, use_container_width=True, hide_index=True)

    # ---- Allocated table + download ----
    st.markdown("**Suggested Allocation (all weeks)**")
    st.dataframe(allocated, use_container_width=True, hide_index=True)

    excel_bytes = _build_excel(result)
    if excel_bytes:
        st.download_button(
            "📥 Download Allocation Workbook (Excel)",
            data=excel_bytes,
            file_name=f"jbh_allocation_{port}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="jbh_download",
        )


def _show_rules(st, rules):
    """Render the resolved rule set as readable tables for auditing."""
    st.markdown(f"**Strategy terminals** (Section 5.1)")
    st.dataframe(pd.DataFrame([
        {"Terminal": t, "Base %": f"{c['base_pct']:.0%}", "Buffer %": f"{c['buffer_pct']:.0%}"}
        for t, c in rules.strategy_terminals.items()
    ]), use_container_width=True, hide_index=True)
    st.markdown(f"**Backup terminals:** {', '.join(rules.backup_terminals) or '—'}")
    st.markdown(f"**Preferred facilities:** {', '.join(rules.preferred_facilities) or '—'}")
    st.markdown(f"**Base weekly target:** {rules.base_weekly_target} · "
                f"**hard ceiling:** {rules.hard_weekly_ceiling}")
    st.markdown(f"**Excluded destinations:** {', '.join(rules.excluded_destinations) or '—'}")
    st.markdown(f"**Secondary destinations:** {', '.join(rules.secondary_destinations) or '—'}")
