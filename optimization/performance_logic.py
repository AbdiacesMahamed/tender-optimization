"""Performance allocation helpers.

This module provides utilities to build a "highest performance" scenario where,
for each lane/week/category combination, 100% of the containers are assigned to
the carrier with the strongest performance score. The output closely mirrors the
current selection table so it can be plugged into the dashboard when you're
ready to surface the scenario.
"""
from __future__ import annotations

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


def allocate_to_highest_performance(
    data: pd.DataFrame,
    *,
    carrier_column: str = "Dray SCAC(FL)",
    container_column: str = "Container Count",
    performance_column: str = "Performance_Score",
    container_numbers_column: str = "Container Numbers",
) -> pd.DataFrame:
    """Allocate all volume for each lane/week/category to the top-performing carrier.

    Parameters
    ----------
    data:
        Filtered dataset that still contains carrier-level allocations.
    carrier_column:
        Name of the column identifying the carrier/SCAC.
    container_column:
        Column holding the number of containers already assigned to the row.
    performance_column:
        Column with a numeric performance score where higher is better.
    container_numbers_column:
        Optional text column that enumerates the containers; when present the
        resulting table concatenates all values found in the source group.

    Returns
    -------
    pandas.DataFrame
        A trimmed table that keeps exactly one row per grouping key (lane/week/
        category) representing the highest-performing carrier with the full
        container total assigned to it. The structure mirrors the input table so
        it can be displayed just like the "Current Selection" view.
    """
    if data is None or data.empty:
        return pd.DataFrame(columns=data.columns if data is not None else [])

    if performance_column not in data.columns:
        raise ValueError(
            f"Column '{performance_column}' is required to compute the performance allocation."
        )
    if carrier_column not in data.columns:
        raise ValueError(
            f"Column '{carrier_column}' is required to identify carriers for allocation."
        )
    if container_column not in data.columns:
        raise ValueError(
            f"Column '{container_column}' is required to sum container totals."
        )

    group_columns = _prepare_group_columns(data, extras=[carrier_column])

    working = data.copy()

    # Ensure numeric comparisons are well-defined.
    working[performance_column] = pd.to_numeric(working[performance_column], errors="coerce")
    working[container_column] = pd.to_numeric(working[container_column], errors="coerce").fillna(0)

    if container_numbers_column in working.columns:
        working[container_numbers_column] = working[container_numbers_column].fillna("")

    # Sorting helpers for tie-breaking: higher performance first, then lower cost/rate if available.
    sort_columns: List[str] = ["__perf_sort"]
    ascending_flags: List[bool] = [False]
    working["__perf_sort"] = working[performance_column].fillna(float("-inf"))

    if "Total Rate" in working.columns:
        working["__cost_sort"] = pd.to_numeric(working["Total Rate"], errors="coerce").fillna(float("inf"))
        sort_columns.append("__cost_sort")
        ascending_flags.append(True)
    elif "Total CPC" in working.columns:
        working["__cost_sort"] = pd.to_numeric(working["Total CPC"], errors="coerce").fillna(float("inf"))
        sort_columns.append("__cost_sort")
        ascending_flags.append(True)

    if "Base Rate" in working.columns:
        working["__rate_sort"] = pd.to_numeric(working["Base Rate"], errors="coerce").fillna(float("inf"))
        sort_columns.append("__rate_sort")
        ascending_flags.append(True)
    elif "CPC" in working.columns:
        working["__rate_sort"] = pd.to_numeric(working["CPC"], errors="coerce").fillna(float("inf"))
        sort_columns.append("__rate_sort")
        ascending_flags.append(True)

    # Stable ordering for deterministic output when all other metrics tie.
    working["__carrier_sort"] = working[carrier_column].astype(str)
    sort_columns.append("__carrier_sort")
    ascending_flags.append(True)

    working = working.sort_values(sort_columns, ascending=ascending_flags)

    # Identify the best carrier per lane/week/category (with tie-breaking applied above).
    best_carriers = working.groupby(_prepare_group_columns(data), as_index=False).head(1).copy()

    # Sum all containers in each group and assign 100% to the selected carrier row.
    container_totals = (
        working
        .groupby(_prepare_group_columns(data), as_index=False)[container_column]
        .sum()
        .rename(columns={container_column: "__total_containers"})
    )
    best_carriers = best_carriers.merge(container_totals, on=_prepare_group_columns(data), how="left")
    best_carriers[container_column] = best_carriers["__total_containers"].fillna(0)

    if container_numbers_column in working.columns:
        # Store original summed count for debugging
        best_carriers["__original_summed_count"] = best_carriers[container_column].copy()
        
        container_number_map = (
            working.groupby(_prepare_group_columns(data))[container_numbers_column]
            .apply(lambda values: ", ".join(str(v) for v in values if str(v).strip()))
            .reset_index(name="__container_numbers")
        )
        best_carriers = best_carriers.merge(
            container_number_map,
            on=_prepare_group_columns(data),
            how="left",
        )
        best_carriers[container_numbers_column] = best_carriers["__container_numbers"].fillna("")
        
        # CRITICAL FIX: Recalculate Container Count based on actual container IDs in the concatenated string
        def count_containers_in_string(container_str):
            """Count actual container IDs in a comma-separated string"""
            if pd.isna(container_str) or not str(container_str).strip():
                return 0
            containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
            return len(containers)
        
        best_carriers["__actual_count"] = best_carriers[container_numbers_column].apply(count_containers_in_string)
        
        # Use actual count instead of summed count
        best_carriers[container_column] = best_carriers["__actual_count"]

    # Recalculate total rate columns where possible so costs reflect the new allocation.
    if "Base Rate" in best_carriers.columns:
        best_carriers["Total Rate"] = (
            pd.to_numeric(best_carriers["Base Rate"], errors="coerce").fillna(0)
            * best_carriers[container_column]
        )
    if "CPC" in best_carriers.columns:
        best_carriers["Total CPC"] = (
            pd.to_numeric(best_carriers["CPC"], errors="coerce").fillna(0)
            * best_carriers[container_column]
        )

    best_carriers["Allocation Strategy"] = "Highest Performance Carrier"

    # Clean helper columns and preserve original ordering.
    helper_columns = {
        "__perf_sort",
        "__cost_sort",
        "__rate_sort",
        "__carrier_sort",
        "__total_containers",
        "__container_numbers",
        "__actual_count",
        "__original_summed_count",
    }
    for col in helper_columns:
        if col in best_carriers.columns:
            best_carriers = best_carriers.drop(columns=col)

    ordered_columns: List[str] = [
        *(col for col in data.columns if col in best_carriers.columns),
    ]
    if "Allocation Strategy" not in ordered_columns:
        ordered_columns.append("Allocation Strategy")

    return best_carriers[ordered_columns]


__all__ = [
    "allocate_to_highest_performance",
]
