"""
Historic Volume Analysis Module

This module analyzes carrier market share based on historical volume data.
It calculates what percentage of containers each carrier handled for the lanes
they serviced over the last 5 completed weeks (excluding current and future weeks).

Key Features:
- Filters out current and future weeks based on today's date
- Analyzes last 5 completed weeks only
- Calculates carrier market share per lane
- Shows volume trends over time
"""
from __future__ import annotations

from typing import List, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np


def get_current_week_number(reference_date: datetime | None = None) -> int:
    """
    Get the ISO week number for the reference date (default: today).
    
    Parameters
    ----------
    reference_date : datetime, optional
        The date to get the week number for. If None, uses today's date.
    
    Returns
    -------
    int
        ISO week number (1-53)
    """
    if reference_date is None:
        reference_date = datetime.now()
    
    return reference_date.isocalendar().week


def filter_historical_weeks(
    data: pd.DataFrame,
    week_column: str = "Week Number",
    reference_date: datetime | None = None,
) -> pd.DataFrame:
    """
    Filter data to include only historical (completed) weeks.
    
    Excludes the current week and any future weeks based on the reference date.
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data with week numbers
    week_column : str
        Name of the column containing week numbers
    reference_date : datetime, optional
        Reference date for determining current week. If None, uses today.
    
    Returns
    -------
    pd.DataFrame
        Filtered data containing only historical weeks
    """
    if data is None or data.empty:
        return pd.DataFrame()
    
    if week_column not in data.columns:
        raise ValueError(f"Column '{week_column}' not found in data")
    
    # Get current week number
    current_week = get_current_week_number(reference_date)
    
    # Filter to only include weeks before the current week
    historical_data = data[data[week_column] < current_week].copy()
    
    return historical_data


def get_last_n_weeks(
    data: pd.DataFrame,
    n_weeks: int = 5,
    week_column: str = "Week Number",
    reference_date: datetime | None = None,
) -> pd.DataFrame:
    """
    Get data for the last N completed weeks (excluding current and future).
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data with week numbers
    n_weeks : int, default=5
        Number of historical weeks to include
    week_column : str
        Name of the column containing week numbers
    reference_date : datetime, optional
        Reference date for determining current week. If None, uses today.
    
    Returns
    -------
    pd.DataFrame
        Data for the last N completed weeks
    """
    # First filter to only historical weeks
    historical_data = filter_historical_weeks(data, week_column, reference_date)
    
    if historical_data.empty:
        return pd.DataFrame()
    
    # Get the last N weeks from historical data
    historical_data = historical_data.sort_values(week_column, ascending=False)
    unique_weeks = historical_data[week_column].unique()
    
    # Take the most recent N weeks
    last_n_weeks = sorted(unique_weeks[:n_weeks])
    
    # Filter to only those weeks
    result = historical_data[historical_data[week_column].isin(last_n_weeks)].copy()
    
    return result


def calculate_carrier_volume_share(
    data: pd.DataFrame,
    *,
    n_weeks: int = 5,
    carrier_column: str = "Dray SCAC(FL)",
    container_column: str = "Container Count",
    week_column: str = "Week Number",
    lane_column: str = "Lane",
    category_column: str = "Category",
    reference_date: datetime | None = None,
) -> pd.DataFrame:
    """
    Calculate carrier market share based on historical volume.
    
    Analyzes the last N completed weeks to determine what percentage of
    containers each carrier handled for the lanes they serviced.
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data with carrier allocations and container counts
    n_weeks : int, default=5
        Number of historical weeks to analyze
    carrier_column : str
        Column identifying the carrier
    container_column : str
        Column with container counts
    week_column : str
        Column with week numbers
    lane_column : str
        Column identifying the lane
    category_column : str
        Column identifying the category (optional)
    reference_date : datetime, optional
        Reference date for determining current week. If None, uses today.
    
    Returns
    -------
    pd.DataFrame
        Carrier market share analysis with columns:
        - Carrier: Carrier identifier
        - Lane: Lane identifier
        - Category: Category (if present)
        - Total_Containers: Total containers handled
        - Lane_Total_Containers: Total containers in lane
        - Volume_Share_Pct: Percentage of lane volume handled by carrier
        - Weeks_Active: Number of weeks carrier was active
        - Avg_Weekly_Containers: Average containers per week
    """
    if data is None or data.empty:
        return pd.DataFrame()
    
    # Validate required columns
    required_columns = [carrier_column, container_column, week_column, lane_column]
    missing_columns = [col for col in required_columns if col not in data.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")
    
    # Get last N completed weeks
    historical_data = get_last_n_weeks(
        data, 
        n_weeks=n_weeks, 
        week_column=week_column,
        reference_date=reference_date
    )
    
    if historical_data.empty:
        return pd.DataFrame(columns=[
            carrier_column, lane_column, "Total_Containers", 
            "Lane_Total_Containers", "Volume_Share_Pct", 
            "Weeks_Active", "Avg_Weekly_Containers"
        ])
    
    # Ensure container count is numeric
    historical_data[container_column] = pd.to_numeric(
        historical_data[container_column], errors="coerce"
    ).fillna(0)
    
    # Determine grouping columns based on what's available
    group_columns = [carrier_column, lane_column]
    if category_column in historical_data.columns:
        group_columns.insert(1, category_column)
    
    # Calculate carrier volume by lane (and category if present)
    carrier_volume = historical_data.groupby(group_columns).agg({
        container_column: 'sum',
        week_column: 'nunique'
    }).reset_index()
    
    carrier_volume.columns = [*group_columns, 'Total_Containers', 'Weeks_Active']
    
    # Calculate total volume per lane (and category)
    lane_group = [lane_column]
    if category_column in historical_data.columns:
        lane_group.insert(0, category_column)
    
    lane_totals = historical_data.groupby(lane_group)[container_column].sum().reset_index()
    lane_totals.columns = [*lane_group, 'Lane_Total_Containers']
    
    # Merge to get lane totals
    result = carrier_volume.merge(lane_totals, on=lane_group, how='left')
    
    # Calculate volume share percentage
    result['Volume_Share_Pct'] = (
        result['Total_Containers'] / result['Lane_Total_Containers'] * 100
    ).fillna(0)
    
    # Calculate average weekly containers
    result['Avg_Weekly_Containers'] = (
        result['Total_Containers'] / result['Weeks_Active']
    ).fillna(0)
    
    # Round for readability
    result['Volume_Share_Pct'] = result['Volume_Share_Pct'].round(2)
    result['Avg_Weekly_Containers'] = result['Avg_Weekly_Containers'].round(1)
    
    # Sort by lane and volume share
    sort_columns = [lane_column, 'Volume_Share_Pct']
    if category_column in result.columns:
        sort_columns.insert(0, category_column)
    
    result = result.sort_values(sort_columns, ascending=[True] * (len(sort_columns) - 1) + [False])
    
    return result


def calculate_carrier_weekly_trends(
    data: pd.DataFrame,
    *,
    n_weeks: int = 5,
    carrier_column: str = "Dray SCAC(FL)",
    container_column: str = "Container Count",
    week_column: str = "Week Number",
    lane_column: str = "Lane",
    reference_date: datetime | None = None,
) -> pd.DataFrame:
    """
    Calculate carrier volume trends week by week.
    
    Shows how carrier volume has changed over the last N weeks for each lane.
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data with carrier allocations
    n_weeks : int, default=5
        Number of historical weeks to analyze
    carrier_column : str
        Column identifying the carrier
    container_column : str
        Column with container counts
    week_column : str
        Column with week numbers
    lane_column : str
        Column identifying the lane
    reference_date : datetime, optional
        Reference date for determining current week
    
    Returns
    -------
    pd.DataFrame
        Weekly trends with columns for each week showing container counts
    """
    if data is None or data.empty:
        return pd.DataFrame()
    
    # Get last N completed weeks
    historical_data = get_last_n_weeks(
        data,
        n_weeks=n_weeks,
        week_column=week_column,
        reference_date=reference_date
    )
    
    if historical_data.empty:
        return pd.DataFrame()
    
    # Ensure container count is numeric
    historical_data[container_column] = pd.to_numeric(
        historical_data[container_column], errors="coerce"
    ).fillna(0)
    
    # Pivot to show weeks as columns
    trends = historical_data.pivot_table(
        index=[carrier_column, lane_column],
        columns=week_column,
        values=container_column,
        aggfunc='sum',
        fill_value=0
    ).reset_index()
    
    # Rename week columns to be more readable
    week_columns = [col for col in trends.columns if isinstance(col, (int, np.integer))]
    column_mapping = {week: f"Week_{week}" for week in week_columns}
    trends = trends.rename(columns=column_mapping)
    
    # Calculate total and average
    week_col_names = [f"Week_{week}" for week in week_columns]
    trends['Total_Containers'] = trends[week_col_names].sum(axis=1)
    trends['Avg_Weekly'] = trends[week_col_names].mean(axis=1).round(1)
    
    # Sort by total containers
    trends = trends.sort_values('Total_Containers', ascending=False)
    
    return trends


def get_carrier_lane_participation(
    data: pd.DataFrame,
    *,
    n_weeks: int = 5,
    carrier_column: str = "Dray SCAC(FL)",
    week_column: str = "Week Number",
    lane_column: str = "Lane",
    reference_date: datetime | None = None,
) -> pd.DataFrame:
    """
    Analyze which weeks each carrier participated in for each lane.
    
    Shows carrier consistency and participation patterns.
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data with carrier allocations
    n_weeks : int, default=5
        Number of historical weeks to analyze
    carrier_column : str
        Column identifying the carrier
    week_column : str
        Column with week numbers
    lane_column : str
        Column identifying the lane
    reference_date : datetime, optional
        Reference date for determining current week
    
    Returns
    -------
    pd.DataFrame
        Participation analysis showing which weeks carrier served each lane
    """
    if data is None or data.empty:
        return pd.DataFrame()
    
    # Get last N completed weeks
    historical_data = get_last_n_weeks(
        data,
        n_weeks=n_weeks,
        week_column=week_column,
        reference_date=reference_date
    )
    
    if historical_data.empty:
        return pd.DataFrame()
    
    # Create participation matrix (1 if carrier was active, 0 otherwise)
    participation = historical_data.groupby([carrier_column, lane_column, week_column]).size().reset_index(name='Active')
    participation['Active'] = 1
    
    # Pivot to show weeks as columns
    participation_matrix = participation.pivot_table(
        index=[carrier_column, lane_column],
        columns=week_column,
        values='Active',
        fill_value=0
    ).reset_index()
    
    # Rename week columns
    week_columns = [col for col in participation_matrix.columns if isinstance(col, (int, np.integer))]
    column_mapping = {week: f"Week_{week}_Active" for week in week_columns}
    participation_matrix = participation_matrix.rename(columns=column_mapping)
    
    # Calculate participation rate
    week_col_names = [f"Week_{week}_Active" for week in week_columns]
    participation_matrix['Weeks_Participated'] = participation_matrix[week_col_names].sum(axis=1)
    participation_matrix['Participation_Rate_Pct'] = (
        participation_matrix['Weeks_Participated'] / len(week_columns) * 100
    ).round(1)
    
    return participation_matrix


__all__ = [
    "get_current_week_number",
    "filter_historical_weeks",
    "get_last_n_weeks",
    "calculate_carrier_volume_share",
    "calculate_carrier_weekly_trends",
    "get_carrier_lane_participation",
]
