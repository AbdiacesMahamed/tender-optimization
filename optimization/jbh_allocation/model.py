"""Top-level orchestrator for the JBH Allocation Model.

Ties together eligibility -> scheduling -> horizon framing -> per-week phase
allocation -> triggers (Sections 2,3,8,4-7,10 of the reference document) into a
single ``run_allocation_model`` call that takes a raw Inbound Container
Milestone DataFrame and a port code, and returns a structured result.

Pure (no Streamlit). The Streamlit wrapper lives in ``ui.py``.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from config.port_allocation_rules import get_port_rules
from .eligibility import (
    normalize_columns, validate_columns, apply_ssl_terminal_fallback, filter_eligible,
    explode_container_ids, filter_to_port,
)
from .scheduling import (
    vba_week_number, compute_expected_outgate, apply_vessel_tiering,
)
from .engine import allocate_week
from .triggers import check_triggers

logger = logging.getLogger(__name__)


def run_allocation_model(milestone_df: pd.DataFrame, port: str,
                         today: date | None = None) -> dict:
    """Run the full JBH allocation model for one port.

    Args:
        milestone_df: raw Inbound Container Milestone frame (per container).
        port: port code (e.g. 'LAX'); must have rules in port_allocation_rules.
        today: horizon anchor date (defaults to date.today()). The horizon is
            today's VBA ISO week + the next (horizon_weeks - 1) weeks.

    Returns a dict:
        port, rules, anchor_week, horizon_weeks (list[int]),
        eligible, excluded (DataFrames),
        weeks: {week_num: <allocate_week result dict>},
        allocated (concatenated DataFrame across weeks),
        triggers (list of breached-trigger dicts, per week + aggregate),
        errors (list[str]) — fatal input problems (empty allocated if present).
    """
    if today is None:
        today = date.today()

    result: dict = {
        "port": str(port).upper(),
        "errors": [],
        "weeks": {},
        "triggers": [],
    }

    # --- resolve rules ---
    try:
        rules = get_port_rules(port)
    except KeyError as exc:
        result["errors"].append(str(exc))
        return result
    result["rules"] = rules

    # --- Section 1: normalize + validate columns ---
    df = normalize_columns(milestone_df)

    # The GVT (Inbound Container Milestone) spans every port and may pack many
    # container IDs into one cell. The model is per-port and per-container, so
    # restrict to the selected port, then explode multi-container rows BEFORE
    # validating/filtering. filter_to_port runs on the raw 'Discharged Port'
    # column, which normalize_columns leaves intact (it isn't in the schema).
    df = filter_to_port(df, port)
    result["port_rows"] = len(df)
    if df.empty:
        result["errors"].append(
            f"No rows for port '{result['port']}' in the input. "
            f"Check the Discharged Port column matches the selected port."
        )
        return result
    df = explode_container_ids(df)

    missing = validate_columns(df)
    if missing:
        result["errors"].append(
            f"Input is missing required column(s): {missing}. "
            f"Required: facility, category, container_id, scac, ocean_eta."
        )
        return result

    # --- Section 15: SSL -> terminal fallback (before eligibility uses terminal) ---
    df = apply_ssl_terminal_fallback(df, rules)

    # --- Section 2: eligibility ---
    eligible, excluded = filter_eligible(df, rules, today=today)
    result["eligible"] = eligible
    result["excluded"] = excluded
    if eligible.empty:
        result["errors"].append("No eligible containers after applying Section 2 filters.")
        return result

    # --- Section 3: expected outgate + vessel tiering ---
    eligible = compute_expected_outgate(eligible, rules)
    eligible = apply_vessel_tiering(eligible, rules)
    result["eligible"] = eligible

    # --- Section 8: horizon framing ---
    anchor_week = vba_week_number(today)
    result["anchor_week"] = anchor_week
    horizon = [anchor_week + i for i in range(rules.horizon_weeks)]
    result["horizon_weeks"] = horizon
    core_count = rules.core_horizon_weeks  # weeks +0..+(core-1) are core

    # --- per-week allocation ---
    all_allocated = []
    for offset, wk in enumerate(horizon):
        is_extended = offset >= core_count
        week_df = eligible[eligible["expected_outgate_week"] == wk]
        if week_df.empty:
            result["weeks"][wk] = {
                "allocated": eligible.iloc[0:0].copy(),
                "unallocated": eligible.iloc[0:0].copy(),
                "target": rules.base_weekly_target, "caps": {},
                "phase_log": [f"Week {wk}: no eligible containers"],
                "hjbt_removals": eligible.iloc[0:0].copy(),
                "is_extended": is_extended,
            }
            continue
        wk_result = allocate_week(week_df, rules, is_extended=is_extended)
        wk_result["is_extended"] = is_extended
        result["weeks"][wk] = wk_result

        alloc = wk_result["allocated"].copy()
        alloc["horizon_week"] = wk
        all_allocated.append(alloc)

        # Section 10 triggers, per week.
        breaches = check_triggers(wk_result["allocated"], week_df, wk_result["target"], rules)
        for b in breaches:
            b["week"] = wk
        result["triggers"].extend(breaches)

    result["allocated"] = (
        pd.concat(all_allocated, ignore_index=True) if all_allocated
        else eligible.iloc[0:0].copy()
    )

    logger.info(
        "JBH model (%s): %d eligible, %d allocated across weeks %s, %d trigger breaches",
        result["port"], len(eligible), len(result["allocated"]), horizon, len(result["triggers"]),
    )
    return result
