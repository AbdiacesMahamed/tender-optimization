"""The 5-pass, multi-phase allocation engine for the JBH model.

Implements Section 4 (targets & caps), Section 5 (terminal split + shortfall
redistribution), Section 6 (five-pass engine + phases), Section 7 (HJBT
concentration), and Section 8 (horizon) of the reference document.

Everything reads from a :class:`~config.port_allocation_rules.PortRules`, so the
engine is port-agnostic — point it at a different port's rules and it runs that
port's policy unchanged.

Vocabulary
----------
* "allocated" container = one the model selects for outgate in a given week.
* A container carries a SCAC already (existing assignment) or is blank
  (available for new allocation). Sort order favors blanks first (6.1).
"""

from __future__ import annotations

import logging
import math

import pandas as pd

logger = logging.getLogger(__name__)


# ===========================================================================
# Section 4.1 — weekly target
# ===========================================================================

def compute_weekly_target(week_df: pd.DataFrame, rules) -> int:
    """Dynamic weekly target from CD/TL mix, floored at the base target.

    4.1: containers_per_shift = TL_frac * w_tl + CD_frac * w_cd
         dynamic = shifts_per_week-derived ... then max(dynamic, base).

    The doc's wording ("250 shifts * containers per shift") yields an
    implausibly large number if taken literally against a per-week shift count,
    so we interpret ``shifts_per_week`` as the scaling constant the business
    uses and still floor at base_weekly_target — which is what actually governs
    in practice (the dynamic value only matters when the mix pushes above base).
    """
    if week_df.empty:
        return rules.base_weekly_target

    cats = week_df["category"].astype(str).str.upper() if "category" in week_df.columns else pd.Series([], dtype=str)
    total = len(cats)
    if total == 0:
        return rules.base_weekly_target
    tl_frac = (cats.str.contains("TL")).mean()
    cd_frac = (cats.str.contains("CD")).mean()

    per_shift = tl_frac * rules.containers_per_shift_tl + cd_frac * rules.containers_per_shift_cd
    dynamic = int(per_shift * rules.shifts_per_week)
    return max(dynamic, rules.base_weekly_target)


# ===========================================================================
# Section 5.1 — terminal caps
# ===========================================================================

def compute_terminal_caps(target: int, rules) -> dict[str, int]:
    """5.1: per strategy terminal, cap = round(target * base_pct * (1 + buffer_pct)).

    The reference doc labels this Int(...) but its own stated outputs only
    reconcile with rounding: at target 275 it gives APM 221, TTI 69, TRAPAC 33,
    yet int(275*0.20*1.25)=int(68.75)=68 (not 69). We round to match the
    business's stated effective caps.
    """
    caps = {}
    for term, cfg in rules.strategy_terminals.items():
        caps[term] = round(target * cfg["base_pct"] * (1 + cfg["buffer_pct"]))
    return caps


# ===========================================================================
# Section 6 — the five-pass engine for one terminal in one week
# ===========================================================================

def _sort_candidates(df: pd.DataFrame, rules) -> pd.DataFrame:
    """6.1 sort: containers WITHOUT a SCAC first, then by container_id."""
    work = df.copy()
    scac = work["scac"].astype(str).str.strip() if "scac" in work.columns else pd.Series("", index=work.index)
    work["_has_scac"] = (scac != "") & (scac.str.lower() != "nan")
    sort_cols = ["_has_scac"]
    if "priority_rank" in work.columns:
        sort_cols.append("priority_rank")
    if "container_id" in work.columns:
        sort_cols.append("container_id")
    work = work.sort_values(sort_cols, kind="mergesort").drop(columns="_has_scac")
    return work


def _is_primary_carrier(df: pd.DataFrame, rules) -> pd.Series:
    scac = df["scac"].astype(str).str.strip().str.upper() if "scac" in df.columns else pd.Series("", index=df.index)
    return scac == rules.primary_carrier.upper()


def _is_preferred_facility(df: pd.DataFrame, rules) -> pd.Series:
    if "facility" not in df.columns or not rules.preferred_facilities:
        return pd.Series(False, index=df.index)
    fac = df["facility"].astype(str).str.upper()
    mask = pd.Series(False, index=df.index)
    for pref in rules.preferred_facilities:
        mask |= fac.str.contains(str(pref).upper(), na=False)
    return mask


def allocate_terminal_week(candidates: pd.DataFrame, terminal_cap: int,
                           target: int, rules) -> pd.DataFrame:
    """Run the 5-pass engine for one terminal within one week.

    Returns the input frame with two added columns:
      * 'allocated' (bool)
      * 'alloc_pass' (str: 'Pass 1'..'Pass 5' or 'Overflow' / NA)
      * 'alloc_day'  (the expected_outgate date used for day-cap accounting)

    Day concentration caps (4.3): passes 1-4 use the soft cap, pass 5 the hard
    cap. Containers that can't fit even at the hard cap are marked 'Overflow'.
    """
    work = candidates.copy()
    work["allocated"] = False
    work["alloc_pass"] = pd.NA

    soft_cap = rules.soft_day_cap(target)
    hard_cap = rules.hard_day_cap(target)
    daily_caps = rules.daily_caps  # weekday-name -> absolute cap

    # Running tallies.
    allocated_count = 0
    per_day_count: dict[object, int] = {}

    def _day_key(row):
        og = row.get("expected_outgate")
        return og.date() if pd.notna(og) else None

    def _day_name(row):
        og = row.get("expected_outgate")
        if pd.isna(og):
            return None
        return og.strftime("%A").lower()

    def _try_allocate(idx_order, day_cap_pct, pass_label):
        nonlocal allocated_count
        day_limit = int(target * day_cap_pct)
        for idx in idx_order:
            if allocated_count >= terminal_cap:
                break
            row = work.loc[idx]
            if row["allocated"]:
                continue
            day_key = _day_key(row)
            day_name = _day_name(row)
            if day_key is None:
                continue
            # Absolute per-day operational cap (4.2) — Sunday=0 blocks allocation.
            abs_cap = daily_caps.get(day_name, rules.daily_caps.get("monday", 65))
            used = per_day_count.get(day_key, 0)
            if used >= abs_cap:
                continue
            # Day concentration cap (4.3) — soft for 1-4, hard for 5.
            if used >= day_limit:
                continue
            work.at[idx, "allocated"] = True
            work.at[idx, "alloc_pass"] = pass_label
            per_day_count[day_key] = used + 1
            allocated_count += 1

    is_primary = _is_primary_carrier(work, rules)
    is_pref = _is_preferred_facility(work, rules)

    sorted_idx = _sort_candidates(work, rules).index

    # Pass 1: primary-carrier (HJBT) + preferred facilities.
    p1 = [i for i in sorted_idx if is_primary[i] and is_pref[i]]
    _try_allocate(p1, rules.soft_day_cap_pct, "Pass 1")

    # Pass 2: remaining HJBT, any facility.
    p2 = [i for i in sorted_idx if is_primary[i] and not work.at[i, "allocated"]]
    _try_allocate(p2, rules.soft_day_cap_pct, "Pass 2")

    # Pass 2b: HJBT floor fill — if HJBT < floor% of terminal cap, keep filling HJBT.
    hjbt_floor = int(terminal_cap * rules.hjbt_floor_pct)
    hjbt_allocated = int((work["allocated"] & is_primary).sum())
    if hjbt_allocated < hjbt_floor:
        p2b = [i for i in sorted_idx if is_primary[i] and not work.at[i, "allocated"]]
        _try_allocate(p2b, rules.soft_day_cap_pct, "Pass 2b")

    # Pass 3: non-HJBT preferred facilities.
    p3 = [i for i in sorted_idx if (not is_primary[i]) and is_pref[i] and not work.at[i, "allocated"]]
    _try_allocate(p3, rules.soft_day_cap_pct, "Pass 3")

    # Pass 4: all remaining (soft cap).
    p4 = [i for i in sorted_idx if not work.at[i, "allocated"]]
    _try_allocate(p4, rules.soft_day_cap_pct, "Pass 4")

    # Pass 5: overflow attempt at the hard day cap.
    p5 = [i for i in sorted_idx if not work.at[i, "allocated"]]
    _try_allocate(p5, rules.hard_day_cap_pct, "Pass 5")

    # Anything still unallocated that had a valid outgate is "Overflow".
    still = (~work["allocated"]) & work["expected_outgate"].notna()
    work.loc[still, "alloc_pass"] = "Overflow"

    return work


# ===========================================================================
# Section 5.2 / 5.3 / 6.2 / 8 — phase orchestration for a single week
# ===========================================================================

def allocate_week(week_df: pd.DataFrame, rules, is_extended: bool = False) -> dict:
    """Allocate one horizon week across terminals via the documented phases.

    Args:
        week_df: eligible containers whose expected_outgate_week == this week.
        rules: PortRules.
        is_extended: True for the +3 extended week (restricted logic, Section 8).

    Returns a dict:
        allocated: DataFrame of allocated rows (with terminal/pass/day columns)
        unallocated: DataFrame of rows not allocated (incl. Overflow tagging)
        target, caps, phase_log (list[str]), hjbt_removals (DataFrame)
    """
    phase_log: list[str] = []
    target = compute_weekly_target(week_df, rules)
    caps = compute_terminal_caps(target, rules)
    phase_log.append(f"Weekly target={target}, terminal caps={caps}"
                     + (" [EXTENDED week: restricted logic]" if is_extended else ""))

    work = week_df.copy()
    if "terminal" in work.columns:
        work["terminal"] = work["terminal"].astype(str).str.strip().str.upper()
    work["allocated"] = False
    work["alloc_pass"] = pd.NA
    work["alloc_terminal"] = pd.NA

    strategy_terms = list(rules.strategy_terminals.keys())

    # ---- Phase 1: strategy terminals with buffered caps ----
    shortfall = 0
    apm_term = strategy_terms[0] if strategy_terms else None
    for term in strategy_terms:
        cap = caps.get(term, 0)
        is_primary_pass = (week_df.get("is_secondary_destination") == False) if "is_secondary_destination" in week_df.columns else None
        cand = work[(work["terminal"] == term) & (~work["allocated"])]
        if "is_secondary_destination" in cand.columns:
            cand = cand[~cand["is_secondary_destination"].fillna(False)]
        if cand.empty:
            phase_log.append(f"Phase 1 {term}: no candidates")
            if term != apm_term:
                shortfall += cap  # 5.3 unused capacity redistributes to APM
            continue
        result = allocate_terminal_week(cand, cap, target, rules)
        _merge_alloc(work, result, term)
        n_alloc = int(result["allocated"].sum())
        phase_log.append(f"Phase 1 {term}: cap={cap}, allocated={n_alloc}")
        if term != apm_term and n_alloc < cap:
            shortfall += (cap - n_alloc)  # 5.3

    # ---- Phase 1b: redistribute TTI/TRAPAC shortfall to APM (core horizon only) ----
    if (not is_extended) and apm_term and shortfall > 0:
        expanded_cap = caps.get(apm_term, 0) + shortfall
        cand = work[(work["terminal"] == apm_term) & (~work["allocated"])]
        if "is_secondary_destination" in cand.columns:
            cand = cand[~cand["is_secondary_destination"].fillna(False)]
        if not cand.empty:
            result = allocate_terminal_week(cand, expanded_cap, target, rules)
            _merge_alloc(work, result, apm_term)
            phase_log.append(
                f"Phase 1b: APM expanded cap={expanded_cap} (+{shortfall} shortfall), "
                f"now allocated={int((work['alloc_terminal'] == apm_term).sum())}")
        else:
            phase_log.append(f"Phase 1b: no extra APM candidates for +{shortfall} shortfall")

    # ---- Phase 2: secondary destinations, only if below target (core only) ----
    allocated_total = int(work["allocated"].sum())
    if (not is_extended) and allocated_total < target and "is_secondary_destination" in work.columns:
        deficit = target - allocated_total
        sec = work[(work["is_secondary_destination"].fillna(False)) & (~work["allocated"])]
        if not sec.empty:
            # Allocate secondary across whichever terminal they belong to, capped by deficit.
            result = allocate_terminal_week(sec, deficit, target, rules)
            for term in result["terminal"].unique():
                _merge_alloc(work, result[result["terminal"] == term], term)
            phase_log.append(f"Phase 2: pulled {int(result['allocated'].sum())} secondary-dest "
                             f"containers to cover deficit={deficit}")

    # ---- Phase 3: backup terminals, only if ALL primary exhausted (core only) ----
    allocated_total = int(work["allocated"].sum())
    primary_remaining = work[(work["terminal"].isin(strategy_terms)) & (~work["allocated"])]
    if (not is_extended) and allocated_total < target and primary_remaining.empty:
        deficit = target - allocated_total
        for term in rules.backup_terminals:
            if deficit <= 0:
                break
            cand = work[(work["terminal"] == term) & (~work["allocated"])]
            if cand.empty:
                continue
            backup_cap = int(deficit * (1 + rules.backup_buffer_pct))
            result = allocate_terminal_week(cand, backup_cap, target, rules)
            _merge_alloc(work, result, term)
            got = int(result["allocated"].sum())
            deficit -= got
            phase_log.append(f"Phase 3 backup {term}: allocated={got}, deficit now {deficit}")

    # ---- Section 7: HJBT concentration cap ----
    hjbt_removals = _apply_hjbt_concentration(work, rules, phase_log)

    allocated = work[work["allocated"]].copy()
    unallocated = work[~work["allocated"]].copy()
    return {
        "allocated": allocated,
        "unallocated": unallocated,
        "target": target,
        "caps": caps,
        "phase_log": phase_log,
        "hjbt_removals": hjbt_removals,
    }


def _merge_alloc(work: pd.DataFrame, result: pd.DataFrame, terminal: str):
    """Copy allocation results back into the master frame by index."""
    newly = result.index[result["allocated"] & ~work.loc[result.index, "allocated"]]
    work.loc[newly, "allocated"] = True
    work.loc[newly, "alloc_pass"] = result.loc[newly, "alloc_pass"]
    work.loc[newly, "alloc_terminal"] = terminal
    # Carry overflow tagging for rows this terminal considered but didn't take.
    overflow = result.index[(result["alloc_pass"] == "Overflow") & (~work.loc[result.index, "allocated"])]
    work.loc[overflow, "alloc_pass"] = "Overflow"


def _apply_hjbt_concentration(work: pd.DataFrame, rules, phase_log: list[str]) -> pd.DataFrame:
    """Section 7: if HJBT > max concentration of allocations, flag excess.

    Returns a DataFrame of suggested removals (lowest-priority HJBT allocations
    above the cap). Does NOT unallocate them automatically — the doc says
    "flags excess containers in Suggested Removals".
    """
    allocated = work[work["allocated"]]
    total = len(allocated)
    if total == 0:
        return work.iloc[0:0].copy()
    is_primary = _is_primary_carrier(allocated, rules)
    hjbt_count = int(is_primary.sum())
    max_allowed = int(total * rules.hjbt_max_concentration)
    if hjbt_count <= max_allowed:
        return work.iloc[0:0].copy()

    excess = hjbt_count - max_allowed
    hjbt_rows = allocated[is_primary]
    # Suggest removing the lowest-priority / last-by-id HJBT rows.
    sort_cols = [c for c in ["priority_rank", "container_id"] if c in hjbt_rows.columns]
    if sort_cols:
        hjbt_rows = hjbt_rows.sort_values(sort_cols, ascending=False, kind="mergesort")
    removals = hjbt_rows.head(excess).copy()
    phase_log.append(f"Section 7: HJBT {hjbt_count}/{total} ({hjbt_count/total:.0%}) exceeds "
                     f"{rules.hjbt_max_concentration:.0%} cap — {excess} suggested removals")
    return removals
