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


def deduplicate_containers_per_lane_week(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate container IDs across carriers within the same lane/week.
    
    A physical container can only belong to ONE carrier per lane/week (zero sum).
    If the same container appears under 2 carriers in the same lane/week,
    it is kept under the first carrier encountered and removed from the second.
    
    Container Count and Total Rate/Total CPC are recalculated after dedup.
    
    Args:
        df: DataFrame with Container Numbers, Week Number, and optionally Lane columns.
        
    Returns:
        DataFrame with deduplicated containers per lane/week.
    """
    if 'Container Numbers' not in df.columns or 'Week Number' not in df.columns:
        return df
    
    result = df.copy().reset_index(drop=True)
    lane_col = 'Lane' if 'Lane' in result.columns else None
    seen = {}  # {(week, lane): set of container IDs already assigned}
    
    for idx in result.index:
        week = result.at[idx, 'Week Number']
        lane = result.at[idx, lane_col] if lane_col else ''
        cn_str = result.at[idx, 'Container Numbers']
        if pd.isna(cn_str) or not str(cn_str).strip():
            continue
        key = (week, lane)
        if key not in seen:
            seen[key] = set()
        ids = [c.strip() for c in str(cn_str).split(',') if c.strip()]
        unique_ids = [c for c in ids if c not in seen[key]]
        seen[key].update(unique_ids)
        result.at[idx, 'Container Numbers'] = ', '.join(unique_ids) if unique_ids else ''
        result.at[idx, 'Container Count'] = len(unique_ids)
    
    # Recalculate cost columns
    if 'Base Rate' in result.columns:
        result['Total Rate'] = result['Base Rate'] * result['Container Count']
    if 'CPC' in result.columns:
        result['Total CPC'] = result['CPC'] * result['Container Count']
    
    return result


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


# Day-of-week names → Excel WEEKDAY(date, 1) number (Sun=1 … Sat=7), matching the
# Sunday-start week convention the rest of the pipeline uses for Week Number.
_DOW_NAME_TO_EXCEL = {
    'sun': 1, 'sunday': 1,
    'mon': 2, 'monday': 2,
    'tue': 3, 'tues': 3, 'tuesday': 3,
    'wed': 4, 'weds': 4, 'wednesday': 4,
    'thu': 5, 'thur': 5, 'thurs': 5, 'thursday': 5,
    'fri': 6, 'friday': 6,
    'sat': 7, 'saturday': 7,
}


def excel_weekday(date_value: Any) -> Optional[int]:
    """Return Excel WEEKDAY(date, 1) for a date: Sun=1, Mon=2, …, Sat=7.

    Mirrors the Sunday-start week the pipeline already uses for Week Number
    (Excel WEEKNUM). Returns None for unparseable/missing dates.
    """
    ts = pd.to_datetime(date_value, errors='coerce')
    if pd.isna(ts):
        return None
    # pandas weekday(): Mon=0 … Sun=6. Excel WEEKDAY(,1): Sun=1 … Sat=7.
    return (ts.weekday() + 1) % 7 + 1


def excel_weekday_series(series: pd.Series) -> pd.Series:
    """Vectorized excel_weekday for a Series of dates (NaT-safe, nullable Int)."""
    ts = pd.to_datetime(series, errors='coerce')
    return ((ts.dt.weekday + 1) % 7 + 1).astype('Int64')


def parse_day_of_week(value: Any) -> Optional[int]:
    """Parse a day-of-week constraint value to an Excel WEEKDAY number (Sun=1 … Sat=7).

    Accepts a number (1–7, where 1=Sunday per the Sunday-start convention) or a name
    (``mon``/``monday``/``Mon`` …, case-insensitively). Returns None if the value is
    blank or unrecognized.
    """
    if pd.isna(value):
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    # Numeric form: '1'..'7' (also tolerates floats like '3.0' from Excel cells).
    try:
        n = int(float(s))
        return n if 1 <= n <= 7 else None
    except (ValueError, TypeError):
        pass
    return _DOW_NAME_TO_EXCEL.get(s)


def normalize_facility_code(facility_str: Any) -> str:
    """
    Normalize facility code for comparison.
    
    If the facility starts with 'Amazon', returns the last 4 characters.
    Otherwise returns the first 4 characters.
    
    Examples: 'HGR6-5' -> 'HGR6', 'IUSF' -> 'IUSF', 'Amazon REWR' -> 'REWR'
    
    Args:
        facility_str: Facility code string.
        
    Returns:
        Normalized 4-character facility code.
    """
    if pd.isna(facility_str) or not str(facility_str).strip():
        return ''
    fc = str(facility_str).strip()
    if fc.upper().startswith('AMAZON'):
        return fc[-4:].upper()
    return fc[:4].upper() if len(fc) >= 4 else fc.upper()


def normalize_facility_series(series: pd.Series) -> pd.Series:
    """
    Vectorized facility normalization for a pandas Series.
    
    If facility starts with 'Amazon', returns the last 4 characters.
    Otherwise returns the first 4 characters.
    """
    s = series.astype(str).str.strip()
    is_amazon = s.str.upper().str.startswith('AMAZON')
    result = s.str[:4].str.upper()
    result[is_amazon] = s[is_amazon].str[-4:].str.upper()
    return result


# ==================== ARROW-SAFE DISPLAY ====================

def arrow_safe(df: "pd.DataFrame") -> "pd.DataFrame":
    """Return a copy of ``df`` whose columns serialize cleanly to Arrow.

    Streamlit renders every ``st.dataframe`` / ``st.data_editor`` by converting
    the frame to an Arrow table via ``pyarrow``. A single ``object`` column that
    mixes types — e.g. some cells ``int`` and others ``str`` — makes pyarrow raise
    ``ArrowTypeError: Expected bytes, got a 'int' object``, which propagates out of
    Streamlit, kills the script run, and (on hosted platforms) trips the health
    check with a "connection reset by peer" on ``/healthz``. Passthrough GVT
    columns (e.g. ``Carp Appointment``) are the usual culprit: a numeric-looking
    column with a few blank/text cells lands as ``object`` with mixed python types.

    This coerces any ``object`` column that holds more than one python scalar type
    (ignoring nulls) to string, leaving clean single-type columns untouched so
    numeric sorting/formatting elsewhere is unaffected. Best-effort and cheap; it
    only rewrites the offending columns. Returns the input unchanged if it is not a
    non-empty DataFrame.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df
    copied = False
    for col in df.columns:
        if df[col].dtype != object:
            continue
        non_null = df[col].dropna()
        if non_null.empty:
            continue
        # More than one distinct python type (e.g. int + str) breaks Arrow.
        if non_null.map(type).nunique() > 1:
            if not copied:
                out = df.copy()
                copied = True
            # Render ints without a trailing ".0"; everything else via str().
            out[col] = df[col].map(
                lambda v: "" if pd.isna(v)
                else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
            )
    return out


def st_dataframe_safe(df, *args, **kwargs):
    """``st.dataframe`` wrapper that first makes the frame Arrow-serializable.

    Drop-in replacement for ``st.dataframe`` at call sites that render
    GVT-derived frames carrying arbitrary passthrough columns. See
    :func:`arrow_safe` for why mixed-type ``object`` columns would otherwise crash
    the whole app run.
    """
    return st.dataframe(arrow_safe(df), *args, **kwargs)


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
            facility_match = normalize_facility_series(df['Facility']) == excluded_fc.upper()[:4]
            keep_mask &= ~(carrier_match & facility_match)
    
    return df[keep_mask].copy()
