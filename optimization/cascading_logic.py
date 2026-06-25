"""
Cascading Allocation Logic with Historical Volume Constraints

This module implements a cascading allocation strategy that:
1. Ranks carriers based on linear programming optimization scores
2. Allocates volume to carriers in rank order
3. Respects historical volume constraints (max 30% growth per carrier)
4. Cascades unallocated volume to next-best carriers

The logic ensures that no carrier receives more than 130% of their historical
allocation, preventing over-concentration and maintaining supplier diversity.
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Set
import pandas as pd
import logging
logger = logging.getLogger(__name__)
import numpy as np

from .linear_programming import optimize_carrier_allocation
from .historic_volume import calculate_carrier_volume_share
from config.category_mapping import canonical_category


DEFAULT_MAX_GROWTH_PCT = 0.30  # 30% maximum growth over historical allocation


def _norm_scope(value):
    """Case/whitespace-insensitive normalization for string scope comparison.

    Mirrors components.constraints.processor.norm_text (defined locally to keep the
    optimization package decoupled from components): upper-cases, trims, and collapses
    internal whitespace so scope values match the same way constraint eligibility does.
    """
    if value is None:
        return value
    return ' '.join(str(value).strip().upper().split())

# ─────────────────────────────────────────────────────────────────────
# CONSTRAINT SCOPE CONFIG
# ─────────────────────────────────────────────────────────────────────
# Maps each scope dimension to two things:
#   constraint_key : the key name stored in the max-constrained dict
#   group_column   : the column name used in optimization groups
#
# To add a new scope dimension (e.g. port), just add an entry here.
# To remove one, delete or comment out the line.
# The optimizer will automatically check all dimensions listed below.
# ─────────────────────────────────────────────────────────────────────
CONSTRAINT_SCOPE_DIMENSIONS = [
    # ( constraint_key,  group_column   )
    ("category",         "Category"     ),
    ("lane",             "Lane"         ),
    ("week",             "Week Number"  ),
    ("day",              "Day of Week"  ),
    # Uncomment to add port-level scoping:
    # ("port",           "Discharged Port"),
]


def cascading_allocate_with_constraints(
    data: pd.DataFrame,
    *,
    max_growth_pct: float = DEFAULT_MAX_GROWTH_PCT,
    cost_weight: float = 0.7,
    performance_weight: float = 0.3,
    n_historical_weeks: int = 5,
    carrier_column: str = "Dray SCAC(FL)",
    container_column: str = "Container Count",
    lane_column: str = "Lane",
    week_column: str = "Week Number",
    category_column: str = "Category",
    excluded_carriers: list = None,
    historical_data: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Allocate containers using cascading logic with historical volume constraints.
    
    Process:
    1. Run linear programming to rank carriers by optimization score
    2. Get historical allocation percentages from last N weeks
    3. Allocate to carriers in rank order, capped at (historical + max_growth%)
    4. Cascade remaining volume to next-best carriers
    5. Generate allocation notes showing historical vs new allocation
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data with carrier options, costs, performance, and history
    max_growth_pct : float, default=0.30
        Maximum growth allowed over historical allocation (0.30 = 30%)
    cost_weight : float, default=0.7
        Weight for cost in LP optimization
    performance_weight : float, default=0.3
        Weight for performance in LP optimization
    n_historical_weeks : int, default=5
        Number of historical weeks to analyze for baseline allocation
    carrier_column : str
        Column identifying carriers
    container_column : str
        Column with container counts
    lane_column : str
        Column identifying lanes
    week_column : str
        Column with week numbers
    category_column : str
        Column identifying categories
    excluded_carriers : list, optional
        List of dicts with 'carrier' and scope filters (category, lane, port, week).
        None scope values mean the constraint applies globally for that dimension.
        In each optimization group, only carriers whose constraint scope matches
        the group's category/lane/week are excluded from receiving volume.
    historical_data : pd.DataFrame, optional
        Unfiltered data to use for calculating historical volume shares.
        If not provided, uses the main data parameter.
        This ensures historical percentages are stable regardless of UI filters.
    
    Returns
    -------
    pd.DataFrame
        Allocated data with additional columns:
        - Carrier_Rank: Rank from LP optimization (1=best)
        - Historical_Allocation_Pct: Carrier's historical market share
        - New_Allocation_Pct: Carrier's new market share
        - Allocation_Notes: Detailed notes on allocation changes
        - Volume_Change: Increase/Decrease indicator
        - Growth_Constrained: Whether allocation was capped by growth limit
    """
    if data is None or data.empty:
        return pd.DataFrame()
    
    # Use historical_data for volume share calculation if provided, otherwise use data
    hist_data_source = historical_data if historical_data is not None else data
    
    # Default to empty list if not provided
    if excluded_carriers is None:
        excluded_carriers = []
    
    # ── IMPORTANT: Do NOT separate excluded carriers from data upfront. ──
    # Max-constrained carriers are already capped in the constrained table.
    # The unconstrained data we receive IS the pool available for optimization.
    # If we remove excluded carriers and ALL carriers are excluded, the data
    # becomes empty and nothing gets optimized.
    #
    # Instead, keep all carriers in the data for LP ranking and groupby,
    # and let _cascading_allocate_single_group prefer non-excluded carriers
    # when allocating volume.
    
    # Grouping for optimization: pool all containers going to the same
    # lane in the same week so the optimizer can pick the best carrier.
    # SSL, Vessel, Facility and Terminal are arrival-specific attributes
    # that should NOT constrain which dray carrier picks up the container.
    # This matches the LP optimization grouping in linear_programming.py.
    group_columns = [lane_column]
    if category_column in data.columns:
        group_columns.insert(0, category_column)
    if week_column in data.columns and week_column not in group_columns:
        group_columns.append(week_column)
    # Day of Week is part of the group key so a day-scoped exclusion stays exact
    # (matches only that weekday's containers) rather than bleeding to the whole week.
    if 'Day of Week' in data.columns and 'Day of Week' not in group_columns:
        group_columns.append('Day of Week')
    
    # Get historical allocation percentages using unfiltered data source
    # This ensures historical percentages are stable regardless of UI filters
    try:
        historical_share = calculate_carrier_volume_share(
            hist_data_source,
            n_weeks=n_historical_weeks,
            carrier_column=carrier_column,
            container_column=container_column,
            week_column=week_column,
            lane_column=lane_column,
            category_column=category_column,
        )
    except Exception as e:
        logger.debug(f"Warning: Could not calculate historical volume: {e}")
        historical_share = pd.DataFrame()
    
    # Run LP optimization to get carrier rankings on ALL data (including excluded carriers)
    # This allows proper ranking even when all carriers are max-constrained
    try:
        lp_results = optimize_carrier_allocation(
            data,
            cost_weight=cost_weight,
            performance_weight=performance_weight,
            carrier_column=carrier_column,
            container_column=container_column,
        )
    except Exception as e:
        logger.debug(f"Warning: LP optimization failed: {e}")
        # Fallback to cheapest carrier if LP fails
        lp_results = data.copy()
    
    # Process each group independently
    result_rows = []
    
    for group_key, group_data in data.groupby(group_columns, dropna=False):
        # Determine which carriers are excluded for THIS group's scope
        group_excluded = _get_excluded_carriers_for_group(
            excluded_carriers, group_key, group_columns,
            category_column, lane_column, week_column,
        )
        
        allocated_group = _cascading_allocate_single_group(
            group_data=group_data,
            group_key=group_key,
            group_columns=group_columns,
            historical_share=historical_share,
            lp_results=lp_results,
            max_growth_pct=max_growth_pct,
            carrier_column=carrier_column,
            container_column=container_column,
            lane_column=lane_column,
            category_column=category_column,
            excluded_carriers=group_excluded,
            excluded_group_data=pd.DataFrame(),  # No longer separating excluded data
        )
        
        if allocated_group is not None and not allocated_group.empty:
            result_rows.append(allocated_group)
    
    if not result_rows:
        return pd.DataFrame()
    
    result = pd.concat(result_rows, ignore_index=True)
    
    return result


def _get_excluded_carriers_for_group(
    max_constrained_carriers: list,
    group_key: Tuple,
    group_columns: List[str],
    category_column: str,
    lane_column: str,
    week_column: str,
) -> Set[str]:
    """
    Determine which carriers are excluded for a specific optimization group.
    
    Uses CONSTRAINT_SCOPE_DIMENSIONS config to check each dimension.
    A max-constraint entry matches a group when every non-None scope filter
    in the entry equals the corresponding group dimension. If a scope filter
    is None, it matches any value (wildcard).
    
    Returns a set of carrier names excluded for this group.
    """
    if not max_constrained_carriers:
        return set()
    
    # Build a dict of group dimension values for easy lookup
    if not isinstance(group_key, tuple):
        group_key = (group_key,)
    group_vals = dict(zip(group_columns, group_key))
    
    excluded = set()
    for mc in max_constrained_carriers:
        carrier = mc.get('carrier')
        if not carrier:
            continue
        
        # Check every dimension defined in CONSTRAINT_SCOPE_DIMENSIONS
        matches = True
        for constraint_key, group_col in CONSTRAINT_SCOPE_DIMENSIONS:
            mc_val = mc.get(constraint_key)
            if mc_val is None:
                continue  # wildcard — skip this dimension
            group_val = group_vals.get(group_col)
            if group_val is None:
                continue  # group doesn't have this dimension — skip
            # Category compares on the canonical bucket so a 'Retail CD' exclusion
            # matches a normalized 'CD' group (both directions); other dimensions
            # use a numeric-safe equality (week numbers may be float vs int).
            if group_col == "Category":
                if canonical_category(mc_val) != canonical_category(group_val):
                    matches = False
                    break
                continue
            try:
                if float(mc_val) != float(group_val):
                    matches = False
                    break
            except (ValueError, TypeError):
                # Case/whitespace-insensitive string compare so a max/lockout rule
                # scoped on e.g. a lowercase Lane or Port still excludes the carrier,
                # mirroring the constraint-eligibility normalization (processor.norm_text).
                if _norm_scope(mc_val) != _norm_scope(group_val):
                    matches = False
                    break
        
        if matches:
            # Normalize the carrier name the same way scope values are compared, so a
            # lockout written as 'abcd' or ' ABCD ' still matches the data's 'ABCD'.
            # The consumer (_cascade_allocate_volume) normalizes data carriers the same
            # way before testing membership.
            excluded.add(_norm_scope(carrier))

    return excluded


def build_lockout_mask(
    df: pd.DataFrame,
    max_constrained_carriers: list,
    carrier_column: str = "Dray SCAC(FL)",
) -> pd.Series:
    """Return a boolean Series flagging rows whose carrier is locked out in that
    row's scope.

    This is the row-level counterpart to ``_get_excluded_carriers_for_group``: it
    applies the SAME scope-matching rules (carrier name + each dimension in
    CONSTRAINT_SCOPE_DIMENSIONS, with category canonicalized and other values
    normalized) but vectorized over an arbitrary dataframe rather than one
    optimization group. Scenario strategies (Performance, Cheapest) use it to keep
    a locked-out carrier from being SELECTED as a group's winner while still
    counting its containers toward the group total — mirroring how the Optimized
    cascade treats lockouts.

    A True value means "this row's carrier must not be chosen for this row's scope".
    Returns an all-False mask when there are no lockouts or no carrier column.
    """
    if df is None or df.empty or not max_constrained_carriers or carrier_column not in df.columns:
        return pd.Series(False, index=df.index if df is not None else None)

    carrier_norm = df[carrier_column].map(_norm_scope)
    mask = pd.Series(False, index=df.index)

    for mc in max_constrained_carriers:
        carrier = mc.get("carrier")
        if not carrier:
            continue
        # Start from "every row matches this carrier", then narrow by each scope dim.
        entry_mask = carrier_norm == _norm_scope(carrier)
        if not entry_mask.any():
            continue
        for constraint_key, group_col in CONSTRAINT_SCOPE_DIMENSIONS:
            mc_val = mc.get(constraint_key)
            if mc_val is None or group_col not in df.columns:
                continue  # wildcard, or data lacks this dimension → don't narrow
            if group_col == "Category":
                want = canonical_category(mc_val)
                entry_mask &= df[group_col].map(canonical_category) == want
            else:
                # Numeric-safe equality (e.g. week 9 vs 9.0), falling back to
                # normalized string compare for lanes/ports/etc.
                col_num = pd.to_numeric(df[group_col], errors="coerce")
                try:
                    mc_num = float(mc_val)
                    dim_mask = col_num == mc_num
                except (ValueError, TypeError):
                    dim_mask = df[group_col].map(_norm_scope) == _norm_scope(mc_val)
                entry_mask &= dim_mask
        mask |= entry_mask

    return mask


def _cascading_allocate_single_group(
    group_data: pd.DataFrame,
    group_key: Tuple,
    group_columns: List[str],
    historical_share: pd.DataFrame,
    lp_results: pd.DataFrame,
    max_growth_pct: float,
    carrier_column: str,
    container_column: str,
    lane_column: str,
    category_column: str,
    excluded_carriers: Set[str],
    excluded_group_data: pd.DataFrame,
) -> pd.DataFrame:
    """
    Allocate containers for a single group using cascading logic.
    
    Internal function that handles allocation for one lane/week/category group.
    excluded_carriers is kept for API compatibility but no longer hard-excludes;
    max constraints are already enforced in the constrained table.
    """
    if group_data.empty:
        return None
    
    # Calculate total containers in this group
    total_containers = group_data[container_column].sum()
    
    total_containers_to_allocate = total_containers
    
    if total_containers_to_allocate == 0:
        return None
    
    # Get ALL carriers in this group
    carriers = group_data[carrier_column].unique().tolist()
    
    if len(carriers) == 0:
        return None
    
    # Collect all Container Numbers for this group if the column exists
    all_container_numbers = []
    container_numbers_column = "Container Numbers"
    if container_numbers_column in group_data.columns:
        all_container_numbers = [
            c.strip()
            for s in group_data[container_numbers_column].dropna()
            for c in str(s).split(',')
            if c.strip()
        ]
    
    # Deduplicate container IDs within this group for clean assignment
    # (upstream dedup already handled cross-carrier dedup per lane/week)
    all_container_numbers = list(dict.fromkeys(all_container_numbers))  # Preserve order while deduplicating
    
    # Use the summed Container Count as source of truth (already deduped upstream)
    # Don't override with len(all_container_numbers) as container IDs may not perfectly match counts
    
    # Build carrier lookup — aggregate when a carrier appears in multiple rows
    # (e.g. same carrier on different vessels within the same lane/week)
    # Vectorized: use groupby to sum containers and concat numbers, then take first row per carrier
    carrier_data = {}
    if container_numbers_column in group_data.columns:
        cn_agg = (
            group_data.groupby(carrier_column, sort=False)[container_numbers_column]
            .apply(lambda s: ', '.join(str(v) for v in s.dropna() if str(v).strip()))
            .to_dict()
        )
    else:
        cn_agg = {}
    count_agg = group_data.groupby(carrier_column, sort=False)[container_column].sum().to_dict()

    # Take first row per carrier as the template
    first_rows = group_data.drop_duplicates(subset=[carrier_column], keep='first')
    for _, row in first_rows.iterrows():
        carrier = row[carrier_column]
        d = row.to_dict()
        d[container_column] = count_agg.get(carrier, 0)
        if cn_agg:
            d[container_numbers_column] = cn_agg.get(carrier, '')
        carrier_data[carrier] = d
    
    # Get LP-based ranking for carriers in this group
    carrier_ranks = _rank_carriers_from_lp(
        carriers=carriers,
        lp_results=lp_results,
        group_key=group_key,
        group_columns=group_columns,
        carrier_column=carrier_column,
        container_column=container_column,
        lane_column=lane_column,
        category_column=category_column,
    )
    
    # Get historical allocation percentages
    historical_pcts = _get_historical_percentages(
        carriers=carriers,
        historical_share=historical_share,
        group_key=group_key,
        group_columns=group_columns,
        carrier_column=carrier_column,
        lane_column=lane_column,
        category_column=category_column,
    )
    
    # Perform cascading allocation (use total including excluded containers)
    allocations, notes = _cascade_allocate_volume(
        carriers=carriers,
        carrier_ranks=carrier_ranks,
        historical_pcts=historical_pcts,
        total_containers=total_containers_to_allocate,
        max_growth_pct=max_growth_pct,
        excluded_carriers=excluded_carriers,
    )
    
    # Build result rows
    result_rows = []
    
    # Track remaining container numbers for proportional distribution
    remaining_container_numbers = all_container_numbers.copy() if all_container_numbers else []
    
    for carrier, allocated_count in allocations.items():
        if allocated_count == 0:
            continue

        row = carrier_data[carrier].copy()

        # Assign Container Numbers based on allocated_count
        if remaining_container_numbers:
            num_to_assign = min(int(allocated_count), len(remaining_container_numbers))
            assigned_containers = remaining_container_numbers[:num_to_assign]
            remaining_container_numbers = remaining_container_numbers[num_to_assign:]
            row[container_numbers_column] = ", ".join(assigned_containers)
            # Container Count must match actual IDs assigned to avoid downstream divergence
            row[container_column] = len(assigned_containers)
        else:
            row[container_column] = allocated_count

        # Add rank
        row['Carrier_Rank'] = carrier_ranks.get(carrier, 999)
        
        # Use actual container count (may differ from allocated_count if IDs were limited)
        actual_count = row[container_column]

        # Add historical and new percentages
        row['Historical_Allocation_Pct'] = historical_pcts.get(carrier, 0)
        row['New_Allocation_Pct'] = (actual_count / total_containers_to_allocate * 100) if total_containers_to_allocate > 0 else 0

        # Add allocation notes
        row['Allocation_Notes'] = notes.get(carrier, "")

        # Add volume change indicator
        hist_pct = historical_pcts.get(carrier, 0)
        new_pct = row['New_Allocation_Pct']

        if new_pct > hist_pct + 0.1:
            row['Volume_Change'] = "↑ Increase"
        elif new_pct < hist_pct - 0.1:
            row['Volume_Change'] = "↓ Decrease"
        else:
            row['Volume_Change'] = "→ Stable"

        # Check if growth was constrained. Mirror the allocator's own cap
        # (_cascade_allocate_volume): a carrier WITH history is capped at
        # hist*(1+growth); a NEW carrier (no history) is capped at growth% of the
        # group, NOT 100% — using 100 here made a genuinely growth-capped new
        # carrier (e.g. held to 30%) wrongly report "No".
        if hist_pct > 0:
            max_allowed_pct = hist_pct * (1 + max_growth_pct)
        else:
            max_allowed_pct = max_growth_pct * 100
        row['Growth_Constrained'] = "Yes" if new_pct >= max_allowed_pct - 0.1 else "No"

        # Recalculate total cost based on actual container count
        if 'Base Rate' in row and pd.notna(row.get('Base Rate')):
            row['Total Rate'] = row['Base Rate'] * actual_count
        if 'CPC' in row and pd.notna(row.get('CPC')):
            row['Total CPC'] = row['CPC'] * actual_count
        
        result_rows.append(row)
    
    # Assign any remaining container numbers due to rounding
    if remaining_container_numbers and result_rows:
        first_row_containers = result_rows[0].get(container_numbers_column, "")
        if first_row_containers:
            result_rows[0][container_numbers_column] = first_row_containers + ", " + ", ".join(remaining_container_numbers)
        else:
            result_rows[0][container_numbers_column] = ", ".join(remaining_container_numbers)
        # Keep Container Count in sync with actual IDs
        all_ids = [c.strip() for c in result_rows[0][container_numbers_column].split(',') if c.strip()]
        result_rows[0][container_column] = len(all_ids)
    
    if not result_rows:
        return None
    
    result = pd.DataFrame(result_rows)
    
    # CRITICAL: Deduplicate Container Numbers across all rows before counting
    # This removes any container that appears in multiple carrier rows
    if container_numbers_column in result.columns:
        seen_containers = set()
        for idx in result.index:
            container_str = result.at[idx, container_numbers_column]
            if pd.notna(container_str) and str(container_str).strip():
                containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
                # Keep only containers not seen before
                unique_containers = []
                for c in containers:
                    if c not in seen_containers:
                        seen_containers.add(c)
                        unique_containers.append(c)
                result.at[idx, container_numbers_column] = ", ".join(unique_containers) if unique_containers else ""
    
    # Recalculate percentages and costs based on allocated Container Count
    # (Don't override Container Count from Container Numbers — use the allocation as source of truth)
    if container_numbers_column in result.columns:
        total_containers_actual = result[container_column].sum()
        if total_containers_actual > 0 and 'New_Allocation_Pct' in result.columns:
            result['New_Allocation_Pct'] = (result[container_column] / total_containers_actual * 100).fillna(0)
        
        # Recalculate Total Cost using the allocated Container Count
        if 'Base Rate' in result.columns:
            result['Total Rate'] = result['Base Rate'] * result[container_column]
        if 'CPC' in result.columns:
            result['Total CPC'] = result['CPC'] * result[container_column]
    
    return result


def _rank_carriers_from_lp(
    carriers: List[str],
    lp_results: pd.DataFrame,
    group_key: Tuple,
    group_columns: List[str],
    carrier_column: str,
    container_column: str,
    lane_column: str,
    category_column: str,
) -> Dict[str, int]:
    """
    Rank carriers based on LP optimization results.
    
    Returns dict mapping carrier to rank (1=best, 2=second best, etc.)
    """
    if lp_results.empty:
        # Default ranking: alphabetical (filter out NaN values)
        valid_carriers = [c for c in carriers if pd.notna(c)]
        return {carrier: idx + 1 for idx, carrier in enumerate(sorted(valid_carriers))}
    
    # Filter LP results to this group - only use LP's grouping columns (Lane, Week Number)
    # The LP groups by Lane+Week only, so we can't filter by finer-grained columns
    lp_group = lp_results
    lp_filter_cols = [lane_column, 'Week Number']
    for col in lp_filter_cols:
        if col in lp_group.columns and col in group_columns:
            col_idx = group_columns.index(col)
            lp_group = lp_group[lp_group[col] == group_key[col_idx]]
    
    if lp_group.empty:
        # No LP results for this group, rank alphabetically (filter out NaN values)
        valid_carriers = [c for c in carriers if pd.notna(c)]
        return {carrier: idx + 1 for idx, carrier in enumerate(sorted(valid_carriers))}
    
    # Rank by container allocation in LP results (higher allocation = better rank)
    if carrier_column in lp_group.columns and container_column in lp_group.columns:
        lp_group = lp_group.sort_values(container_column, ascending=False).reset_index(drop=True)
        carriers_set = set(carriers)
        # Vectorized: filter to relevant carriers and assign ranks by position
        in_group = lp_group[lp_group[carrier_column].isin(carriers_set)]
        carrier_ranks = {c: rank + 1 for rank, c in enumerate(in_group[carrier_column])}

        # Add any carriers not in LP results with lower ranks
        next_rank = len(carrier_ranks) + 1
        for carrier in carriers:
            if carrier not in carrier_ranks:
                carrier_ranks[carrier] = next_rank
                next_rank += 1

        return carrier_ranks
    
    # Fallback: alphabetical (filter out NaN values)
    valid_carriers = [c for c in carriers if pd.notna(c)]
    return {carrier: idx + 1 for idx, carrier in enumerate(sorted(valid_carriers))}


def _get_historical_percentages(
    carriers: List[str],
    historical_share: pd.DataFrame,
    group_key: Tuple,
    group_columns: List[str],
    carrier_column: str,
    lane_column: str,
    category_column: str,
) -> Dict[str, float]:
    """
    Get historical allocation percentages for carriers.
    
    Returns dict mapping carrier to historical percentage (0-100).
    """
    if historical_share.empty:
        # No historical data, assume equal distribution
        return {carrier: 0 for carrier in carriers}
    
    # Filter historical share to this group - optimized boolean indexing
    hist_group = historical_share
    for idx, col in enumerate(group_columns):
        if col in hist_group.columns:
            hist_group = hist_group[hist_group[col] == group_key[idx]]
    
    if hist_group.empty:
        # No historical data for this group
        return {carrier: 0 for carrier in carriers}
    
    # Extract percentages using vectorized operations
    if carrier_column in hist_group.columns and 'Volume_Share_Pct' in hist_group.columns:
        # Create dictionary in one pass
        hist_dict = hist_group.set_index(carrier_column)['Volume_Share_Pct'].to_dict()
        return {carrier: hist_dict.get(carrier, 0) for carrier in carriers}
    
    return {carrier: 0 for carrier in carriers}


def _cascade_allocate_volume(
    carriers: List[str],
    carrier_ranks: Dict[str, int],
    historical_pcts: Dict[str, float],
    total_containers: float,
    max_growth_pct: float,
    excluded_carriers: Set[str],
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """
    Perform cascading allocation with growth constraints.
    
    Returns:
    - allocations: Dict mapping carrier to allocated container count
    - notes: Dict mapping carrier to allocation notes string
    """
    # Sort carriers by rank (best first), filter out NaN values
    valid_carriers = [c for c in carriers if pd.notna(c)]
    # excluded_carriers holds normalized names (see _get_excluded_carriers_for_group),
    # so normalize each data carrier the same way before testing membership — otherwise
    # a lockout written in a different case/spacing than the data would silently miss.
    def _is_excluded(c):
        return _norm_scope(c) in excluded_carriers
    # Separate excluded carriers — they keep containers in the pool but cannot receive allocation
    allocatable_carriers = [c for c in valid_carriers if not _is_excluded(c)]
    sorted_carriers = sorted(allocatable_carriers, key=lambda c: carrier_ranks.get(c, 999))

    allocations = {carrier: 0 for carrier in carriers}
    notes = {}
    remaining = total_containers

    # Mark excluded carriers in notes
    for carrier in valid_carriers:
        if _is_excluded(carrier):
            notes[carrier] = f"Rank #{carrier_ranks.get(carrier, 999)} | ⛔ Max constraint active — excluded from allocation in this group"
    
    # First pass: allocate up to historical + max_growth
    for carrier in sorted_carriers:
        if remaining <= 0:
            break
        
        hist_pct = historical_pcts.get(carrier, 0)
        rank = carrier_ranks.get(carrier, 999)
        
        # Calculate maximum allowed allocation
        if hist_pct > 0:
            # Has historical data: cap at historical + growth%
            max_allowed_pct = hist_pct * (1 + max_growth_pct)
            max_allowed_containers = (max_allowed_pct / 100) * total_containers
        else:
            # No historical data: can take up to max_growth% of total
            max_allowed_pct = max_growth_pct * 100
            max_allowed_containers = (max_allowed_pct / 100) * total_containers
        
        # Allocate
        allocated = min(remaining, max_allowed_containers)
        allocations[carrier] = allocated  # Store exact value, round later
        remaining -= allocated
        
        # Generate notes
        new_pct = (allocated / total_containers * 100) if total_containers > 0 else 0
        
        if hist_pct > 0:
            change_pct = new_pct - hist_pct
            change_abs = allocated - ((hist_pct / 100) * total_containers)
            
            if allocated >= max_allowed_containers - 0.01:
                constraint_note = f" (capped at {max_growth_pct*100:.0f}% growth)"
            else:
                constraint_note = ""
            
            notes[carrier] = (
                f"Rank #{rank} | "
                f"Historical: {hist_pct:.1f}% → New: {new_pct:.1f}% | "
                f"Change: {change_pct:+.1f}% ({change_abs:+.0f} containers){constraint_note}"
            )
        else:
            # New carrier - show if at growth limit
            max_allowed_pct = max_growth_pct * 100
            if allocated >= max_allowed_containers - 0.01:
                limit_note = f" (at {max_growth_pct*100:.0f}% growth limit)"
            else:
                limit_note = f" (limit {max_growth_pct*100:.0f}%)"
            
            notes[carrier] = (
                f"Rank #{rank} | "
                f"Historical: 0% (new carrier) → New: {new_pct:.1f}% | "
                f"Allocated: {allocated:.0f} containers{limit_note}"
            )
    
    # Second pass: if volume remains, allow carriers to exceed growth cap up to a hard
    # ceiling (2x historical or 50% of total for new carriers). Carriers are filled in
    # rank order so better-ranked carriers absorb overflow first.
    OVERFLOW_MULTIPLIER = 2.0  # hard ceiling: 2x the first-pass cap
    MAX_NEW_CARRIER_PCT = 50.0  # new carriers can take up to 50% of group total

    if remaining > 0:
        for carrier in sorted_carriers:
            if remaining <= 0:
                break

            hist_pct = historical_pcts.get(carrier, 0)
            rank = carrier_ranks.get(carrier, 999)

            # Compute hard ceiling for this carrier
            if hist_pct > 0:
                ceiling_pct = hist_pct * (1 + max_growth_pct) * OVERFLOW_MULTIPLIER
            else:
                ceiling_pct = MAX_NEW_CARRIER_PCT
            ceiling_containers = (ceiling_pct / 100) * total_containers

            headroom = ceiling_containers - allocations[carrier]
            if headroom > 0:
                additional = min(remaining, headroom)
                allocations[carrier] += additional
                remaining -= additional

                new_pct = (allocations[carrier] / total_containers * 100) if total_containers > 0 else 0
                if hist_pct > 0:
                    change_pct = new_pct - hist_pct
                    change_abs = allocations[carrier] - ((hist_pct / 100) * total_containers)
                    notes[carrier] = (
                        f"Rank #{rank} | "
                        f"Historical: {hist_pct:.1f}% → New: {new_pct:.1f}% | "
                        f"Change: {change_pct:+.1f}% ({change_abs:+.0f} containers) (overflow, capped at {ceiling_pct:.0f}%)"
                    )
                else:
                    notes[carrier] = (
                        f"Rank #{rank} | "
                        f"Historical: 0% (new carrier) → New: {new_pct:.1f}% | "
                        f"Allocated: {allocations[carrier]:.0f} containers (overflow, capped at {MAX_NEW_CARRIER_PCT:.0f}%)"
                    )

    # Third pass: if volume still remains after hard ceilings, distribute proportionally
    # to all allocatable carriers by rank (no single carrier gets all overflow)
    if remaining > 0.5 and sorted_carriers:
        per_carrier_share = remaining / len(sorted_carriers)
        for carrier in sorted_carriers:
            if remaining <= 0:
                break
            give = min(remaining, per_carrier_share)
            allocations[carrier] += give
            remaining -= give

            hist_pct = historical_pcts.get(carrier, 0)
            new_pct = (allocations[carrier] / total_containers * 100) if total_containers > 0 else 0
            rank = carrier_ranks.get(carrier, 999)
            if hist_pct > 0:
                change_pct = new_pct - hist_pct
                change_abs = allocations[carrier] - ((hist_pct / 100) * total_containers)
                notes[carrier] = (
                    f"Rank #{rank} | "
                    f"Historical: {hist_pct:.1f}% → New: {new_pct:.1f}% | "
                    f"Change: {change_pct:+.1f}% ({change_abs:+.0f} containers) (proportional overflow)"
                )
            else:
                notes[carrier] = (
                    f"Rank #{rank} | "
                    f"Historical: 0% (new carrier) → New: {new_pct:.1f}% | "
                    f"Allocated: {allocations[carrier]:.0f} containers (proportional overflow)"
                )

        # Final safety: assign any rounding remainder to rank-1 carrier
        if remaining > 0.5:
            allocations[sorted_carriers[0]] += remaining
            remaining = 0
    
    # Final step: round all allocations to integers while preserving total_containers
    # Use largest-remainder method so sum(rounded) == total_containers
    floored = {c: int(v) for c, v in allocations.items()}
    remainders = {c: allocations[c] - floored[c] for c in allocations}
    shortfall = int(round(total_containers)) - sum(floored.values())
    for c in sorted(remainders, key=remainders.get, reverse=True):
        if shortfall <= 0:
            break
        floored[c] += 1
        shortfall -= 1
    allocations = floored
    
    return allocations, notes


__all__ = [
    "cascading_allocate_with_constraints",
]
