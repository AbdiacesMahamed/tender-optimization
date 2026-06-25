"""
Optimization-aware core for the Tender Optimization assistant.

These are pure functions over pandas DataFrames — no Streamlit, no Bedrock — so
they can be unit-tested and adversarially probed in isolation, exactly like
``simulation.py`` and ``code_sandbox.py``. The chat layer (``chat_ui.py``) reads
the live optimizer weights from ``st.session_state`` and passes them in as plain
floats; nothing here ever touches session state.

Why this module exists
-----------------------
The flip tools (``simulation.py``) answer "what would carrier X cost?" by naive
re-pricing. They do NOT reflect how the dashboard actually *decides* allocations:
a weighted blend of cost and performance solved per [Lane, Week] group, with a
historical-growth cap that preserves supplier diversity. This module wraps the
SAME engine the dashboard uses so the assistant can answer "what's the *best*
carrier?" and "what happens to cost if I apply this rule?" in the dashboard's own
terms:

  * ``optimize_carrier_allocation``        (optimization/linear_programming.py)
  * ``cascading_allocate_with_constraints``(optimization/cascading_logic.py)
  * ``apply_constraints_to_data``          (components/constraints_processor.py)

All inputs are copied before use — these functions never mutate what they are
given (mirrors ``FlipSimulator`` and ``apply_optimized_strategy``).
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

CARRIER_COL = "Dray SCAC(FL)"
COUNT_COL = "Container Count"

# Fallback weights (cost, performance, max_growth) — only used if the caller does
# not supply them. The live values come from the dashboard's session state.
DEFAULT_COST_WEIGHT = 0.70
DEFAULT_PERFORMANCE_WEIGHT = 0.30
DEFAULT_MAX_GROWTH_PCT = 0.30

# Above this many rows, running the full LP/cascade inside a streamed chat turn
# is too slow; we return a "narrow the scope" note instead of hanging the reply.
MAX_OPT_ROWS = 8000


# ==================== helpers ====================

def _carrier_col(df: pd.DataFrame) -> str:
    return CARRIER_COL if CARRIER_COL in df.columns else "Carrier"


def _round(v: Any, ndigits: int = 2) -> Optional[float]:
    try:
        return round(float(v), ndigits)
    except (TypeError, ValueError):
        return None


def _cost(df: pd.DataFrame) -> float:
    """Total cost of a frame: sum 'Total Rate', else Base Rate * Container Count.

    Robust to missing columns and non-numeric cells (coerced, NaN treated as 0),
    mirroring ``FlipSimulator._cost`` so the numbers agree with the flip tools.
    """
    if df is None or len(df) == 0:
        return 0.0
    if "Total Rate" in df.columns:
        return float(pd.to_numeric(df["Total Rate"], errors="coerce").fillna(0).sum())
    if "Base Rate" in df.columns and COUNT_COL in df.columns:
        rate = pd.to_numeric(df["Base Rate"], errors="coerce").fillna(0)
        count = pd.to_numeric(df[COUNT_COL], errors="coerce").fillna(0)
        return float((rate * count).sum())
    return 0.0


def _containers(df: pd.DataFrame) -> int:
    if df is None or len(df) == 0 or COUNT_COL not in df.columns:
        return 0
    return int(pd.to_numeric(df[COUNT_COL], errors="coerce").fillna(0).sum())


def _weighted_performance(df: pd.DataFrame) -> Optional[float]:
    """Volume-weighted average Performance_Score (0-1), or None if unavailable."""
    if df is None or len(df) == 0 or "Performance_Score" not in df.columns:
        return None
    perf = pd.to_numeric(df["Performance_Score"], errors="coerce")
    count = pd.to_numeric(df[COUNT_COL], errors="coerce") if COUNT_COL in df.columns \
        else pd.Series(1.0, index=df.index)
    mask = perf.notna() & count.notna()
    total = float(count[mask].sum())
    if total <= 0:
        return None
    return _round(float((perf[mask] * count[mask]).sum() / total), 3)


def _scope_slice(df: pd.DataFrame, scope_input: Any) -> pd.DataFrame:
    """Slice ``df`` to a scope (dict or Scope), reusing the flip tools' semantics."""
    from .simulation import Scope
    scope = scope_input if isinstance(scope_input, Scope) else Scope.from_dict(scope_input)
    if scope.is_empty_spec():
        return df
    return df[scope.mask(df)]


# ==================== cost / performance / mix rollup ====================

def cost_perf_rollup(df: pd.DataFrame) -> dict:
    """Headline cost, volume-weighted performance, and per-carrier volume mix."""
    if df is None or len(df) == 0:
        return {"containers": 0, "total_cost": 0.0, "avg_performance": None, "carrier_mix": {}}
    carrier_col = _carrier_col(df)
    total_containers = _containers(df)
    mix: dict = {}
    if carrier_col in df.columns and total_containers > 0:
        grouped = (
            df.assign(_c=pd.to_numeric(df[COUNT_COL], errors="coerce").fillna(0))
            .groupby(carrier_col)["_c"].sum().sort_values(ascending=False)
        )
        from config.carrier_mapping import get_carrier_name
        for scac, cnt in grouped.items():
            if cnt <= 0:
                continue
            mix[str(scac)] = {
                "name": get_carrier_name(str(scac)),
                "containers": int(cnt),
                "pct": _round(100.0 * cnt / total_containers, 1),
            }
    return {
        "containers": total_containers,
        "total_cost": _round(_cost(df)),
        "avg_performance": _weighted_performance(df),
        "carrier_mix": mix,
    }


# ==================== carrier recommendation (optimizer blend) ====================

def recommend_carriers_core(
    df: Optional[pd.DataFrame],
    scope_input: Any,
    *,
    cost_weight: float = DEFAULT_COST_WEIGHT,
    performance_weight: float = DEFAULT_PERFORMANCE_WEIGHT,
    max_growth_pct: float = DEFAULT_MAX_GROWTH_PCT,
    top_n: int = 5,
) -> dict:
    """Rank carriers for the scoped lanes using the optimizer's cost+performance blend.

    This is NOT naive cheapest: it runs the SAME LP the dashboard's Optimized
    scenario uses (``optimize_carrier_allocation``) on the scoped slice and reports
    how the optimizer would route volume, plus each carrier's average rate and
    performance so the user can see *why*. Only carriers present in the loaded
    data for the scoped lanes are considered (use lane_rate_options/compare_carriers
    to bring in carriers not currently on a lane).
    """
    if df is None or len(df) == 0:
        return {"error": "No data is loaded. Upload GVT and Rate files first."}
    carrier_col = _carrier_col(df)
    for col in (carrier_col, COUNT_COL, "Base Rate", "Lane"):
        if col not in df.columns:
            return {"error": f"Column '{col}' is not available in the loaded data."}

    sliced = _scope_slice(df, scope_input)
    if len(sliced) == 0:
        return {"matched_containers": 0,
                "note": "No containers match that selection. Widen or correct the scope."}
    if len(sliced) > MAX_OPT_ROWS:
        return {"error": f"That scope covers {len(sliced):,} rows — too many to optimize in chat. "
                         "Narrow it (a lane, port, or week) and try again."}

    from optimization.linear_programming import optimize_carrier_allocation
    try:
        allocated = optimize_carrier_allocation(
            sliced.copy(),
            cost_weight=float(cost_weight),
            performance_weight=float(performance_weight),
            carrier_column=carrier_col,
        )
    except Exception as e:  # noqa: BLE001 — surface as a tool error, never raise
        return {"error": f"Optimization failed: {e}"}

    from config.carrier_mapping import get_carrier_name

    # How the optimizer would route the scoped volume (the headline recommendation).
    opt_by_carrier = {}
    if allocated is not None and len(allocated) and carrier_col in allocated.columns:
        g = (allocated.assign(_c=pd.to_numeric(allocated[COUNT_COL], errors="coerce").fillna(0))
             .groupby(carrier_col)["_c"].sum())
        opt_by_carrier = {str(k): int(v) for k, v in g.items() if v > 0}

    # Per-carrier rate / performance from the scoped slice (the "why").
    stats = (sliced.assign(
        _rate=pd.to_numeric(sliced["Base Rate"], errors="coerce"),
        _c=pd.to_numeric(sliced[COUNT_COL], errors="coerce").fillna(0),
    ))
    rows = []
    for scac, grp in stats.groupby(carrier_col):
        rated = grp["_rate"].dropna()
        rows.append({
            "carrier": str(scac),
            "name": get_carrier_name(str(scac)),
            "avg_base_rate": _round(rated.mean()) if len(rated) else None,
            "avg_performance": _weighted_performance(grp),
            "current_containers": int(grp["_c"].sum()),
            "optimizer_allocated_containers": int(opt_by_carrier.get(str(scac), 0)),
        })
    # Rank by what the optimizer would give them, then by cheaper rate as tiebreak.
    rows.sort(key=lambda r: (-(r["optimizer_allocated_containers"] or 0),
                             r["avg_base_rate"] if r["avg_base_rate"] is not None else float("inf")))

    recommended = rows[0] if rows and rows[0]["optimizer_allocated_containers"] > 0 else None
    return {
        "matched_containers": _containers(sliced),
        "lanes": int(sliced["Lane"].nunique()),
        "weights": {"cost": _round(cost_weight, 2), "performance": _round(performance_weight, 2)},
        "objective": "minimize cost_weight*normalized_cost + performance_weight*(1 - normalized_performance)",
        "recommended": recommended,
        "ranked_carriers": rows[:max(1, int(top_n))],
        "note": ("Ranking reflects the optimizer's cost+performance blend over the loaded data, "
                 "not naive cheapest. Carriers not currently on these lanes are not included; "
                 "use lane_rate_options or compare_carriers to bring in others."),
    }


# ==================== full-allocation wrapper ====================

def run_allocation_core(
    df: Optional[pd.DataFrame],
    *,
    cost_weight: float = DEFAULT_COST_WEIGHT,
    performance_weight: float = DEFAULT_PERFORMANCE_WEIGHT,
    max_growth_pct: float = DEFAULT_MAX_GROWTH_PCT,
    n_historical_weeks: int = 5,
    excluded_carriers: Optional[list] = None,
    historical_data: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Copy-safe wrapper over ``cascading_allocate_with_constraints``.

    Returns the reallocated frame (Optimized scenario semantics) or an empty
    DataFrame if there is nothing to allocate.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame()
    from optimization.cascading_logic import cascading_allocate_with_constraints
    return cascading_allocate_with_constraints(
        df.copy(),
        max_growth_pct=float(max_growth_pct),
        cost_weight=float(cost_weight),
        performance_weight=float(performance_weight),
        n_historical_weeks=int(n_historical_weeks),
        excluded_carriers=excluded_carriers,
        historical_data=historical_data if historical_data is not None else df.copy(),
    )


# ==================== scenario comparison (cheapest / performance / optimized) ====================

# The dashboard's reallocation scenarios group by Lane/Week/Category.
_SCENARIO_GROUP_COLS = ["Category", "Lane", "Week Number"]
SCENARIOS = ("cheapest", "performance", "optimized")


def _per_carrier_volume(df: pd.DataFrame) -> dict:
    """{SCAC: containers} for a frame, as plain ints."""
    if df is None or len(df) == 0:
        return {}
    carrier_col = _carrier_col(df)
    if carrier_col not in df.columns:
        return {}
    cnt = pd.to_numeric(df[COUNT_COL], errors="coerce").fillna(0) if COUNT_COL in df.columns \
        else pd.Series(0, index=df.index)
    grp = cnt.groupby(df[carrier_col].astype(str).str.strip()).sum()
    return {str(k): int(v) for k, v in grp.items() if v}


def _cheapest_allocation(sub: pd.DataFrame) -> dict:
    """Move each Lane/Week/Category group to its cheapest *rated* carrier.

    Carriers with a 0 / missing Base Rate are NOT eligible to be "cheapest" — the
    merge fills an absent rate with 0, and picking that would report a phantom
    saving (the unrated-lane trap ``simulation.py`` guards). Groups with no rated
    carrier keep their current allocation and are flagged as unpriced.
    """
    carrier_col = _carrier_col(sub)
    group_cols = [c for c in _SCENARIO_GROUP_COLS if c in sub.columns]
    if not group_cols:
        return {"error": "Need at least one of Category / Lane / Week Number to build "
                         "the cheapest scenario."}
    w = sub.copy()
    w["_rate"] = pd.to_numeric(w.get("Base Rate"), errors="coerce")
    w["_c"] = pd.to_numeric(w[COUNT_COL], errors="coerce").fillna(0)

    per_carrier_new: dict = {}
    new_cost = 0.0
    unpriced_groups = 0
    for _gkey, gdf in w.groupby(group_cols, dropna=False):
        total = int(gdf["_c"].sum())
        if total == 0:
            continue
        rated = gdf[gdf["_rate"] > 0]
        if not rated.empty:
            best = rated.sort_values(["_rate", carrier_col]).iloc[0]
            scac = str(best[carrier_col]).strip()
            per_carrier_new[scac] = per_carrier_new.get(scac, 0) + total
            new_cost += float(best["_rate"]) * total
        else:
            unpriced_groups += 1
            for scac, cnt in _per_carrier_volume(gdf).items():
                per_carrier_new[scac] = per_carrier_new.get(scac, 0) + cnt
            new_cost += _cost(gdf)
    notes = []
    if unpriced_groups:
        notes.append(f"{unpriced_groups} group(s) had no carrier with a published rate; "
                     "those containers were left on their current carrier and not re-priced "
                     "(never costed at $0).")
    return {"new_cost": new_cost, "per_carrier_new": per_carrier_new, "notes": notes}


def _performance_allocation(sub: pd.DataFrame) -> dict:
    """Move each group to its highest-performance carrier (dashboard engine)."""
    if "Performance_Score" not in sub.columns:
        return {"error": "No Performance_Score in the data — the performance scenario "
                         "needs a performance scorecard loaded."}
    from optimization.performance_logic import allocate_to_highest_performance
    try:
        alloc = allocate_to_highest_performance(
            sub, carrier_column=_carrier_col(sub), container_column=COUNT_COL,
            performance_column="Performance_Score",
        )
    except ValueError as exc:
        return {"error": f"Could not build the performance scenario: {exc}"}
    if alloc is None or len(alloc) == 0:
        return {"error": "The performance allocation returned no rows."}
    return {"new_cost": _cost(alloc), "per_carrier_new": _per_carrier_volume(alloc), "notes": []}


def run_scenario_core(
    df: Optional[pd.DataFrame],
    scenario: str,
    scope_input: Any = None,
    *,
    cost_weight: float = DEFAULT_COST_WEIGHT,
    performance_weight: float = DEFAULT_PERFORMANCE_WEIGHT,
    max_growth_pct: float = DEFAULT_MAX_GROWTH_PCT,
    historical_data: Optional[pd.DataFrame] = None,
    top_n: int = 25,
) -> dict:
    """Run a dashboard reallocation scenario over the (optionally scoped) data.

    ``scenario`` is one of 'cheapest', 'performance', 'optimized'. Returns the
    current vs proposed cost, savings and %, and per-carrier volume deltas
    (gained/lost), biggest movers first. Read-only: every frame is copied.

    Distinct from ``optimization_summary`` (which only covers the LP 'optimized'
    scenario over all loaded data): this compares any of the three scenarios over
    an arbitrary scope, the way the dashboard's Detailed Analysis Table does.
    """
    scenario = str(scenario or "").strip().lower()
    if scenario not in SCENARIOS:
        return {"error": f"Unknown scenario '{scenario}'. Choose one of {', '.join(SCENARIOS)}."}
    if df is None or len(df) == 0:
        return {"error": "No data is loaded. Upload GVT and Rate files first.", "scenario": scenario}
    carrier_col = _carrier_col(df)
    if carrier_col not in df.columns or COUNT_COL not in df.columns:
        return {"error": "Data is missing the carrier or container-count column.",
                "scenario": scenario}

    sub = _scope_slice(df, scope_input)
    if len(sub) == 0:
        return {"scenario": scenario, "matched_rows": 0, "containers": 0,
                "note": "No containers match that selection — nothing to optimize."}
    if len(sub) > MAX_OPT_ROWS:
        return {"scenario": scenario,
                "error": f"That scope covers {len(sub):,} rows — too many to optimize in chat. "
                         "Narrow it (a lane, port, or week) and try again."}

    if scenario == "cheapest":
        outcome = _cheapest_allocation(sub)
    elif scenario == "performance":
        outcome = _performance_allocation(sub)
    else:  # optimized
        try:
            alloc = run_allocation_core(
                sub, cost_weight=cost_weight, performance_weight=performance_weight,
                max_growth_pct=max_growth_pct,
                historical_data=historical_data if historical_data is not None else df,
            )
        except Exception as e:  # noqa: BLE001
            outcome = {"error": f"The optimizer failed: {e}"}
        else:
            if alloc is None or len(alloc) == 0:
                outcome = {"error": "The optimizer returned no allocation."}
            else:
                outcome = {"new_cost": _cost(alloc),
                           "per_carrier_new": _per_carrier_volume(alloc), "notes": []}

    if "error" in outcome:
        return {"scenario": scenario, **outcome}

    current_cost = _cost(sub)
    current_containers = _containers(sub)
    per_cur = _per_carrier_volume(sub)
    per_new = outcome["per_carrier_new"]
    new_cost = outcome["new_cost"]
    notes = list(outcome.get("notes", []))

    from config.carrier_mapping import get_carrier_name
    per_carrier = []
    for scac in sorted(set(per_cur) | set(per_new)):
        cur, new = int(per_cur.get(scac, 0)), int(per_new.get(scac, 0))
        if cur == 0 and new == 0:
            continue
        per_carrier.append({"carrier": scac, "name": get_carrier_name(scac),
                            "current_containers": cur, "new_containers": new,
                            "delta": new - cur})
    per_carrier.sort(key=lambda d: abs(d["delta"]), reverse=True)

    # Total volume is conserved, so net gained == net shed; report it as "reallocated".
    reallocated = sum(d["delta"] for d in per_carrier if d["delta"] > 0)
    new_containers = sum(per_new.values())
    if new_containers != current_containers:
        notes.append(f"Allocation totals {new_containers} containers vs {current_containers} "
                     "in the current view (the optimizer drops fractional remainders); cost and "
                     "deltas reflect the allocated set.")

    savings = current_cost - new_cost
    savings_pct = _round(100.0 * savings / current_cost, 2) if current_cost > 0 else None
    try:
        cap = max(1, int(top_n))
    except (TypeError, ValueError):
        cap = 25
    result = {
        "scenario": scenario,
        "matched_rows": int(len(sub)),
        "containers": current_containers,
        "current_cost": _round(current_cost),
        "new_cost": _round(new_cost),
        "cost_delta": _round(new_cost - current_cost),
        "savings": _round(savings),
        "savings_pct": savings_pct,
        "cheaper": savings > 0,
        "containers_reallocated": int(reallocated),
        "reallocated_metric": "net containers shifted between carriers",
        "per_carrier": per_carrier[:cap],
        "per_carrier_omitted": max(0, len(per_carrier) - cap),
    }
    if notes:
        result["notes"] = notes
    return result


# ==================== constraint impact (what-if through the optimizer) ====================

def constraint_impact_core(
    filtered_data: Optional[pd.DataFrame],
    constraints_df: Optional[pd.DataFrame],
    rate_data=None,
    *,
    cost_weight: float = DEFAULT_COST_WEIGHT,
    performance_weight: float = DEFAULT_PERFORMANCE_WEIGHT,
    max_growth_pct: float = DEFAULT_MAX_GROWTH_PCT,
    historical_data: Optional[pd.DataFrame] = None,
) -> dict:
    """Run a constraint set through the REAL pipeline on a copy and report the delta.

    Pipeline (mirrors dashboard.py): apply_constraints_to_data -> lock the
    constrained containers -> reoptimize the unconstrained remainder with the
    matching carriers excluded -> proposed cost = constrained + reoptimized.

    Returns current (as-loaded) vs proposed cost / performance / carrier mix, plus
    the raw ``constraint_summary`` so the caller can digest the per-rule outcome.
    Read-only: every frame is copied before use.
    """
    if filtered_data is None or len(filtered_data) == 0:
        return {"error": "No data is loaded. Upload GVT and Rate files first."}
    if constraints_df is None or len(constraints_df) == 0:
        return {"error": "No constraints to preview. Draft or stage at least one rule first."}
    if len(filtered_data) > MAX_OPT_ROWS:
        return {"error": f"The loaded data has {len(filtered_data):,} rows — too many to preview in "
                         "chat. Narrow the dashboard filters and try again."}

    from components.constraints.processor import apply_constraints_to_data

    current = cost_perf_rollup(filtered_data)

    try:
        (constrained, unconstrained, constraint_summary,
         max_constrained, _fc_excl, _logs) = apply_constraints_to_data(
            filtered_data.copy(), constraints_df, rate_data
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Applying constraints failed: {e}"}

    try:
        reoptimized = run_allocation_core(
            unconstrained,
            cost_weight=cost_weight,
            performance_weight=performance_weight,
            max_growth_pct=max_growth_pct,
            excluded_carriers=max_constrained,
            historical_data=historical_data if historical_data is not None else filtered_data.copy(),
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Reoptimizing the unconstrained remainder failed: {e}"}

    proposed_frame = pd.concat(
        [f for f in (constrained, reoptimized) if f is not None and len(f)],
        ignore_index=True,
    ) if (len(constrained) or len(reoptimized)) else pd.DataFrame()
    proposed = cost_perf_rollup(proposed_frame)

    cur_cost = current["total_cost"] or 0.0
    new_cost = proposed["total_cost"] or 0.0
    delta = _round(new_cost - cur_cost)
    delta_pct = _round(100.0 * (new_cost - cur_cost) / cur_cost, 1) if cur_cost else None

    # Where the volume moves: per-carrier current-vs-proposed container counts so
    # the user sees which carriers shed volume and which pick it up under these
    # constraints (same delta shape run_allocation_core reports for scenarios).
    from config.carrier_mapping import get_carrier_name
    per_cur = _per_carrier_volume(filtered_data)
    per_new = _per_carrier_volume(proposed_frame)
    movement = []
    for scac in sorted(set(per_cur) | set(per_new)):
        cur, new = int(per_cur.get(scac, 0)), int(per_new.get(scac, 0))
        if cur == 0 and new == 0:
            continue
        movement.append({"carrier": scac, "name": get_carrier_name(scac),
                         "current_containers": cur, "new_containers": new,
                         "delta": new - cur})
    movement.sort(key=lambda d: abs(d["delta"]), reverse=True)
    # Conserved volume => net gained == net shed; surface it as one headline number.
    reallocated = sum(d["delta"] for d in movement if d["delta"] > 0)

    return {
        "current": current,
        "proposed": proposed,
        "cost_delta": delta,
        "cost_delta_pct": delta_pct,
        "cheaper": (new_cost < cur_cost) if cur_cost else None,
        "constrained_containers": _containers(constrained),
        "reoptimized_containers": _containers(reoptimized),
        "containers_reallocated": int(reallocated),
        "reallocated_metric": "net containers shifted between carriers under these constraints",
        "per_carrier_movement": movement,
        "constraint_summary": constraint_summary,
        "note": ("Proposed = constrained containers (locked to their target carrier) + the "
                 "unconstrained remainder reoptimized with the capped carriers excluded. "
                 "Current is the allocation as loaded. per_carrier_movement shows where "
                 "the volume moves: negative delta = carrier sheds volume, positive = gains."),
    }
