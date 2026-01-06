"""
Linear Programming Optimization for Carrier Allocation

This module implements a weighted optimization approach that balances:
- Cost optimization (default 70% weight)
- Performance optimization (default 30% weight)

The optimization uses linear programming to find the optimal allocation of containers
to carriers while minimizing a weighted objective function.
"""
from __future__ import annotations

from typing import List, Tuple
import pandas as pd
import numpy as np
from pulp import LpProblem, LpMinimize, LpVariable, lpSum, LpStatus, value


# Default grouping columns for optimization
DEFAULT_GROUP_COLUMNS: List[str] = [
    "Discharged Port",
    "Category",
    "SSL",
    "Lane",
    "Facility",
    "Terminal",
    "Week Number",
]


def _prepare_group_columns(data: pd.DataFrame) -> List[str]:
    """Return the subset of grouping columns that are actually present in data."""
    columns: List[str] = [col for col in DEFAULT_GROUP_COLUMNS if col in data.columns]
    if not columns:
        raise ValueError(
            "Data must include at least one of the grouping columns: "
            f"{', '.join(DEFAULT_GROUP_COLUMNS)}"
        )
    return columns


def _normalize_values(values: pd.Series, lower_is_better: bool = True) -> pd.Series:
    """
    Normalize values to 0-1 scale.
    
    Parameters
    ----------
    values : pd.Series
        Values to normalize
    lower_is_better : bool
        If True, lower values get scores closer to 0 (better)
        If False, higher values get scores closer to 1 (better)
    
    Returns
    -------
    pd.Series
        Normalized values between 0 and 1
    """
    min_val = values.min()
    max_val = values.max()
    
    if min_val == max_val:
        # All values are the same
        return pd.Series(0.5, index=values.index)
    
    # Vectorized normalization
    normalized = (values - min_val) / (max_val - min_val)
    
    if not lower_is_better:
        # For performance, higher is better, so invert
        normalized = 1 - normalized
    
    return normalized


def optimize_carrier_allocation(
    data: pd.DataFrame,
    *,
    cost_weight: float = 0.7,
    performance_weight: float = 0.3,
    carrier_column: str = "Dray SCAC(FL)",
    container_column: str = "Container Count",
    rate_column: str = "Base Rate",
    performance_column: str = "Performance_Score",
    container_numbers_column: str = "Container Numbers",
) -> pd.DataFrame:
    """
    Optimize carrier allocation using linear programming with weighted objectives.
    
    This function allocates containers to carriers by minimizing a weighted combination
    of cost and negative performance. The optimization ensures that:
    1. All containers in each lane/week/category are allocated
    2. Each carrier can only receive containers if they serve that lane
    3. The allocation minimizes: cost_weight * normalized_cost + performance_weight * (1 - normalized_performance)
    
    Parameters
    ----------
    data : pd.DataFrame
        Filtered dataset containing carrier-level allocations with costs and performance scores
    cost_weight : float, default=0.7
        Weight for cost optimization (0 to 1). Higher values prioritize lower costs.
    performance_weight : float, default=0.3
        Weight for performance optimization (0 to 1). Higher values prioritize higher performance.
    carrier_column : str
        Name of the column identifying the carrier/SCAC
    container_column : str
        Column holding the number of containers
    rate_column : str
        Column with the rate/cost per container
    performance_column : str
        Column with performance score (higher is better, should be 0-1 scale)
    container_numbers_column : str
        Optional column with container identifiers
    
    Returns
    -------
    pd.DataFrame
        Optimized allocation with containers assigned to carriers based on weighted objectives
    
    Notes
    -----
    - Weights should sum to 1.0 for interpretability, but will be normalized if they don't
    - Performance scores are expected to be in 0-1 range (e.g., 0.85 for 85%)
    - The optimization is performed independently for each lane/week/category group
    """
    if data is None or data.empty:
        return pd.DataFrame(columns=data.columns if data is not None else [])
    
    # Validate weights
    total_weight = cost_weight + performance_weight
    if total_weight == 0:
        raise ValueError("At least one weight must be non-zero")
    
    # Normalize weights to sum to 1
    cost_weight = cost_weight / total_weight
    performance_weight = performance_weight / total_weight
    
    # Validate required columns
    required_columns = [carrier_column, container_column, rate_column]
    missing_columns = [col for col in required_columns if col not in data.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")
    
    # Check if performance column exists
    has_performance = performance_column in data.columns
    if not has_performance and performance_weight > 0:
        print(f"Warning: Performance column '{performance_column}' not found. Using cost-only optimization.")
        performance_weight = 0
        cost_weight = 1.0
    
    group_columns = _prepare_group_columns(data)
    
    # Convert to numeric once and handle missing values upfront
    working = data.copy()
    working[container_column] = pd.to_numeric(working[container_column], errors="coerce").fillna(0)
    working[rate_column] = pd.to_numeric(working[rate_column], errors="coerce").fillna(0)
    
    if has_performance:
        working[performance_column] = pd.to_numeric(working[performance_column], errors="coerce").fillna(0).clip(0, 1)
    
    if container_numbers_column in working.columns:
        working[container_numbers_column] = working[container_numbers_column].fillna("")
    
    # Prepare results storage
    optimized_allocations = []
    
    # Group by lane/week/category and optimize each group
    for group_key, group_data in working.groupby(group_columns, dropna=False):
        optimized_group = _optimize_single_group(
            group_data=group_data,
            group_key=group_key,
            group_columns=group_columns,
            cost_weight=cost_weight,
            performance_weight=performance_weight,
            carrier_column=carrier_column,
            container_column=container_column,
            rate_column=rate_column,
            performance_column=performance_column if has_performance else None,
            container_numbers_column=container_numbers_column,
        )
        
        if optimized_group is not None and not optimized_group.empty:
            optimized_allocations.append(optimized_group)
    
    if not optimized_allocations:
        return pd.DataFrame(columns=data.columns)
    
    # Combine all optimized groups
    result = pd.concat(optimized_allocations, ignore_index=True)
    
    # Add allocation strategy label
    result["Allocation Strategy"] = f"Optimized (Cost: {cost_weight:.0%}, Performance: {performance_weight:.0%})"
    
    # Reorder columns to match input
    ordered_columns: List[str] = [
        *(col for col in data.columns if col in result.columns),
    ]
    if "Allocation Strategy" not in ordered_columns:
        ordered_columns.append("Allocation Strategy")
    
    return result[ordered_columns]


def _optimize_single_group(
    group_data: pd.DataFrame,
    group_key: Tuple,
    group_columns: List[str],
    cost_weight: float,
    performance_weight: float,
    carrier_column: str,
    container_column: str,
    rate_column: str,
    performance_column: str | None,
    container_numbers_column: str,
) -> pd.DataFrame | None:
    """
    Optimize carrier allocation for a single lane/week/category group using LP.
    
    This internal function sets up and solves a linear program for one group.
    """
    if group_data.empty:
        return None
    
    # Get total containers to allocate
    total_containers = group_data[container_column].sum()
    
    if total_containers == 0:
        return None
    
    # Get unique carriers in this group
    carriers = group_data[carrier_column].unique().tolist()
    
    if len(carriers) == 0:
        return None
    
    # Collect all container numbers for this group
    all_container_numbers = []
    if container_numbers_column in group_data.columns:
        for containers_str in group_data[container_numbers_column]:
            if pd.notna(containers_str) and str(containers_str).strip():
                all_container_numbers.extend([c.strip() for c in str(containers_str).split(',') if c.strip()])
    
    # CRITICAL: Use actual container ID count as the source of truth
    # This ensures allocations are based on real container IDs, not potentially mismatched Container Count values
    if all_container_numbers:
        actual_container_count = len(all_container_numbers)
        if actual_container_count != total_containers:
            total_containers = actual_container_count
    
    # If only one carrier, assign all containers to it
    if len(carriers) == 1:
        result = group_data.copy()
        result[container_column] = total_containers
        
        # Consolidate container numbers if present
        if container_numbers_column in result.columns:
            all_containers = ", ".join(
                str(v) for v in group_data[container_numbers_column] if str(v).strip()
            )
            result[container_numbers_column] = all_containers
        
        # Calculate total cost
        carrier_rate = group_data[rate_column].iloc[0]
        result["Total Rate"] = carrier_rate * total_containers
        
        return result.head(1)
    
    # Create carrier-indexed data for easier lookup
    carrier_data = {}
    for idx, row in group_data.iterrows():
        carrier = row[carrier_column]
        carrier_data[carrier] = {
            'rate': row[rate_column],
            'performance': row[performance_column] if performance_column else 0,
            'original_row': row,
        }
    
    # Normalize costs and performance within this group
    rates = np.array([carrier_data[c]['rate'] for c in carriers])
    normalized_costs = _normalize_values(pd.Series(rates, index=carriers), lower_is_better=True)
    
    if performance_column:
        performances = np.array([carrier_data[c]['performance'] for c in carriers])
        # For performance, higher is better, but we want to minimize the objective
        # So we use (1 - performance) in the objective
        # Normalize so that best performance = 0 cost, worst performance = 1 cost
        normalized_perf_costs = _normalize_values(pd.Series(performances, index=carriers), lower_is_better=False)
    else:
        normalized_perf_costs = pd.Series(0, index=carriers)
    
    # Create LP problem
    prob = LpProblem(f"Carrier_Optimization_Group", LpMinimize)
    
    # Decision variables: containers allocated to each carrier
    allocation_vars = {
        carrier: LpVariable(f"alloc_{carrier}", lowBound=0, upBound=total_containers, cat="Continuous")
        for carrier in carriers
    }
    
    # Objective: minimize weighted combination of normalized cost and (1-performance)
    objective = lpSum([
        (cost_weight * normalized_costs[carrier] + performance_weight * normalized_perf_costs[carrier]) 
        * allocation_vars[carrier]
        for carrier in carriers
    ])
    prob += objective
    
    # Constraint: all containers must be allocated
    prob += lpSum([allocation_vars[carrier] for carrier in carriers]) == total_containers
    
    # Solve the problem
    prob.solve()
    
    # Check if solution is optimal
    if LpStatus[prob.status] != "Optimal":
        # If optimization fails, fall back to cheapest carrier
        cheapest_carrier = min(carriers, key=lambda c: carrier_data[c]['rate'])
        result = group_data[group_data[carrier_column] == cheapest_carrier].copy()
        result[container_column] = total_containers
        
        if container_numbers_column in result.columns:
            all_containers = ", ".join(
                str(v) for v in group_data[container_numbers_column] if str(v).strip()
            )
            result[container_numbers_column] = all_containers
        
        result["Total Rate"] = carrier_data[cheapest_carrier]['rate'] * total_containers
        return result.head(1)
    
    # Extract solution
    allocations = {carrier: value(allocation_vars[carrier]) for carrier in carriers}
    
    # Filter out carriers with negligible allocation (< 0.5 containers)
    significant_allocations = {
        carrier: alloc for carrier, alloc in allocations.items() if alloc >= 0.5
    }
    
    if not significant_allocations:
        # No significant allocation, assign to cheapest
        cheapest_carrier = min(carriers, key=lambda c: carrier_data[c]['rate'])
        significant_allocations = {cheapest_carrier: total_containers}
    
    # Build result DataFrame
    result_rows = []
    
    # Use the container numbers we already collected at the start of the function
    # (all_container_numbers was collected when we validated total_containers)
    
    for carrier, allocated_count in significant_allocations.items():
        # Round to nearest integer
        allocated_count = round(allocated_count)
        
        if allocated_count == 0:
            continue
        
        row = carrier_data[carrier]['original_row'].copy()
        row[container_column] = allocated_count
        
        # Calculate total cost
        row["Total Rate"] = carrier_data[carrier]['rate'] * allocated_count
        
        # Assign Container Numbers based on allocated_count (not proportion)
        # allocated_count is already the exact number of containers this carrier should receive
        if all_container_numbers:
            # Assign exactly allocated_count container IDs (or all remaining if less available)
            num_to_assign = min(int(allocated_count), len(all_container_numbers))
            assigned_containers = all_container_numbers[:num_to_assign]
            all_container_numbers = all_container_numbers[num_to_assign:]
            row[container_numbers_column] = ", ".join(assigned_containers)
        
        result_rows.append(row)
    
    # Assign any remaining containers due to rounding
    if all_container_numbers and result_rows:
        result_rows[0][container_numbers_column] = (
            str(result_rows[0].get(container_numbers_column, "")) + ", " + ", ".join(all_container_numbers)
        ).strip(", ")
    
    if not result_rows:
        return None
    
    result = pd.DataFrame(result_rows)
    
    # CRITICAL: Recalculate Container Count from Container Numbers after assignment
    # This ensures Container Count always matches the actual number of IDs in Container Numbers
    if container_numbers_column in result.columns:
        def count_containers_in_string(container_str):
            """Count actual container IDs in a comma-separated string"""
            if pd.isna(container_str) or not str(container_str).strip():
                return 0
            containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
            return len(containers)
        
        result[container_column] = result[container_numbers_column].apply(count_containers_in_string)
        
        # CRITICAL: Recalculate Total Cost using the NEW Container Count
        # Support both Base Rate and CPC for dynamic rate selection
        if 'Base Rate' in result.columns:
            result['Total Rate'] = result['Base Rate'] * result[container_column]
        if 'CPC' in result.columns:
            result['Total CPC'] = result['CPC'] * result[container_column]
    
    return result


__all__ = [
    "optimize_carrier_allocation",
]
