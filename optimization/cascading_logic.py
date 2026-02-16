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


DEFAULT_MAX_GROWTH_PCT = 0.30  # 30% maximum growth over historical allocation


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
    excluded_carriers: set = None,
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
    excluded_carriers : set, optional
        Set of carrier names to EXCLUDE from receiving any volume allocation.
        These carriers have maximum constraints and should not get additional volume.
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
    
    # Default to empty set if not provided
    if excluded_carriers is None:
        excluded_carriers = set()
    
    # Separate excluded carrier data from allocatable data
    excluded_data = pd.DataFrame()
    if excluded_carriers:
        original_count = len(data)
        # Check both carrier column variations
        carrier_cols_to_check = [carrier_column]
        if 'Carrier' in data.columns and carrier_column != 'Carrier':
            carrier_cols_to_check.append('Carrier')
        
        # Create mask for EXCLUDED carriers (these will be reallocated)
        excluded_mask = pd.Series([False] * len(data), index=data.index)
        for col in carrier_cols_to_check:
            if col in data.columns:
                excluded_mask |= data[col].isin(excluded_carriers)
        
        # Separate the data
        excluded_data = data[excluded_mask].copy()
        data = data[~excluded_mask].copy()
        filtered_count = len(data)
        
        if len(excluded_data) > 0:
            excluded_containers = excluded_data[container_column].sum()
            valid_excluded = [c for c in excluded_carriers if pd.notna(c)]
            logger.debug(f"🔒 Found {len(excluded_data)} rows ({excluded_containers:.0f} containers) from {len(excluded_carriers)} carriers with maximum constraints: {', '.join(sorted(valid_excluded))}")
            logger.debug(f"   These containers will be reallocated to available carriers or marked as unallocatable.")
    
    # Determine grouping columns - must match data_processor.py grouping
    # to prevent mixing containers from different groups
    group_columns = [lane_column]
    if category_column in data.columns:
        group_columns.insert(0, category_column)
    if 'SSL' in data.columns:
        group_columns.insert(1, 'SSL')
    if 'Vessel' in data.columns:
        group_columns.insert(2, 'Vessel')
    if 'Facility' in data.columns:
        group_columns.append('Facility')
    if 'Terminal' in data.columns:
        group_columns.append('Terminal')
    if week_column in data.columns and week_column not in group_columns:
        group_columns.append(week_column)
    
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
    
    # Run LP optimization to get carrier rankings
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
    unallocatable_rows = []
    
    for group_key, group_data in data.groupby(group_columns, dropna=False):
        # Check if there are excluded carrier containers for this group
        excluded_group_data = pd.DataFrame()
        if not excluded_data.empty:
            # Filter excluded_data for this group
            group_mask = pd.Series([True] * len(excluded_data), index=excluded_data.index)
            for i, col in enumerate(group_columns):
                if col in excluded_data.columns:
                    group_mask &= (excluded_data[col] == group_key[i])
            excluded_group_data = excluded_data[group_mask].copy()
        
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
            excluded_carriers=excluded_carriers,
            excluded_group_data=excluded_group_data,
        )
        
        if allocated_group is not None and not allocated_group.empty:
            result_rows.append(allocated_group)
    
    if not result_rows:
        return pd.DataFrame()
    
    result = pd.concat(result_rows, ignore_index=True)
    
    return result


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
    Also handles reallocation of containers from excluded carriers.
    """
    if group_data.empty:
        return None
    
    # Calculate containers from allocatable carriers
    total_containers = group_data[container_column].sum()
    
    # Add excluded carrier containers (these need to be reallocated)
    excluded_containers = 0
    excluded_container_numbers = []
    if not excluded_group_data.empty:
        excluded_containers = excluded_group_data[container_column].sum()
        # Collect container numbers from excluded carriers
        container_numbers_column = "Container Numbers"
        if container_numbers_column in excluded_group_data.columns:
            excluded_container_numbers = [
                c.strip()
                for s in excluded_group_data[container_numbers_column].dropna()
                for c in str(s).split(',')
                if c.strip()
            ]
    
    # Total containers to allocate = allocatable + excluded (to be reallocated)
    total_containers_to_allocate = total_containers + excluded_containers
    
    if total_containers_to_allocate == 0:
        return None
    
    # Get carriers in this group (ONLY allocatable carriers)
    carriers = group_data[carrier_column].unique().tolist()
    
    if len(carriers) == 0:
        # No available carriers - create unallocatable record
        if excluded_containers > 0:
            unallocatable_row = excluded_group_data.iloc[0].copy()
            unallocatable_row[container_column] = excluded_containers
            unallocatable_row['Container Numbers'] = ", ".join(excluded_container_numbers) if excluded_container_numbers else ""
            unallocatable_row['Carrier_Rank'] = 999
            unallocatable_row['Historical_Allocation_Pct'] = 0
            unallocatable_row['New_Allocation_Pct'] = 0
            unallocatable_row['Allocation_Notes'] = f"⚠️ UNALLOCATABLE: {excluded_containers:.0f} containers cannot be assigned (all carriers have maximum constraints)"
            unallocatable_row['Volume_Change'] = "❌ Blocked"
            unallocatable_row['Growth_Constrained'] = "Max Constraint"
            return pd.DataFrame([unallocatable_row])
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
    
    # Add excluded container numbers to the pool
    all_container_numbers.extend(excluded_container_numbers)
    
    # Deduplicate container IDs within this group for clean assignment
    # (upstream dedup already handled cross-carrier dedup per lane/week)
    all_container_numbers = list(dict.fromkeys(all_container_numbers))  # Preserve order while deduplicating
    
    # Use the summed Container Count as source of truth (already deduped upstream)
    # Don't override with len(all_container_numbers) as container IDs may not perfectly match counts
    
    # Build carrier lookup
    carrier_data = {}
    for idx, row in group_data.iterrows():
        carrier = row[carrier_column]
        carrier_data[carrier] = row.to_dict()
    
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
        row[container_column] = allocated_count
        
        # Assign Container Numbers based on allocated_count (not proportion)
        # allocated_count is already the exact number of containers this carrier should receive
        if remaining_container_numbers:
            # Assign exactly allocated_count container IDs (or all remaining if less available)
            num_to_assign = min(int(allocated_count), len(remaining_container_numbers))
            assigned_containers = remaining_container_numbers[:num_to_assign]
            remaining_container_numbers = remaining_container_numbers[num_to_assign:]
            row[container_numbers_column] = ", ".join(assigned_containers)
        
        # Add rank
        row['Carrier_Rank'] = carrier_ranks.get(carrier, 999)
        
        # Add historical and new percentages
        row['Historical_Allocation_Pct'] = historical_pcts.get(carrier, 0)
        row['New_Allocation_Pct'] = (allocated_count / total_containers_to_allocate * 100) if total_containers_to_allocate > 0 else 0
        
        # Add allocation notes
        row['Allocation_Notes'] = notes.get(carrier, "")
        
        # Add volume change indicator
        hist_pct = historical_pcts.get(carrier, 0)
        new_pct = row['New_Allocation_Pct']
        
        if new_pct > hist_pct + 0.1:  # More than 0.1% increase
            row['Volume_Change'] = "↑ Increase"
        elif new_pct < hist_pct - 0.1:  # More than 0.1% decrease
            row['Volume_Change'] = "↓ Decrease"
        else:
            row['Volume_Change'] = "→ Stable"
        
        # Check if growth was constrained
        max_allowed_pct = hist_pct * (1 + max_growth_pct) if hist_pct > 0 else 100
        row['Growth_Constrained'] = "Yes" if new_pct >= max_allowed_pct - 0.1 else "No"
        
        # Recalculate total cost based on available rate columns
        # Check for both Base Rate and CPC to support dynamic rate selection
        if 'Base Rate' in row and pd.notna(row.get('Base Rate')):
            row['Total Rate'] = row['Base Rate'] * allocated_count
        if 'CPC' in row and pd.notna(row.get('CPC')):
            row['Total CPC'] = row['CPC'] * allocated_count
        
        result_rows.append(row)
    
    # Assign any remaining container numbers due to rounding
    if remaining_container_numbers and result_rows:
        first_row_containers = result_rows[0].get(container_numbers_column, "")
        if first_row_containers:
            result_rows[0][container_numbers_column] = first_row_containers + ", " + ", ".join(remaining_container_numbers)
        else:
            result_rows[0][container_numbers_column] = ", ".join(remaining_container_numbers)
    
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
    
    # Filter LP results to this group - use boolean indexing for efficiency
    lp_group = lp_results
    for idx, col in enumerate(group_columns):
        if col in lp_group.columns:
            lp_group = lp_group[lp_group[col] == group_key[idx]]
    
    if lp_group.empty:
        # No LP results for this group, rank alphabetically (filter out NaN values)
        valid_carriers = [c for c in carriers if pd.notna(c)]
        return {carrier: idx + 1 for idx, carrier in enumerate(sorted(valid_carriers))}
    
    # Rank by container allocation in LP results (higher allocation = better rank)
    if carrier_column in lp_group.columns and container_column in lp_group.columns:
        # Sort once and create rank dictionary
        lp_group = lp_group.sort_values(container_column, ascending=False)
        
        # Use dictionary comprehension for efficiency
        carrier_ranks = {row[carrier_column]: rank + 1 
                        for rank, (_, row) in enumerate(lp_group.iterrows()) 
                        if row[carrier_column] in carriers}
        
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
    sorted_carriers = sorted(valid_carriers, key=lambda c: carrier_ranks.get(c, 999))
    
    allocations = {carrier: 0 for carrier in carriers}
    notes = {}
    remaining = total_containers
    
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
    
    # Second pass: if volume remains, allow ALL carriers to take more (bypass growth cap)
    # This handles cases where growth caps prevented full allocation in the first pass
    if remaining > 0:
        for carrier in sorted_carriers:
            if remaining <= 0:
                break
            
            current_allocation = allocations[carrier]
            additional_capacity = total_containers - current_allocation
            
            if additional_capacity > 0:
                additional = min(remaining, additional_capacity)
                allocations[carrier] += additional
                remaining -= additional
                
                # Update notes
                new_pct = (allocations[carrier] / total_containers * 100) if total_containers > 0 else 0
                rank = carrier_ranks.get(carrier, 999)
                hist_pct = historical_pcts.get(carrier, 0)
                
                if hist_pct > 0:
                    change_pct = new_pct - hist_pct
                    change_abs = allocations[carrier] - ((hist_pct / 100) * total_containers)
                    notes[carrier] = (
                        f"Rank #{rank} | "
                        f"Historical: {hist_pct:.1f}% → New: {new_pct:.1f}% | "
                        f"Change: {change_pct:+.1f}% ({change_abs:+.0f} containers) (overflow from growth caps)"
                    )
                else:
                    notes[carrier] = (
                        f"Rank #{rank} | "
                        f"Historical: 0% (new carrier) → New: {new_pct:.1f}% | "
                        f"Allocated: {allocations[carrier]:.0f} containers (overflow from growth caps)"
                    )
    
    # Third pass: if volume still remains, assign to rank 1 (best) carrier
    if remaining > 0.5 and sorted_carriers:  # Check for remaining (> 0.5 to handle rounding)
        best_carrier = sorted_carriers[0]  # Rank 1 carrier
        allocations[best_carrier] += remaining
        
        # Determine if this is due to max constraints or normal cascading
        has_max_constraints = len(excluded_carriers) > 0
        
        # Update notes to indicate overflow was assigned
        hist_pct = historical_pcts.get(best_carrier, 0)
        new_pct = (allocations[best_carrier] / total_containers * 100) if total_containers > 0 else 0
        rank = carrier_ranks.get(best_carrier, 999)
        
        if has_max_constraints:
            # Overflow due to maximum constraints - special note
            if hist_pct > 0:
                change_pct = new_pct - hist_pct
                change_abs = allocations[best_carrier] - ((hist_pct / 100) * total_containers)
                notes[best_carrier] = (
                    f"Rank #{rank} | "
                    f"Historical: {hist_pct:.1f}% → New: {new_pct:.1f}% | "
                    f"Change: {change_pct:+.1f}% ({change_abs:+.0f} containers) | "
                    f"⚠️ +{remaining:.0f} overflow containers assigned (max constraints applied - growth limit bypassed)"
                )
            else:
                notes[best_carrier] = (
                    f"Rank #{rank} | "
                    f"Historical: 0% (new carrier) → New: {new_pct:.1f}% | "
                    f"Allocated: {allocations[best_carrier]:.0f} containers | "
                    f"⚠️ +{remaining:.0f} overflow containers assigned (max constraints applied - growth limit bypassed)"
                )
        else:
            # Normal overflow cascading
            if hist_pct > 0:
                change_pct = new_pct - hist_pct
                change_abs = allocations[best_carrier] - ((hist_pct / 100) * total_containers)
                notes[best_carrier] = (
                    f"Rank #{rank} | "
                    f"Historical: {hist_pct:.1f}% → New: {new_pct:.1f}% | "
                    f"Change: {change_pct:+.1f}% ({change_abs:+.0f} containers) | "
                    f"⚠️ +{remaining:.0f} overflow containers assigned"
                )
            else:
                notes[best_carrier] = (
                    f"Rank #{rank} | "
                    f"Historical: 0% (new carrier) → New: {new_pct:.1f}% | "
                    f"Allocated: {allocations[best_carrier]:.0f} containers | "
                    f"⚠️ +{remaining:.0f} overflow containers assigned"
                )
        
        remaining = 0  # All volume now allocated
    
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
