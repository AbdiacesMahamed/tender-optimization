"""
Hierarchical Constraint Allocator

Processes constraints in strict priority and specificity order:
  1. Priority Score (10 → 9 → 8)
  2. Specificity: rows with more scope fields filled run before less specific rows
  3. Within same priority+specificity: higher percent allocation first

Allocation modes:
  - Priority 10: Hard locks (lane-level assignments, percent splits)
  - Priority 9: Shares with caps (% of original pool, hard max ceiling)
  - Priority 8: Soft caps / blocks (max=0 means blocked, max>0 means overflow-only)

The max on a blank-lane row is a TOTAL cap inclusive of what lane-level locks
already gave that carrier in the same scope.
"""
from __future__ import annotations

import math
import logging
from typing import Dict, List, Tuple, Optional, Set

import pandas as pd
import numpy as np

from components.utils import parse_container_ids, join_container_ids, normalize_facility_code

logger = logging.getLogger(__name__)

# Columns that define constraint scope (used for specificity scoring)
SCOPE_COLUMNS = ['Port', 'Category', 'Lane', 'Week Number', 'SSL', 'Terminal', 'Vessel']

# Column name mapping from common file variations to internal names
COLUMN_ALIASES = {
    'maximum container number': 'Maximum Container Count',
    'minimum container number': 'Minimum Container Count',
    'percent allocation': 'Percent Allocation',
    'priority score': 'Priority Score',
    'priority sc': 'Priority Score',
    'excluded fc': 'Excluded FC',
    'excluded facility': 'Excluded FC',
    'discharged port': 'Port',
    'port': 'Port',
    'category': 'Category',
    'carrier': 'Carrier',
    'lane': 'Lane',
    'week number': 'Week Number',
    'terminal': 'Terminal',
    'ssl': 'SSL',
    'vessel': 'Vessel',
}


def load_and_normalize_constraints(filepath_or_df) -> pd.DataFrame:
    """
    Load constraints from file path or DataFrame, normalize column names and values.

    Handles:
      - Column name variations (leading spaces, case differences)
      - Percent Allocation stored as 0-1 decimal → converted to 0-100 scale
      - Missing columns added as NaN
    """
    if isinstance(filepath_or_df, pd.DataFrame):
        df = filepath_or_df.copy()
    else:
        df = pd.read_excel(filepath_or_df)

    # Strip whitespace from column names
    df.columns = df.columns.str.strip()

    # Map columns to canonical names
    rename_map = {}
    for col in df.columns:
        col_lower = col.lower().strip()
        if col_lower in COLUMN_ALIASES:
            rename_map[col] = COLUMN_ALIASES[col_lower]
    df = df.rename(columns=rename_map)

    # Ensure all expected columns exist
    expected = SCOPE_COLUMNS + [
        'Carrier', 'Maximum Container Count', 'Minimum Container Count',
        'Percent Allocation', 'Excluded FC', 'Priority Score'
    ]
    for col in expected:
        if col not in df.columns:
            df[col] = np.nan

    # Normalize Percent Allocation: if values are in 0-1 range, scale to 0-100
    pct_col = df['Percent Allocation']
    non_null_pcts = pct_col.dropna()
    if len(non_null_pcts) > 0 and non_null_pcts.max() <= 1.0:
        df['Percent Allocation'] = pct_col * 100

    # Ensure numeric columns are numeric
    for col in ['Maximum Container Count', 'Minimum Container Count', 'Percent Allocation', 'Priority Score']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Clean text fields
    for col in ['Category', 'Carrier', 'Lane', 'Port', 'Terminal', 'SSL', 'Vessel', 'Excluded FC']:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: None if pd.isna(x) or (isinstance(x, str) and x.strip() == '') else str(x).strip()
            )

    # Drop rows with no priority score
    df = df[df['Priority Score'].notna()].copy()

    return df


def _compute_specificity(row: pd.Series) -> int:
    """Count how many scope fields are non-null (more = more specific)."""
    count = 0
    for col in SCOPE_COLUMNS:
        if pd.notna(row.get(col)):
            count += 1
    return count


def _is_filled(val) -> bool:
    """Check if a constraint field has a meaningful value."""
    if val is None:
        return False
    if pd.isna(val):
        return False
    if isinstance(val, str) and val.strip() == '':
        return False
    return True


def sort_constraints(constraints_df: pd.DataFrame) -> pd.DataFrame:
    """
    Sort constraints by:
      1. Priority Score descending (10 before 9 before 8)
      2. Specificity descending (more scope fields filled = more specific)
      3. Percent Allocation descending (larger shares first to reduce fragmentation)
    """
    df = constraints_df.copy()
    df['_specificity'] = df.apply(_compute_specificity, axis=1)
    df['_pct_sort'] = df['Percent Allocation'].fillna(0)

    df = df.sort_values(
        ['Priority Score', '_specificity', '_pct_sort'],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    df = df.drop(columns=['_specificity', '_pct_sort'])
    return df


def allocate_with_hierarchy(
    data: pd.DataFrame,
    constraints_df: pd.DataFrame,
    *,
    carrier_column: str = 'Dray SCAC(FL)',
    container_column: str = 'Container Count',
    container_ids_column: str = 'Container Numbers',
    port_column: str = 'Discharged Port',
    lane_column: str = 'Lane',
    week_column: str = 'Week Number',
    category_column: str = 'Category',
    facility_column: str = 'Facility',
) -> Tuple[pd.DataFrame, pd.DataFrame, List[dict], List[dict], Dict[str, Set[str]], List[dict]]:
    """
    Apply constraints hierarchically: priority → specificity → percentage.

    Parameters
    ----------
    data : pd.DataFrame
        The full container data (one row per carrier+lane+week with Container Numbers).
    constraints_df : pd.DataFrame
        Normalized constraints (output of load_and_normalize_constraints or sort_constraints).

    Returns
    -------
    constrained_data : pd.DataFrame
        Rows allocated by constraints (locked to specific carriers).
    unconstrained_data : pd.DataFrame
        Remaining rows for the optimization engine.
    constraint_summary : list of dict
        Per-constraint application summary.
    max_constrained_carriers : list of dict
        Carriers with hard caps (for optimization exclusion).
    carrier_facility_exclusions : dict
        Carrier → set of excluded facility codes.
    explanation_logs : list of dict
        Detailed processing log.
    """
    constraints_df = sort_constraints(constraints_df)

    logs: List[dict] = []
    constraint_summary: List[dict] = []
    max_constrained_carriers: List[dict] = []

    def log(msg, level='info'):
        logs.append({'Level': level.upper(), 'Message': msg})

    # -- Pre-collect facility exclusions --
    carrier_facility_exclusions: Dict[str, Set[str]] = {}
    for _, row in constraints_df.iterrows():
        carrier = row.get('Carrier')
        excluded_fc = row.get('Excluded FC')
        if _is_filled(carrier) and _is_filled(excluded_fc):
            carrier_facility_exclusions.setdefault(carrier, set()).add(
                normalize_facility_code(str(excluded_fc))
            )

    if carrier_facility_exclusions:
        for c, fcs in carrier_facility_exclusions.items():
            log(f"Pre-collected exclusions: {c} blocked from {', '.join(sorted(fcs))}", 'exclusion')

    # Working copy of data
    remaining = data.copy().reset_index(drop=True)

    # Track cumulative containers allocated per carrier per scope (port, category)
    # Key: (carrier, port, category) → total containers allocated so far
    carrier_allocated: Dict[Tuple, int] = {}

    # Track individual container IDs that have been allocated
    allocated_container_ids: Set[str] = set()

    # Constrained records accumulator
    constrained_records: List[pd.Series] = []

    log(f"Processing {len(constraints_df)} constraints in priority+specificity order")

    for c_idx, constraint in constraints_df.iterrows():
        priority = int(constraint['Priority Score'])
        carrier = constraint.get('Carrier')
        port = constraint.get('Port')
        category = constraint.get('Category')
        lane = constraint.get('Lane')
        week = constraint.get('Week Number')
        ssl_val = constraint.get('SSL')
        terminal = constraint.get('Terminal')
        vessel = constraint.get('Vessel')
        excluded_fc = constraint.get('Excluded FC')

        pct_alloc = constraint.get('Percent Allocation')
        max_count = constraint.get('Maximum Container Count')
        min_count = constraint.get('Minimum Container Count')

        # Build description
        desc_parts = []
        if _is_filled(port): desc_parts.append(f"Port={port}")
        if _is_filled(category): desc_parts.append(f"Cat={category}")
        if _is_filled(carrier): desc_parts.append(f"Carrier={carrier}")
        if _is_filled(lane): desc_parts.append(f"Lane={lane}")
        if _is_filled(week): desc_parts.append(f"Week={int(week)}")
        if _is_filled(ssl_val): desc_parts.append(f"SSL={ssl_val}")
        if _is_filled(terminal): desc_parts.append(f"Terminal={terminal}")
        if _is_filled(excluded_fc): desc_parts.append(f"ExclFC={excluded_fc}")
        desc = f"P{priority} | " + (', '.join(desc_parts) if desc_parts else 'Global')

        # -- Exclusion-only constraint (no allocation amount) --
        has_allocation = (
            (_is_filled(pct_alloc) and pct_alloc > 0) or
            _is_filled(max_count) or
            _is_filled(min_count)
        )
        if not has_allocation and _is_filled(excluded_fc) and _is_filled(carrier):
            log(f"[{desc}] Exclusion-only rule applied via pre-collection", 'info')
            constraint_summary.append({
                'priority': priority, 'description': desc,
                'status': 'Applied (Exclusion)', 'containers_allocated': 0,
            })
            continue

        if not has_allocation and not _is_filled(excluded_fc):
            log(f"[{desc}] No allocation amount or exclusion — skipped", 'warning')
            constraint_summary.append({
                'priority': priority, 'description': desc,
                'status': 'Skipped (no amount)', 'containers_allocated': 0,
            })
            continue

        # -- Build filter mask on remaining data --
        mask = pd.Series(True, index=remaining.index)

        if _is_filled(port) and port_column in remaining.columns:
            mask &= remaining[port_column] == port
        if _is_filled(category) and category_column in remaining.columns:
            mask &= remaining[category_column] == category
        if _is_filled(lane) and lane_column in remaining.columns:
            mask &= remaining[lane_column] == lane
        if _is_filled(week) and week_column in remaining.columns:
            mask &= remaining[week_column] == week
        if _is_filled(ssl_val) and 'SSL' in remaining.columns:
            mask &= remaining['SSL'] == ssl_val
        if _is_filled(terminal) and 'Terminal' in remaining.columns:
            mask &= remaining['Terminal'] == terminal
        if _is_filled(vessel) and 'Vessel' in remaining.columns:
            mask &= remaining['Vessel'] == vessel

        # Apply facility exclusions for this carrier
        if _is_filled(carrier) and facility_column in remaining.columns:
            all_excl = carrier_facility_exclusions.get(carrier, set())
            if all_excl:
                fac_normalized = remaining[facility_column].apply(
                    lambda x: normalize_facility_code(str(x)) if pd.notna(x) else ''
                )
                mask &= ~fac_normalized.isin(all_excl)

        eligible = remaining[mask].copy()

        if len(eligible) == 0:
            log(f"[{desc}] No matching data", 'warning')
            constraint_summary.append({
                'priority': priority, 'description': desc,
                'status': 'No matching data', 'containers_allocated': 0,
            })
            # Still register max constraint for optimization exclusion
            if _is_filled(max_count) and _is_filled(carrier):
                max_constrained_carriers.append(_build_scope_dict(carrier, constraint))
            continue

        # Calculate available containers (not yet allocated by higher-priority constraints)
        available_per_row = []
        for idx_val, row in eligible.iterrows():
            cids = parse_container_ids(row.get(container_ids_column, ''))
            available = [c for c in cids if c not in allocated_container_ids]
            available_per_row.append(available)

        eligible['_available_ids'] = available_per_row
        eligible['_available_count'] = eligible['_available_ids'].apply(len)
        eligible = eligible[eligible['_available_count'] > 0].copy()

        total_available = eligible['_available_count'].sum()

        if total_available == 0:
            log(f"[{desc}] All containers already allocated by higher-priority constraints", 'info')
            constraint_summary.append({
                'priority': priority, 'description': desc,
                'status': 'Exhausted', 'containers_allocated': 0,
            })
            if _is_filled(max_count) and _is_filled(carrier):
                max_constrained_carriers.append(_build_scope_dict(carrier, constraint))
            continue

        # -- Determine target container count --
        # Scope key for tracking cumulative allocation
        scope_key = (
            carrier if _is_filled(carrier) else '__any__',
            port if _is_filled(port) else '__any__',
            category if _is_filled(category) else '__any__',
        )
        already_allocated_for_carrier = carrier_allocated.get(scope_key, 0)

        target = _compute_target(
            pct_alloc=pct_alloc,
            max_count=max_count,
            min_count=min_count,
            total_available=total_available,
            already_allocated=already_allocated_for_carrier,
            priority=priority,
        )

        if target is None:
            # Priority 8 with pct=0 and max=0 → block
            if _is_filled(carrier):
                max_constrained_carriers.append(_build_scope_dict(carrier, constraint))
                log(f"[{desc}] BLOCKED — carrier will receive 0 containers", 'block')
                constraint_summary.append({
                    'priority': priority, 'description': desc,
                    'status': 'Applied (Block)', 'containers_allocated': 0,
                })
            continue

        if target == 0:
            log(f"[{desc}] Target=0 after cap adjustment (already at max)", 'info')
            if _is_filled(carrier):
                max_constrained_carriers.append(_build_scope_dict(carrier, constraint))
            constraint_summary.append({
                'priority': priority, 'description': desc,
                'status': 'Applied (Cap reached)', 'containers_allocated': 0,
            })
            continue

        # -- Allocate containers --
        allocated_count = 0
        allocation_rows = eligible.sort_values(week_column) if week_column in eligible.columns else eligible

        for row_idx, row in allocation_rows.iterrows():
            if allocated_count >= target:
                break

            available_ids = row['_available_ids']
            needed = target - allocated_count
            to_take = available_ids[:needed]

            if not to_take:
                continue

            # Create constrained record
            record = row.drop(labels=['_available_ids', '_available_count']).copy()
            record[container_ids_column] = join_container_ids(to_take)
            record[container_column] = len(to_take)
            if _is_filled(carrier):
                record[carrier_column] = carrier
                if 'Carrier' in record.index and carrier_column != 'Carrier':
                    record['Carrier'] = carrier
            record['Constraint_Priority'] = priority
            record['Constraint_Description'] = desc

            constrained_records.append(record)
            allocated_count += len(to_take)

            # Mark these container IDs as allocated
            allocated_container_ids.update(to_take)

            # Update remaining data: remove allocated IDs from this row
            leftover = [c for c in available_ids if c not in set(to_take)]
            # Also include any already-allocated IDs that were in the original row
            orig_ids = parse_container_ids(remaining.at[row_idx, container_ids_column])
            new_ids = [c for c in orig_ids if c not in allocated_container_ids]

            if new_ids:
                remaining.at[row_idx, container_ids_column] = join_container_ids(new_ids)
                remaining.at[row_idx, container_column] = len(new_ids)
            else:
                remaining.at[row_idx, container_ids_column] = ''
                remaining.at[row_idx, container_column] = 0

        # Update cumulative tracker
        carrier_allocated[scope_key] = already_allocated_for_carrier + allocated_count

        # Register carrier for optimizer exclusion if max or percent is set
        # Max: hard cap — carrier must not get more in optimization
        # Percent: defines total share — optimizer should not add beyond it
        if _is_filled(carrier) and (_is_filled(max_count) or (_is_filled(pct_alloc) and pct_alloc > 0)):
            max_constrained_carriers.append(_build_scope_dict(carrier, constraint))

        # Determine status: flag minimum shortfalls
        alloc_status = 'Applied'
        if _is_filled(min_count) and min_count > 0 and allocated_count < int(min_count):
            shortfall = int(min_count) - allocated_count
            log(f"[{desc}] SHORTFALL: minimum requires {int(min_count)} but only allocated {allocated_count} ({shortfall} short)", 'warning')
            alloc_status = f"Partial (shortfall: {shortfall})"

        log(f"[{desc}] Allocated {allocated_count}/{target} containers", 'success')
        constraint_summary.append({
            'priority': priority, 'description': desc,
            'status': alloc_status, 'containers_allocated': allocated_count,
            'target': target, 'available': total_available,
        })

    # -- Build output DataFrames --
    remaining = remaining[remaining[container_column] > 0].copy()

    if constrained_records:
        constrained_data = pd.DataFrame(constrained_records).reset_index(drop=True)
    else:
        constrained_data = pd.DataFrame()

    # Final balance check
    total_original = data[container_column].sum()
    total_constrained = constrained_data[container_column].sum() if len(constrained_data) > 0 else 0
    total_remaining = remaining[container_column].sum()
    log(f"Balance: original={total_original}, constrained={total_constrained}, remaining={total_remaining}", 'summary')
    if abs(total_original - (total_constrained + total_remaining)) > 0.01:
        log(f"MISMATCH: {total_original - (total_constrained + total_remaining):.0f} containers unaccounted", 'error')

    return (
        constrained_data,
        remaining,
        constraint_summary,
        max_constrained_carriers,
        carrier_facility_exclusions,
        logs,
    )


def _compute_target(
    *,
    pct_alloc: Optional[float],
    max_count: Optional[float],
    min_count: Optional[float],
    total_available: int,
    already_allocated: int,
    priority: int,
) -> Optional[int]:
    """
    Compute how many containers to allocate for this constraint.

    Returns:
      - int >= 0: allocate this many containers
      - None: this is a BLOCK (carrier gets zero, should be excluded from optimization)
    """
    # Block: pct=0, max=0 (or max not set with pct=0 at priority 8)
    is_blocked = (
        _is_filled(pct_alloc) and pct_alloc == 0 and
        _is_filled(max_count) and max_count == 0
    )
    if is_blocked:
        return None

    # Priority 8 with pct=0 and no max → also a block
    if priority == 8 and _is_filled(pct_alloc) and pct_alloc == 0 and not _is_filled(max_count):
        return None

    # Compute base target from percentage, or use min/max as the starting point
    if _is_filled(pct_alloc) and pct_alloc > 0:
        raw = total_available * (pct_alloc / 100.0)
        target = math.ceil(raw) if raw > 0 else 0
    elif _is_filled(pct_alloc) and pct_alloc == 0:
        # pct=0 but max>0: this is an overflow-only carrier (no guaranteed share)
        # They get 0 proactive allocation; max is just a cap for the optimizer
        target = 0 if not _is_filled(min_count) else int(min_count)
    elif _is_filled(min_count) and min_count > 0:
        # Min-only: lock exactly the minimum amount
        target = int(min_count)
    elif _is_filled(max_count):
        # Max-only: allocate up to the max
        target = int(max_count)
    else:
        target = total_available

    # Apply minimum floor
    if _is_filled(min_count) and min_count > 0:
        target = max(target, int(min_count))

    # Apply maximum ceiling (inclusive of prior allocations)
    if _is_filled(max_count):
        remaining_cap = max(0, int(max_count) - already_allocated)
        target = min(target, remaining_cap)

    # Can't exceed available
    target = min(target, total_available)

    return max(0, target)


def _build_scope_dict(carrier: str, constraint: pd.Series) -> dict:
    """Build a scope dict for the max_constrained_carriers list."""
    return {
        'carrier': carrier,
        'category': constraint.get('Category') if _is_filled(constraint.get('Category')) else None,
        'lane': constraint.get('Lane') if _is_filled(constraint.get('Lane')) else None,
        'port': constraint.get('Port') if _is_filled(constraint.get('Port')) else None,
        'week': int(constraint.get('Week Number')) if _is_filled(constraint.get('Week Number')) else None,
    }
