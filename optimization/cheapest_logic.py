"""Cheapest cost allocation logic - DEPRECATED

⚠️ DEPRECATION NOTICE ⚠️
This module is deprecated and no longer used in the application.
The cheapest cost logic has been replaced with simpler aggregation
directly in the metrics.py module.

This file is retained for reference only and may be removed in a future version.

Historical Purpose:
This module provided utilities to build a "cheapest cost" scenario where,
for each lane/week/category combination, 100% of the containers are assigned to
the carrier with the lowest rate. The output mirrors the current selection table
so it can be plugged into the dashboard.

Current Implementation:
The cheapest cost scenario is now calculated inline in metrics.py by:
1. Grouping data by Category, Week Number, and Lane
2. Finding the carrier with the minimum rate in each group
3. Assigning all containers in that group to the cheapest carrier
4. Calculating total cost based on the cheapest carrier's rate
"""
from __future__ import annotations

import warnings

warnings.warn(
    "The cheapest_logic module is deprecated and no longer used. "
    "Cheapest cost calculations are now performed inline in metrics.py.",
    DeprecationWarning,
    stacklevel=2
)

from typing import Iterable, List

import pandas as pd


# Columns considered when grouping carriers that share the same demand slice.
DEFAULT_GROUP_COLUMNS: List[str] = [
    "Discharged Port",
    "Category",
    "Lane",
    "Facility",
    "Week Number",
]


def _prepare_group_columns(data: pd.DataFrame, extras: Iterable[str] | None = None) -> List[str]:
    """Return the subset of grouping columns that are actually present in *data*."""
    columns: List[str] = [col for col in DEFAULT_GROUP_COLUMNS if col in data.columns]
    if extras:
        columns.extend(col for col in extras if col in data.columns and col not in columns)
    if not columns:
        raise ValueError(
            "Data must include at least one of the grouping columns: "
            f"{', '.join(DEFAULT_GROUP_COLUMNS)}"
        )
    return columns


def allocate_to_cheapest_carrier(
    data: pd.DataFrame,
    *,
    carrier_column: str = "Dray SCAC(FL)",
    container_column: str = "Container Count",
    rate_column: str = "Base Rate",
    cheapest_rate_column: str = "Cheapest Base Rate",
    container_numbers_column: str = "Container Numbers",
) -> pd.DataFrame:
    """Allocate all volume for each lane/week/category to the cheapest carrier.

    Parameters
    ----------
    data:
        Filtered dataset that contains carrier-level allocations.
    carrier_column:
        Name of the column identifying the carrier/SCAC.
    container_column:
        Column holding the number of containers already assigned to the row.
    rate_column:
        Column with the current rate for each carrier.
    cheapest_rate_column:
        Column with the pre-calculated cheapest rate available for that lane.
        This should be the minimum rate across ALL carriers for that lane.
    container_numbers_column:
        Optional text column that enumerates the containers; when present the
        resulting table concatenates all values found in the source group.

    Returns
    -------
    pandas.DataFrame
        A trimmed table that keeps exactly one row per grouping key (lane/week/
        category) representing the cheapest carrier with the full container
        total assigned to it. The structure mirrors the input table so it can
        be displayed just like the "Current Selection" view.
    """
    if data is None or data.empty:
        return pd.DataFrame(columns=data.columns if data is not None else [])

    if cheapest_rate_column not in data.columns:
        raise ValueError(
            f"Column '{cheapest_rate_column}' is required to compute the cheapest allocation."
        )
    if carrier_column not in data.columns:
        raise ValueError(
            f"Column '{carrier_column}' is required to identify carriers for allocation."
        )
    if container_column not in data.columns:
        raise ValueError(
            f"Column '{container_column}' is required to sum container totals."
        )

    group_columns = _prepare_group_columns(data)

    working = data.copy()

    # Ensure numeric comparisons are well-defined.
    working[cheapest_rate_column] = pd.to_numeric(working[cheapest_rate_column], errors="coerce")
    working[container_column] = pd.to_numeric(working[container_column], errors="coerce").fillna(0)
    
    if rate_column in working.columns:
        working[rate_column] = pd.to_numeric(working[rate_column], errors="coerce")

    if container_numbers_column in working.columns:
        working[container_numbers_column] = working[container_numbers_column].fillna("")

    # For each group, find the carrier that matches the cheapest rate
    # The cheapest_rate_column should already contain the minimum rate for that lane
    # So we find the carrier whose rate equals the cheapest rate
    
    # First, identify which carrier has the cheapest rate in each group
    # Sort by rate to ensure we get the cheapest carrier first in case of ties
    working["__rate_sort"] = working[cheapest_rate_column].fillna(float("inf"))
    
    # Add carrier name for tie-breaking (alphabetical)
    working["__carrier_sort"] = working[carrier_column].astype(str)
    
    working = working.sort_values(["__rate_sort", "__carrier_sort"], ascending=[True, True])

    # Get the first (cheapest) carrier for each group
    cheapest_carriers = working.groupby(group_columns, as_index=False).first().copy()

    # Sum all containers in each group and assign 100% to the selected carrier row.
    container_totals = (
        working
        .groupby(group_columns, as_index=False)[container_column]
        .sum()
        .rename(columns={container_column: "__total_containers"})
    )
    cheapest_carriers = cheapest_carriers.merge(container_totals, on=group_columns, how="left")
    cheapest_carriers[container_column] = cheapest_carriers["__total_containers"].fillna(0)

    if container_numbers_column in working.columns:
        container_number_map = (
            working.groupby(group_columns)[container_numbers_column]
            .apply(lambda values: ", ".join(str(v) for v in values if str(v).strip()))
            .reset_index(name="__container_numbers")
        )
        cheapest_carriers = cheapest_carriers.merge(
            container_number_map,
            on=group_columns,
            how="left",
        )
        cheapest_carriers[container_numbers_column] = cheapest_carriers["__container_numbers"].fillna("")
        
        # CRITICAL FIX: Recalculate Container Count based on actual container IDs
        def count_containers_in_string(container_str):
            """Count actual container IDs in a comma-separated string"""
            if pd.isna(container_str) or not str(container_str).strip():
                return 0
            containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
            return len(containers)
        
        cheapest_carriers["__actual_count"] = cheapest_carriers[container_numbers_column].apply(count_containers_in_string)
        # Override the summed count with actual count
        cheapest_carriers[container_column] = cheapest_carriers["__actual_count"]

    # Calculate total cost based on cheapest rate × total containers
    # The cheapest_rate_column already contains the cheapest rate for this lane
    cheapest_carriers["Total Cost"] = (
        cheapest_carriers[cheapest_rate_column].fillna(0) * cheapest_carriers[container_column]
    )
    
    # Also recalculate standard Total Rate and Total CPC columns if Base Rate/CPC exist
    if "Base Rate" in cheapest_carriers.columns:
        cheapest_carriers["Total Rate"] = (
            pd.to_numeric(cheapest_carriers["Base Rate"], errors="coerce").fillna(0)
            * cheapest_carriers[container_column]
        )
    if "CPC" in cheapest_carriers.columns:
        cheapest_carriers["Total CPC"] = (
            pd.to_numeric(cheapest_carriers["CPC"], errors="coerce").fillna(0)
            * cheapest_carriers[container_column]
        )

    cheapest_carriers["Allocation Strategy"] = "Cheapest Carrier"

    # Clean helper columns and preserve original ordering.
    helper_columns = {
        "__rate_sort",
        "__carrier_sort",
        "__total_containers",
        "__container_numbers",
        "__actual_count",
    }
    for col in helper_columns:
        if col in cheapest_carriers.columns:
            cheapest_carriers = cheapest_carriers.drop(columns=col)

    ordered_columns: List[str] = [
        *(col for col in data.columns if col in cheapest_carriers.columns),
    ]
    if "Total Cost" not in ordered_columns:
        ordered_columns.append("Total Cost")
    if "Allocation Strategy" not in ordered_columns:
        ordered_columns.append("Allocation Strategy")

    return cheapest_carriers[ordered_columns]


__all__ = [
    "allocate_to_cheapest_carrier",
]
