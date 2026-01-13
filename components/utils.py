"""
Shared utility functions for the Carrier Tender Optimization Dashboard.

This module consolidates commonly used helper functions to avoid duplication
across the codebase.
"""
import pandas as pd
import numpy as np
import streamlit as st
from typing import Dict, List, Optional, Any


# ==================== RATE COLUMN UTILITIES ====================

def get_rate_columns() -> Dict[str, str]:
    """
    Get the appropriate rate column names based on selected rate type.
    
    Returns:
        Dict with 'rate' and 'total_rate' keys mapping to column names.
    """
    rate_type = st.session_state.get('rate_type', 'Base Rate')
    
    if rate_type == 'CPC':
        return {'rate': 'CPC', 'total_rate': 'Total CPC'}
    return {'rate': 'Base Rate', 'total_rate': 'Total Rate'}


# ==================== CONTAINER UTILITIES ====================

def count_containers(container_str: Any) -> int:
    """
    Count the number of containers in a comma-separated string.
    
    Args:
        container_str: Comma-separated container IDs or any value.
        
    Returns:
        Number of containers found.
    """
    if pd.isna(container_str) or not str(container_str).strip():
        return 0
    return len([c.strip() for c in str(container_str).split(',') if c.strip()])


def parse_container_ids(container_str: Any) -> List[str]:
    """
    Parse comma-separated container IDs from string.
    
    Args:
        container_str: Comma-separated container IDs.
        
    Returns:
        List of individual container IDs.
    """
    if pd.isna(container_str) or not str(container_str).strip():
        return []
    return [c.strip() for c in str(container_str).split(',') if c.strip()]


def join_container_ids(container_list: List[str]) -> str:
    """
    Join list of container IDs into comma-separated string.
    
    Args:
        container_list: List of container IDs.
        
    Returns:
        Comma-separated string of container IDs.
    """
    return ', '.join(str(c) for c in container_list if c)


def concat_and_dedupe_containers(values: pd.Series) -> str:
    """
    Concatenate container numbers from multiple rows and remove duplicates.
    
    Args:
        values: Series of comma-separated container strings.
        
    Returns:
        Deduplicated comma-separated container string.
    """
    all_containers = []
    for v in values:
        if pd.notna(v) and str(v).strip():
            all_containers.extend(parse_container_ids(v))
    # Deduplicate while preserving order
    unique_containers = list(dict.fromkeys(all_containers))
    return ', '.join(unique_containers)


# ==================== DATA GROUPING UTILITIES ====================

def get_grouping_columns(
    data: pd.DataFrame, 
    base_cols: Optional[List[str]] = None
) -> List[str]:
    """
    Get grouping columns for aggregation, including optional columns if present.
    
    Args:
        data: DataFrame to check for column availability.
        base_cols: Base columns to include. Defaults to standard grouping.
        
    Returns:
        List of column names that exist in the data.
    """
    if base_cols is None:
        base_cols = ['Discharged Port', 'Lane', 'Facility', 'Week Number']
    
    cols = base_cols.copy()
    
    # Add Category at the beginning if it exists
    if 'Category' in data.columns and 'Category' not in cols:
        cols.insert(0, 'Category')
    
    # Add SSL after Category if it exists
    if 'SSL' in data.columns and 'SSL' not in cols:
        cols.insert(1, 'SSL')
    
    # Add Vessel after SSL if it exists
    if 'Vessel' in data.columns and 'Vessel' not in cols:
        cols.insert(2, 'Vessel')
    
    # Add Terminal if it exists
    if 'Terminal' in data.columns and 'Terminal' not in cols:
        cols.append('Terminal')
    
    return [c for c in cols if c in data.columns]


def normalize_facility_code(facility_str: Any) -> str:
    """
    Normalize facility code to first 4 characters for comparison.
    
    Examples: 'HGR6-5' -> 'HGR6', 'IUSF' -> 'IUSF', 'GBPT-3' -> 'GBPT'
    
    Args:
        facility_str: Facility code string.
        
    Returns:
        Normalized 4-character facility code.
    """
    if pd.isna(facility_str) or not str(facility_str).strip():
        return ''
    fc = str(facility_str).strip().upper()
    return fc[:4] if len(fc) >= 4 else fc


# ==================== VALUE FORMATTING UTILITIES ====================

def safe_numeric(value: Any) -> float:
    """
    Convert any value to float, stripping formatting if needed.
    
    Args:
        value: Value to convert (can be formatted string like '$1,234.56').
        
    Returns:
        Float value, or 0.0 if conversion fails.
    """
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace('$', '').replace(',', '').replace('%', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def format_currency(value: Any) -> str:
    """
    Format a value as currency.
    
    Args:
        value: Numeric value to format.
        
    Returns:
        Formatted currency string or 'N/A'.
    """
    if pd.notna(value) and value != 0:
        return f"${value:,.2f}"
    return "N/A"


def format_percentage(value: Any) -> str:
    """
    Format a value as percentage.
    
    Args:
        value: Numeric value to format (0.5 = 50%).
        
    Returns:
        Formatted percentage string or 'N/A'.
    """
    if pd.notna(value):
        return f"{value:.1%}"
    return "N/A"


def format_number(value: Any, decimals: int = 0) -> str:
    """
    Format a number with thousands separators.
    
    Args:
        value: Numeric value to format.
        decimals: Number of decimal places.
        
    Returns:
        Formatted number string.
    """
    if pd.notna(value):
        return f"{value:,.{decimals}f}"
    return "N/A"


# ==================== DATAFRAME UTILITIES ====================

def filter_excluded_carrier_facility_rows(
    df: pd.DataFrame, 
    exclusions_dict: Dict[str, set],
    carrier_col: str = 'Dray SCAC(FL)'
) -> pd.DataFrame:
    """
    Filter out rows where a carrier is excluded from a specific facility.
    
    For scenario calculations, prevents certain carriers from being selected
    at certain facilities.
    
    Args:
        df: DataFrame to filter.
        exclusions_dict: Dict mapping carrier names to sets of excluded facility codes.
        carrier_col: Column name for carrier identification.
        
    Returns:
        Filtered DataFrame.
    """
    if not exclusions_dict or df.empty or 'Facility' not in df.columns:
        return df
    
    keep_mask = pd.Series(True, index=df.index)
    
    for carrier, excluded_facilities in exclusions_dict.items():
        if not excluded_facilities:
            continue
        for excluded_fc in excluded_facilities:
            carrier_match = df[carrier_col] == carrier
            facility_match = df['Facility'].str[:4].str.upper() == excluded_fc.upper()[:4]
            keep_mask &= ~(carrier_match & facility_match)
    
    return df[keep_mask].copy()
