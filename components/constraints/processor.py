"""
Constraints Processing Module
Handles operational constraints uploaded via Excel file
Version: 2025-11-25 - Moved constraint processing messages to downloadable CSV sheet
"""
import pandas as pd
import streamlit as st
import math
from ..core.utils import (
    normalize_facility_code, parse_container_ids, join_container_ids,
    parse_day_of_week
)
from config.category_mapping import canonical_category

# Port shorthand used in user-supplied constraint files → discharge ports the user
# considers part of that port complex. Lookup is case-insensitive.
PORT_ALIASES = {
    'NYC': ['NYC', 'EWR'],
    'LAX': ['LAX', 'LGB'],
}


def norm_text(value):
    """Case- and whitespace-insensitive normalization for string scope matching.

    Upper-cases, trims, and collapses internal whitespace runs to a single space so a
    constraint typed 'abe8', ' ABE8 ', or 'MSC  GULSUN' matches the data's 'ABE8' /
    'MSC GULSUN'. Used for the raw string dimensions (Lane, Port, Terminal, SSL, Vessel)
    that would otherwise require an exact byte-for-byte match. Non-strings (NaN, numbers)
    pass through str() first; genuinely different values stay different.
    """
    if pd.isna(value):
        return value
    return ' '.join(str(value).strip().upper().split())


def norm_text_series(series):
    """Vectorized norm_text for a pandas Series (NaN-safe)."""
    return series.map(norm_text)


def canonical_category_key(value):
    """Canonical bucket a constraint/data Category value matches on (or None).

    Both the constraint side and the data side are routed through the same
    canonicalization (config.category_mapping), so every spelling of a category
    — the raw GVT label ('Retail CD'), the shorthand ('CD'), or the already-
    normalized bucket — collapses to one key. Comparing canonical-to-canonical
    is what makes Category matching work in both directions; comparing a raw
    label against a normalized bucket is the bug this replaces.
    """
    return canonical_category(value)


def expected_constraint_columns():
    """The canonical 14-column constraint schema, in order.

    Single source of truth shared by the Excel upload path
    (``process_constraints_file``) and the prebuilt per-port CSVs
    (``components.constraints.prebuilt``) so both stay in lockstep.
    """
    return [
        'Category', 'Carrier', 'Lane', 'Port', 'Week Number', 'Day of Week',
        'Terminal', 'SSL', 'Vessel',
        'Maximum Container Count', 'Minimum Container Count',
        'Percent Allocation', 'Excluded FC', 'Priority Score'
    ]


def resolve_port_filter(value):
    """Return the list of Discharged Port values a constraint Port should match."""
    if value is None:
        return []
    key = str(value).strip().upper()
    return PORT_ALIASES.get(key, [str(value).strip()])


def is_valid_value(val):
    """True if a constraint field carries a real value (not None/NaN/blank)."""
    if pd.isna(val):
        return False
    if isinstance(val, str) and val.strip() == '':
        return False
    return True


def build_scope_filters(constraint, df):
    """Return the active scope filters for a constraint as a list of dicts:
    ``{'dimension', 'value', 'desc', 'mask'}``.

    Only dimensions with a valid value AND a backing column in ``df`` are
    included. This is the single source of truth for "which rows does this
    constraint apply to" — it drives both the combined eligibility mask in the
    allocation loop and the per-filter failure diagnosis. Because both paths
    build their masks here, the eligibility decision and the "why did nothing
    match?" explanation can never disagree about which filters were active.

    NOTE: Carrier is intentionally NOT a filter — it's the TARGET assignment.
    A constraint means "assign X to this carrier", not "find X already with it".
    """
    specs = []

    # Category: canonicalize BOTH the constraint value and the data column to the
    # same bucket before comparing (config.category_mapping). This matches in both
    # directions — a 'CD' rule hits 'Retail CD'/'FBA FCL'/'FBA LCL' rows AND the
    # already-normalized 'CD' rows — instead of expanding one side to labels the
    # normalized data no longer contains.
    if is_valid_value(constraint.get('Category')) and 'Category' in df.columns:
        wanted = canonical_category_key(constraint['Category'])
        data_canon = df['Category'].map(canonical_category_key)
        specs.append({
            'dimension': 'Category',
            'value': constraint['Category'],
            'desc': f"Category={constraint['Category']}",
            'mask': data_canon == wanted,
        })

    # Lane: constraint files commonly use 4-char facility codes (e.g. ABE8) while
    # data carries the full 9-char concatenated lane (e.g. USNYCABE8) — an endswith
    # match keeps the short form usable while still respecting Port filters. Both
    # sides are case/whitespace-normalized so 'abe8' matches 'USNYCABE8'.
    if is_valid_value(constraint.get('Lane')) and 'Lane' in df.columns:
        lane_value = norm_text(constraint['Lane'])
        lane_data = norm_text_series(df['Lane'])
        if len(lane_value) <= 4:
            lane_mask = lane_data.str.endswith(lane_value)
        else:
            lane_mask = lane_data == lane_value
        specs.append({
            'dimension': 'Lane',
            'value': constraint['Lane'],
            'desc': f"Lane={constraint['Lane']}",
            'mask': lane_mask,
        })

    # Port: user shorthand (NYC/LAX) expands to the full Discharged Port set via
    # PORT_ALIASES. Both the expanded set and the data column are normalized so the
    # isin match is case/whitespace-insensitive.
    if is_valid_value(constraint.get('Port')) and 'Discharged Port' in df.columns:
        allowed_ports = [norm_text(p) for p in resolve_port_filter(constraint['Port'])]
        specs.append({
            'dimension': 'Port',
            'value': constraint['Port'],
            'desc': f"Port={constraint['Port']}",
            'mask': norm_text_series(df['Discharged Port']).isin(allowed_ports),
        })

    if is_valid_value(constraint.get('Week Number')) and 'Week Number' in df.columns:
        specs.append({
            'dimension': 'Week',
            'value': int(constraint['Week Number']),
            'desc': f"Week={int(constraint['Week Number'])}",
            'mask': df['Week Number'] == constraint['Week Number'],
        })

    # Day of Week: constraint value is already parsed to the Excel WEEKDAY number
    # (Sun=1 … Sat=7) at load time; the data column carries the same numbering.
    if is_valid_value(constraint.get('Day of Week')) and 'Day of Week' in df.columns:
        dow_value = int(constraint['Day of Week'])
        specs.append({
            'dimension': 'Day of Week',
            'value': dow_value,
            'desc': f"Day={dow_value}",
            'mask': pd.to_numeric(df['Day of Week'], errors='coerce') == dow_value,
        })

    if is_valid_value(constraint.get('Terminal')) and 'Terminal' in df.columns:
        specs.append({
            'dimension': 'Terminal',
            'value': constraint['Terminal'],
            'desc': f"Terminal={constraint['Terminal']}",
            'mask': norm_text_series(df['Terminal']) == norm_text(constraint['Terminal']),
        })

    if is_valid_value(constraint.get('SSL')) and 'SSL' in df.columns:
        specs.append({
            'dimension': 'SSL',
            'value': constraint['SSL'],
            'desc': f"SSL={constraint['SSL']}",
            'mask': norm_text_series(df['SSL']) == norm_text(constraint['SSL']),
        })

    if is_valid_value(constraint.get('Vessel')) and 'Vessel' in df.columns:
        specs.append({
            'dimension': 'Vessel',
            'value': constraint['Vessel'],
            'desc': f"Vessel={constraint['Vessel']}",
            'mask': norm_text_series(df['Vessel']) == norm_text(constraint['Vessel']),
        })

    return specs


def diagnose_no_match(constraint, source_df):
    """Explain why a constraint matched zero rows by testing each scope filter
    against the pristine source data individually.

    Returns ``(kind, reason)`` where ``kind`` is:
      - ``'dead'``        one or more filter VALUES are absent from the data
                          entirely (the most actionable culprit — a typo, an
                          alias that didn't expand, or a value that only exists
                          under a different week/port/category);
      - ``'combination'`` every filter matches rows on its own, but no single
                          row satisfies all of them at once (scope too narrow);
      - ``None``          the constraint defines no scope filters to blame.
    """
    specs = build_scope_filters(constraint, source_df)
    if not specs:
        return None, None

    counts = [(s['dimension'], s['value'], int(s['mask'].sum())) for s in specs]
    dead = [(dim, val) for dim, val, n in counts if n == 0]

    if dead:
        parts = ', '.join(f"{dim}={val}" for dim, val in dead)
        return 'dead', (
            f"No rows in the source data match the scope filter(s) {parts}. That value "
            "isn't present in the GVT file for this run — check for a typo, an alias that "
            "didn't expand, or a value that only exists under a different week/port/category."
        )

    breakdown = '; '.join(f"{dim}={val} → {n} row(s)" for dim, val, n in counts)
    return 'combination', (
        "Each scope filter matches rows on its own, but no single row satisfies all of "
        f"them at once ({breakdown}). The filter combination is too narrow — relax one "
        "dimension so the scopes overlap."
    )


def compute_scoped_max_ceilings(constraints_df, data):
    """Pre-scan every Maximum Container Count rule into a per-(carrier, scope) ceiling.

    Returns a list of dicts ``{carrier, mask, cap, allocated, desc}`` where ``mask`` is
    a boolean Series over ``data.index`` selecting the rows the cap binds (built from
    the SAME build_scope_filters used by allocation, so all scope dimensions are
    covered). ``allocated`` starts at 0 and is mutated by callers as they consume
    headroom. This is the single source of truth for scoped maxima so both the file
    constraint pass AND the peel pile honor the same caps.
    """
    ceilings = []
    if constraints_df is None or len(constraints_df) == 0:
        return ceilings
    if 'Maximum Container Count' not in constraints_df.columns or 'Carrier' not in constraints_df.columns:
        return ceilings
    for _, mc in constraints_df.iterrows():
        cap_val = mc.get('Maximum Container Count')
        cap_carrier = mc.get('Carrier')
        if not (pd.notna(cap_val) and cap_val > 0 and is_valid_value(cap_carrier)):
            continue
        specs = build_scope_filters(mc, data)
        mask = pd.Series(True, index=data.index)
        for s in specs:
            mask &= s['mask'].reindex(data.index, fill_value=False)
        ceilings.append({
            'carrier': str(cap_carrier).strip(),
            'mask': mask,
            'cap': int(cap_val),
            'allocated': 0,
            'desc': ', '.join(s['desc'] for s in specs) or 'all data',
        })
    return ceilings


def ceiling_headroom(ceilings, row_index, carrier):
    """Smallest remaining headroom across all ceilings binding this (row, carrier).
    None means no ceiling applies (unbounded)."""
    if not carrier:
        return None
    carrier_key = norm_text(carrier)
    hr = None
    for c in ceilings:
        if norm_text(c['carrier']) != carrier_key:
            continue
        m = c['mask']
        if row_index in m.index and bool(m.loc[row_index]):
            remaining = max(0, c['cap'] - c['allocated'])
            hr = remaining if hr is None else min(hr, remaining)
    return hr


def credit_ceilings(ceilings, row_index, carrier, n):
    """Count ``n`` containers allocated to ``carrier`` from ``row_index`` against every
    ceiling that binds them, so later rows/rules see the reduced cap."""
    if not carrier or n <= 0:
        return
    carrier_key = norm_text(carrier)
    for c in ceilings:
        if norm_text(c['carrier']) != carrier_key:
            continue
        m = c['mask']
        if row_index in m.index and bool(m.loc[row_index]):
            c['allocated'] += n


def compute_scoped_lockouts(constraints_df, data):
    """Pre-scan every lockout rule (Max 0 or Percent 0) into a per-(carrier, scope) ban.

    Returns a list of ``{carrier, mask}`` where ``mask`` selects the rows the lockout
    binds (built from the SAME build_scope_filters the allocation loop uses, so it
    covers every scope dimension — Port, Vessel, Terminal, etc.). This is the
    counterpart to :func:`compute_scoped_max_ceilings`, which deliberately keeps only
    caps with ``cap > 0``; here we keep only the zeros. Used so the over-cap re-home
    pass never reassigns volume to a carrier that is locked out of that row's scope
    (e.g. moving capped TIW volume onto AOYV, which is banned from TIW).
    """
    lockouts = []
    if constraints_df is None or len(constraints_df) == 0:
        return lockouts
    if 'Carrier' not in constraints_df.columns:
        return lockouts
    has_max = 'Maximum Container Count' in constraints_df.columns
    has_pct = 'Percent Allocation' in constraints_df.columns
    for _, mc in constraints_df.iterrows():
        carrier = mc.get('Carrier')
        if not is_valid_value(carrier):
            continue
        is_zero_max = has_max and pd.notna(mc.get('Maximum Container Count')) \
            and mc.get('Maximum Container Count') == 0
        is_zero_pct = has_pct and pd.notna(mc.get('Percent Allocation')) \
            and mc.get('Percent Allocation') == 0
        if not (is_zero_max or is_zero_pct):
            continue
        specs = build_scope_filters(mc, data)
        mask = pd.Series(True, index=data.index)
        for s in specs:
            mask &= s['mask'].reindex(data.index, fill_value=False)
        lockouts.append({'carrier': str(carrier).strip(), 'mask': mask})
    return lockouts


def carrier_locked_out(lockouts, row_index, carrier):
    """True if ``carrier`` is locked out of ``row_index``'s scope by any lockout rule."""
    if not carrier:
        return False
    carrier_key = norm_text(carrier)
    for lk in lockouts:
        if norm_text(lk['carrier']) != carrier_key:
            continue
        m = lk['mask']
        if row_index in m.index and bool(m.loc[row_index]):
            return True
    return False


# ==================== EVEN WEEKLY (DAY-OF-WEEK) DISTRIBUTION ====================
# When a constraint allocates N containers, we spread them across the days of the
# week instead of greedily draining the earliest rows. The day is taken from each
# row's Ocean ETA (already materialized as the Excel WEEKDAY 'Day of Week' column,
# Sun=1 … Sat=7). Per the business rule, Friday, Saturday and Sunday collapse into a
# SINGLE bucket — the weekend counts as one "day" — leaving five buckets:
#   Mon, Tue, Wed, Thu, Fri-Sun.
# The split is round-robin and need not be perfectly even; it just keeps volume from
# piling onto one weekday when the eligible rows span several.
_DOW_BUCKET = {2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri-Sun', 7: 'Fri-Sun', 1: 'Fri-Sun'}
_DOW_BUCKET_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri-Sun']
# Rows with no / unparseable Day of Week land here so they still allocate (just not
# as part of the even spread). Sorted last so dated rows are balanced first.
_NO_DOW_BUCKET = '__nodow__'


def day_bucket(dow_value):
    """Map an Excel WEEKDAY number (Sun=1 … Sat=7) to a weekly-distribution bucket.

    Mon–Thu are their own buckets; Fri(6)/Sat(7)/Sun(1) collapse to one 'Fri-Sun'
    bucket. Missing or unparseable values map to ``_NO_DOW_BUCKET``.
    """
    try:
        n = int(dow_value)
    except (TypeError, ValueError):
        return _NO_DOW_BUCKET
    return _DOW_BUCKET.get(n, _NO_DOW_BUCKET)


def bucket_iter_order(bucket_caps):
    """Day buckets present in ``bucket_caps``, in Mon→Fri-Sun order, no-DOW last."""
    order = [b for b in _DOW_BUCKET_ORDER if b in bucket_caps]
    order += [b for b in bucket_caps if b not in _DOW_BUCKET_ORDER]
    return order


def round_robin_quota(target, bucket_caps):
    """Split ``target`` containers across day buckets round-robin (one at a time).

    Walks the buckets in day order, handing out a single container per turn and
    skipping any bucket that has reached its available-container cap, so a thin
    bucket never gets a quota it can't fill — the overflow cycles to buckets that
    still have room. Returns ``{bucket: count}`` summing to
    ``min(target, total available)``. Five buckets max, so the per-container loop is
    cheap even for large targets.
    """
    order = bucket_iter_order(bucket_caps)
    alloc = {b: 0 for b in order}
    remaining = min(int(target), int(sum(bucket_caps.values())))
    progressed = True
    while remaining > 0 and progressed:
        progressed = False
        for b in order:
            if remaining <= 0:
                break
            if alloc[b] < bucket_caps[b]:
                alloc[b] += 1
                remaining -= 1
                progressed = True
    return alloc


def allocate_specific_containers(row, num_containers, allocated_tracker, target_carrier, week_num, priority=None):
    """
    Allocate specific container IDs from a row, tracking which containers are allocated

    Args:
        row: Data row containing Container Numbers
        num_containers: Number of containers to allocate
        allocated_tracker: Dict tracking allocated container IDs
        target_carrier: Carrier to assign containers to
        week_num: Week number for tracking
        priority: Priority score of the constraint claiming these containers (for attribution)

    Returns:
        tuple: (allocated_container_ids, remaining_container_ids)
    """
    container_ids = parse_container_ids(row.get('Container Numbers', ''))

    # Filter out already-allocated containers
    available_ids = [cid for cid in container_ids if cid not in allocated_tracker]

    if len(available_ids) == 0:
        return [], []

    # Take up to num_containers
    actual_to_allocate = min(num_containers, len(available_ids))
    allocated_ids = available_ids[:actual_to_allocate]
    remaining_ids = available_ids[actual_to_allocate:]

    # Mark as allocated with metadata
    for cid in allocated_ids:
        allocated_tracker[cid] = {
            'carrier': target_carrier,
            'week': week_num,
            'row_idx': row.name if hasattr(row, 'name') else None,
            'priority': priority,
        }

    return allocated_ids, remaining_ids


# ==================== MAIN CONSTRAINT PROCESSING FUNCTIONS ====================

def process_constraints_file(constraints_file):
    """
    Read and validate constraints file
    
    Expected columns (all optional except Priority Score):
    - Category
    - Carrier
    - Lane
    - Port (Discharged Port)
    - Week Number
    - Terminal
    - SSL (Steamship Line)
    - Vessel
    - Maximum container number / Maximum Container Count
    - minimum container number / Minimum Container Count
    - Percent Allocation
    - Excluded FC (Excluded Facility) - Carrier cannot receive volume at this facility
    - Priority Score / Priority Sc (required)
    
    Returns:
        DataFrame with validated constraints sorted by priority
    """
    try:
        constraints_df = pd.read_excel(constraints_file)
        
        # Normalize column names - strip whitespace and convert to title case
        constraints_df.columns = constraints_df.columns.str.strip()
        
        # Create column mapping for flexible naming
        column_mapping = {}
        
        for col in constraints_df.columns:
            col_lower = col.lower().strip()
            
            # Map Priority Score variations
            if 'priority' in col_lower and 'sc' in col_lower:
                column_mapping[col] = 'Priority Score'
            # Map Category
            elif col_lower == 'category':
                column_mapping[col] = 'Category'
            # Map Carrier
            elif col_lower == 'carrier':
                column_mapping[col] = 'Carrier'
            # Map Lane
            elif col_lower == 'lane':
                column_mapping[col] = 'Lane'
            # Map Port (Discharged Port)
            elif col_lower == 'port' or 'discharged' in col_lower and 'port' in col_lower:
                column_mapping[col] = 'Port'
            # Map Week Number
            elif 'week' in col_lower and 'number' in col_lower:
                column_mapping[col] = 'Week Number'
            # Map Day of Week (accepts 'Day of Week', 'Day', 'DOW', 'Weekday')
            elif col_lower in ('day of week', 'day', 'dow', 'weekday', 'day of the week'):
                column_mapping[col] = 'Day of Week'
            # Map Maximum Container variations
            elif 'maximum' in col_lower and 'container' in col_lower:
                column_mapping[col] = 'Maximum Container Count'
            # Map Minimum Container variations
            elif 'minimum' in col_lower and 'container' in col_lower:
                column_mapping[col] = 'Minimum Container Count'
            # Map Percent Allocation
            elif 'percent' in col_lower and 'allocation' in col_lower:
                column_mapping[col] = 'Percent Allocation'
            # Map Excluded FC (Excluded Facility)
            elif 'excluded' in col_lower and 'fc' in col_lower:
                column_mapping[col] = 'Excluded FC'
            elif 'excluded' in col_lower and 'facility' in col_lower:
                column_mapping[col] = 'Excluded FC'
            # Map Terminal
            elif col_lower == 'terminal':
                column_mapping[col] = 'Terminal'
            # Map SSL
            elif col_lower == 'ssl':
                column_mapping[col] = 'SSL'
            # Map Vessel
            elif col_lower == 'vessel':
                column_mapping[col] = 'Vessel'
        
        # Apply column mapping
        constraints_df = constraints_df.rename(columns=column_mapping)
        
        # Define expected columns
        expected_cols = expected_constraint_columns()
        
        # Check if Priority Score exists (required)
        if 'Priority Score' not in constraints_df.columns:
            st.error("❌ Constraints file must include 'Priority Score' or 'Priority Sc' column")
            st.write("Available columns:", list(constraints_df.columns))
            return None
        
        # Add missing optional columns as None
        for col in expected_cols:
            if col not in constraints_df.columns:
                constraints_df[col] = None
        
        # Clean up text fields - convert empty strings to None
        for col in ['Category', 'Lane', 'Carrier', 'Port', 'Terminal', 'Excluded FC', 'SSL', 'Vessel']:
            if col in constraints_df.columns:
                # Replace empty strings with None
                constraints_df[col] = constraints_df[col].apply(
                    lambda x: None if pd.isna(x) or (isinstance(x, str) and x.strip() == '') else x
                )
        
        # Clean up Week Number - convert to int if possible
        if 'Week Number' in constraints_df.columns:
            constraints_df['Week Number'] = pd.to_numeric(
                constraints_df['Week Number'], errors='coerce'
            )

        # Parse Day of Week to Excel WEEKDAY number (Sun=1 … Sat=7). Accepts numbers
        # (1–7) or names (mon/monday/…), case-insensitively. Unrecognized → None.
        if 'Day of Week' in constraints_df.columns:
            constraints_df['Day of Week'] = constraints_df['Day of Week'].apply(parse_day_of_week)
        
        # Clean up Percent Allocation - remove % sign and convert to numeric
        if 'Percent Allocation' in constraints_df.columns:
            def clean_percent(val):
                if pd.isna(val) or val == '':
                    return None
                
                # If it's already a number (Excel percentage cells are stored as decimals)
                if isinstance(val, (int, float)):
                    # If it's between 0 and 1, it's likely stored as a decimal (0.2 = 20%)
                    if 0 < val <= 1:
                        return val * 100  # Convert 0.2 to 20
                    else:
                        return val  # Already a percentage value
                
                # Convert to string and remove % sign
                val_str = str(val).strip().replace('%', '')
                try:
                    num_val = float(val_str)
                    # If it's between 0 and 1, assume it's a decimal
                    if 0 < num_val <= 1:
                        return num_val * 100
                    return num_val
                except:
                    return None
            
            constraints_df['Percent Allocation'] = constraints_df['Percent Allocation'].apply(clean_percent)
        
        # Clean up Maximum Container Count
        if 'Maximum Container Count' in constraints_df.columns:
            constraints_df['Maximum Container Count'] = pd.to_numeric(
                constraints_df['Maximum Container Count'], errors='coerce'
            )
        
        # Clean up Minimum Container Count
        if 'Minimum Container Count' in constraints_df.columns:
            constraints_df['Minimum Container Count'] = pd.to_numeric(
                constraints_df['Minimum Container Count'], errors='coerce'
            )
        
        # Sort by Priority Score (higher score = higher priority)
        constraints_df = constraints_df.sort_values('Priority Score', ascending=False, na_position='last')
        
        # Remove rows with no priority score
        constraints_df = constraints_df[constraints_df['Priority Score'].notna()]
        
        if len(constraints_df) == 0:
            st.warning("⚠️ No valid constraints found in file (all rows missing Priority Score)")
            return None
        
        st.success(f"✅ Loaded {len(constraints_df)} constraint(s) from file")
        
        return constraints_df
        
    except Exception as e:
        st.error(f"❌ Error processing constraints file: {str(e)}")
        import traceback
        st.error(traceback.format_exc())
        return None


def apply_constraints_to_data(data, constraints_df, rate_data=None):
    """
    Apply constraints to data based on priority score
    
    Args:
        data: DataFrame with comprehensive data
        constraints_df: DataFrame with constraints sorted by priority
        rate_data: Optional DataFrame with rate data (used to find capable carriers for lanes)
    
    Returns:
        constrained_data: DataFrame with containers locked by constraints
        unconstrained_data: DataFrame with remaining containers for scenarios
        constraint_summary: List of applied constraints with details
        max_constrained_carriers: List of dicts, each with 'carrier' and scope filters
                                   (category, lane, port, week). None scope values mean global.
                                   These carriers should NOT receive additional volume in optimization
                                   for groups matching their constraint scope.
        carrier_facility_exclusions: Dict mapping carrier -> set of excluded facility codes
                                      (carriers cannot receive containers at these facilities)
    
    Maximum Constraint Logic:
        When a carrier has a Maximum Container Count constraint:
        1. Allocate specified amount to constrained table (assigned to target carrier)
        2. Add carrier to max_constrained_carriers exclusion set
        3. Containers remain in unconstrained table (not deleted)
        4. Optimization will exclude this carrier, making containers available to other carriers
        
        IMPORTANT: Maximum constraints only REQUIRE a Carrier field.
        - Carrier (REQUIRED): The carrier to cap
        - Filters (OPTIONAL): Category, Lane, Port, Week Number, Terminal, SSL
        - Containers are NOT removed from unconstrained table
        - Container count is preserved: Original = Constrained + Unconstrained
        - Optimization excludes the carrier, allowing other carriers to use the volume
    
    Excluded FC (Excluded Facility) Logic:
        When a constraint specifies Excluded FC:
        1. REQUIRES a Carrier to be specified
        2. Carrier CANNOT receive containers at that facility in EITHER table
        3. During allocation, containers at excluded facility are skipped
        4. If carrier has containers at excluded facility, they must be reallocated
        5. If reallocation is not possible, the constraint FAILS
        
        Example:
            Carrier=ABC, Excluded FC=IUSF, Maximum=100
            - ABC gets up to 100 containers from facilities OTHER than IUSF
            - ABC cannot receive ANY containers at IUSF (in constrained OR unconstrained)
            - If ABC already has containers at IUSF, they must go to another carrier
    
    Examples:
        Example 1 - Carrier-only maximum:
            Carrier=ABC, Maximum=100
            - Constrained: 100 containers assigned to ABC
            - Unconstrained: ALL containers remain (including ABC's)
            - Optimization: ABC excluded, other carriers can use ABC's containers
            - Container count: Original = Constrained + Unconstrained ✅
        
        Example 2 - Maximum with filters:
            Carrier=ABC, Category=Import, Lane=LAX-CHI, Maximum=100
            - Constrained: 100 containers from Import/LAX-CHI assigned to ABC
            - Unconstrained: ALL containers remain (including ABC's Import/LAX-CHI)
            - Optimization: ABC excluded from Import/LAX-CHI only
            - ABC can still receive containers in OTHER categories/lanes
            - Container count: Original = Constrained + Unconstrained ✅
        
        Example 3 - With Excluded FC:
            Carrier=ABC, Excluded FC=IUSF, Maximum=50
            - Constrained: 50 containers (NOT at IUSF) assigned to ABC
            - Unconstrained: ABC cannot receive containers at IUSF
            - Optimization: ABC blocked, IUSF containers go to other carriers
    """
    
    if constraints_df is None or len(constraints_df) == 0:
        return pd.DataFrame(), data.copy(), [], [], {}, []

    constrained_records = []
    remaining_data = data.copy().reset_index(drop=True)

    # Normalize the constraint Carrier to the spelling that actually exists in the data,
    # case-insensitively. The Carrier value is used two ways downstream — written verbatim
    # as the assignment target (Dray SCAC(FL)/Carrier) and matched against group carriers in
    # the optimizer exclusion (cascading_logic) — both of which are case-sensitive exact
    # string comparisons. So a constraint typed as "TraPac" against data carrying "TRAPAC"
    # would create a phantom carrier and silently fail to exclude the real one. We resolve
    # to the data's spelling rather than blindly uppercasing, because SCAC casing is owned by
    # the source file, and we operate on a fresh copy of constraints_df so the caller's frame
    # is untouched.
    constraints_df = constraints_df.copy()
    if 'Carrier' in constraints_df.columns:
        _carrier_cols = [c for c in ('Dray SCAC(FL)', 'Carrier') if c in remaining_data.columns]
        _carrier_canon_map = {}
        for _col in _carrier_cols:
            for _val in remaining_data[_col].dropna().unique():
                _key = norm_text(_val)
                if _key and _key not in _carrier_canon_map:
                    _carrier_canon_map[_key] = str(_val).strip()

        def _resolve_carrier(val):
            if not is_valid_value(val):
                return val
            return _carrier_canon_map.get(norm_text(val), val)

        constraints_df['Carrier'] = constraints_df['Carrier'].map(_resolve_carrier)
    # Snapshot of the input data BEFORE any allocations run. Percent allocations use this as
    # the denominator so a "30%" rule always means 30% of the original scope volume, even
    # after higher-priority constraints have consumed part of the pool. Indexes are aligned
    # with remaining_data via reset_index, so the same mask selects the same rows in both.
    original_data = remaining_data.copy()
    # Snapshot of original container IDs per row index — survives mutation of remaining_data
    # so we can attribute "missing" containers back to the priorities that claimed them.
    _original_containers_by_idx = (
        remaining_data['Container Numbers'].map(
            lambda s: parse_container_ids(s) if pd.notna(s) else []
        ).to_dict()
        if 'Container Numbers' in remaining_data.columns else {}
    )
    constraint_summary = []
    
    # Collect explanation logs for downloadable report (not displayed in UI)
    explanation_logs = []
    
    def log_explanation(message, level='info'):
        """Add a message to the explanation log for downloadable report"""
        explanation_logs.append({'Level': level.upper(), 'Message': message})
    
    # Track which INDIVIDUAL container IDs have been allocated
    # Key: container_id, Value: dict with {carrier, week, row_idx}
    allocated_containers_tracker = {}

    # Enforce the "broader rule is the carrier's total ceiling" semantic — e.g. if PGLT
    # received 7 containers from a P10 ABE8 lane rule, a later P8 "NYC CD 30%" rule for
    # PGLT subtracts those 7 from the 30% target so PGLT doesn't double-dip across
    # priorities. The tally is derived on demand from allocated_containers_tracker by
    # exact scope containment (see _lookup_carrier_scope_total) rather than a precomputed
    # (port, category) key, so it credits nested earlier rules WITHOUT letting disjoint
    # scopes (different terminal/vessel/week) cannibalize each other.
    def _lookup_carrier_scope_total(carrier, constraint_row):
        """How many containers has `carrier` already received from earlier constraints
        whose source rows fall INSIDE this constraint's scope?

        Counts by EXACT scope containment: we rebuild this constraint's full scope mask
        over the original snapshot (via build_scope_filters — every dimension: Port,
        Category, Lane, Week, Day, Terminal, SSL, Vessel) and tally tracked containers
        assigned to ``carrier`` whose row index is inside that mask. A narrower earlier
        rule nested in this scope (e.g. a lane within a port) still credits this rule, so
        a broader rule remains the carrier's total ceiling — but a DISJOINT earlier rule
        (e.g. a cap on a different Terminal or Vessel) contributes nothing, so disjoint
        caps no longer cannibalize each other's targets. (The old (port, category) key
        ignored Terminal/Vessel/SSL/Week and let a VES_A allocation zero out a T30 rule.)
        """
        if not carrier:
            return 0
        specs = build_scope_filters(constraint_row, original_data)
        mask = pd.Series(True, index=original_data.index)
        for s in specs:
            mask &= s['mask'].reindex(original_data.index, fill_value=False)
        in_scope_rows = set(original_data.index[mask])
        if not in_scope_rows:
            return 0
        carrier_key = norm_text(carrier)
        total = 0
        for meta in allocated_containers_tracker.values():
            if meta.get('row_idx') in in_scope_rows and norm_text(meta.get('carrier')) == carrier_key:
                total += 1
        return total
    
    # Track carriers with MAXIMUM constraints (hard caps)
    # Each entry is a dict with the carrier name and the constraint's scope filters.
    # None values mean "no filter on this dimension" (applies globally for that dimension).
    # Example: {'carrier': 'HDDR', 'category': 'Import', 'lane': 'USNYCREWR', 'port': None, 'week': None}
    max_constrained_carriers = []

    # ========== PRE-SCAN SCOPED MAX CEILINGS ==========
    # A Maximum Container Count constraint caps how many containers its TARGET carrier
    # may hold WITHIN ITS SCOPE — and that cap must bind against EVERY other rule, not
    # just the cap rule's own allocation. Example: "HJBT max 40 on Vessel VIENNA EXPRESS"
    # must hold even when a broader "HJBT min 130 at TIW" rule (different scope, often a
    # different priority) would otherwise pull MORE VIENNA EXPRESS containers onto HJBT.
    # We pre-scan every max rule into a per-(carrier, scope) ceiling and enforce it during
    # allocation, so the bound holds regardless of which constraint priority runs first.
    # Each ceiling: {carrier, mask (over original_data index), cap, allocated, desc}.
    # Single source of truth (also consumed by the peel pile) — see
    # compute_scoped_max_ceilings / ceiling_headroom / credit_ceilings at module scope.
    scoped_max_ceilings = compute_scoped_max_ceilings(constraints_df, original_data)
    # Parallel structure for lockout rules (Max 0 / Percent 0): the over-cap re-home
    # pass must never reassign volume to a carrier banned from that row's scope.
    scoped_lockouts = compute_scoped_lockouts(constraints_df, original_data)

    def _ceiling_headroom(row_index, carrier):
        return ceiling_headroom(scoped_max_ceilings, row_index, carrier)

    def _credit_ceilings(row_index, carrier, n):
        credit_ceilings(scoped_max_ceilings, row_index, carrier, n)

    # ========== PRE-COLLECT ALL CARRIER+FACILITY EXCLUSIONS ==========
    # This ensures exclusions from ALL constraint rows are applied, even exclusion-only rows
    # Key: carrier, Value: set of normalized facility codes
    carrier_facility_exclusions = {}
    
    if 'Excluded FC' in constraints_df.columns and 'Carrier' in constraints_df.columns:
        log_explanation("Pre-collecting facility exclusions from all constraints...", 'info')
        for _, row in constraints_df.iterrows():
            carrier = row.get('Carrier')
            excluded_fc = row.get('Excluded FC')
            
            if pd.notna(carrier) and carrier and pd.notna(excluded_fc) and str(excluded_fc).strip():
                carrier_str = str(carrier).strip()
                normalized_fc = normalize_facility_code(str(excluded_fc).strip())
                
                if carrier_str not in carrier_facility_exclusions:
                    carrier_facility_exclusions[carrier_str] = set()
                
                if normalized_fc not in carrier_facility_exclusions[carrier_str]:
                    carrier_facility_exclusions[carrier_str].add(normalized_fc)
        
        # Log summary of exclusions found
        if carrier_facility_exclusions:
            for carrier, facilities in carrier_facility_exclusions.items():
                log_explanation(f"{carrier}: Excluded from facilities: {', '.join(sorted(facilities))}", 'exclusion')
    
    # ========== APPLY EXCLUSIONS TO REMAINING DATA ==========
    # Remove carrier assignments where carrier is excluded from facility
    # AND reallocate to an available carrier that can serve the lane
    if carrier_facility_exclusions and 'Facility' in remaining_data.columns:
        log_explanation("Applying facility exclusions and reallocating containers...", 'info')

        carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in remaining_data.columns else 'Carrier'
        lane_col = 'Lane' if 'Lane' in remaining_data.columns else None

        containers_reallocated = 0
        containers_failed = 0

        # Pre-compute normalized facility column once (avoids repeated .apply per carrier)
        facility_normalized = remaining_data['Facility'].apply(normalize_facility_code)

        # Pre-build lane -> carrier set lookup (vectorized)
        lane_carriers_map = {}
        if lane_col:
            lane_carriers_map = remaining_data.groupby('Lane')[carrier_col].apply(
                lambda s: set(v for v in s.unique() if pd.notna(v) and str(v).strip())
            ).to_dict()

        # Pre-extract rate data carriers per lane (vectorized, done once)
        rate_lane_carriers = {}
        if rate_data is not None and 'Lane' in rate_data.columns and 'Lookup' in rate_data.columns:
            rate_data_valid = rate_data[rate_data['Lookup'].notna() & (rate_data['Lookup'].str.len() >= 4)]
            rate_data_valid = rate_data_valid.copy()
            rate_data_valid['_scac'] = rate_data_valid['Lookup'].str[:4]
            rate_lane_carriers = rate_data_valid.groupby('Lane')['_scac'].apply(
                lambda s: set(v for v in s.unique() if v.strip())
            ).to_dict()

        for carrier, excluded_facilities in carrier_facility_exclusions.items():
            carrier_match = remaining_data[carrier_col] == carrier
            facility_excluded = facility_normalized.isin(excluded_facilities)

            violation_mask = carrier_match & facility_excluded
            if not violation_mask.any():
                continue

            violation_df = remaining_data.loc[violation_mask, ['Facility', 'Lane', 'Container Count']].copy()
            violation_df['_facility_norm'] = facility_normalized[violation_mask]
            log_explanation(f"Found {len(violation_df)} rows with {carrier} at excluded facilities", 'info')

            for idx, vrow in violation_df.iterrows():
                facility = vrow['Facility']
                facility_norm = vrow['_facility_norm']
                lane = vrow['Lane'] if lane_col else ''
                container_count = vrow['Container Count'] if pd.notna(vrow['Container Count']) else 1

                if lane:
                    # Use pre-built lane lookup instead of filtering per row
                    carriers_on_lane = lane_carriers_map.get(lane, set())
                    available_carriers = [
                        alt for alt in carriers_on_lane
                        if alt != carrier and facility_norm not in carrier_facility_exclusions.get(alt, set())
                    ]

                    if not available_carriers:
                        # Use pre-built rate data lookup
                        rate_carriers = rate_lane_carriers.get(lane, set())
                        available_carriers = [
                            alt for alt in rate_carriers
                            if alt != carrier and alt.strip() and
                            facility_norm not in carrier_facility_exclusions.get(alt, set())
                        ]
                        if available_carriers:
                            log_explanation(f"Found {len(available_carriers)} capable carrier(s) from rate data for lane {lane}: {', '.join(list(available_carriers)[:5])}", 'info')

                    if available_carriers:
                        new_carrier = available_carriers[0]
                        remaining_data.loc[idx, carrier_col] = new_carrier
                        if 'Carrier' in remaining_data.columns and carrier_col != 'Carrier':
                            remaining_data.loc[idx, 'Carrier'] = new_carrier
                        containers_reallocated += container_count
                        log_explanation(f"Reallocated {container_count} container(s) at {facility} from {carrier} → {new_carrier}", 'reallocation')
                    else:
                        remaining_data.loc[idx, carrier_col] = ''
                        if 'Carrier' in remaining_data.columns and carrier_col != 'Carrier':
                            remaining_data.loc[idx, 'Carrier'] = ''
                        containers_failed += container_count
                        log_explanation(f"No available carrier for {container_count} container(s) at {facility} (lane: {lane})", 'warning')
                else:
                    remaining_data.loc[idx, carrier_col] = ''
                    if 'Carrier' in remaining_data.columns and carrier_col != 'Carrier':
                        remaining_data.loc[idx, 'Carrier'] = ''
                    containers_failed += container_count
                    log_explanation(f"No lane info for container at {facility} - cleared carrier", 'warning')

        if containers_reallocated > 0:
            log_explanation(f"Successfully reallocated {containers_reallocated} containers to available carriers", 'success')
        if containers_failed > 0:
            log_explanation(f"{containers_failed} containers could not be reallocated (no available carrier)", 'warning')
            log_explanation("These containers will need to be handled by optimization scenarios", 'info')
    
    log_explanation(f"Applying {len(constraints_df)} constraints...", 'info')

    # Pre-compute normalized facility codes for the constraint loop (avoids repeated .apply)
    _facility_norm_series = (
        remaining_data['Facility'].apply(normalize_facility_code)
        if 'Facility' in remaining_data.columns else pd.Series(dtype='object')
    )

    def _attribute_claimed_containers(filter_mask, exclude_priority=None):
        """For rows matching filter_mask, count which prior priorities claimed their containers.

        Returns (claimed_total, claimed_by_priority dict). Uses the original snapshot of
        container IDs so it sees claimed containers even after their row was zeroed out.
        Containers claimed by `exclude_priority` (the current constraint) are skipped.
        """
        claimed_by_priority = {}
        claimed_total = 0
        for row_idx in remaining_data.index[filter_mask]:
            for cid in _original_containers_by_idx.get(row_idx, []):
                meta = allocated_containers_tracker.get(cid)
                if meta is None:
                    continue
                p = meta.get('priority')
                if exclude_priority is not None and p == exclude_priority:
                    continue
                claimed_by_priority[p] = claimed_by_priority.get(p, 0) + 1
                claimed_total += 1
        return claimed_total, claimed_by_priority

    def _format_claimed_by(claimed_by):
        if not claimed_by:
            return None
        parts = [f"Priority {p} ({n})" for p, n in sorted(claimed_by.items(), key=lambda kv: -kv[1])]
        return ', '.join(parts)

    def _build_scope_dict(constraint, target_carrier=None, excluded_facilities=None):
        """Capture the constraint's filter values for the summary."""
        scope = {}
        for field in ('Category', 'Lane', 'Port', 'Week Number', 'Day of Week',
                      'Terminal', 'SSL', 'Vessel'):
            val = constraint.get(field)
            if pd.notna(val) and not (isinstance(val, str) and val.strip() == ''):
                if field in ('Week Number', 'Day of Week'):
                    scope[field] = int(val)
                else:
                    scope[field] = val
        if target_carrier:
            scope['Target Carrier'] = target_carrier
        if excluded_facilities:
            scope['Excluded Facilities'] = sorted(excluded_facilities)
        return scope

    for idx, constraint in constraints_df.iterrows():
        # Build filter mask based on provided constraint fields
        # NOTE: Carrier is NOT a filter - it's the TARGET carrier to assign containers to
        mask = pd.Series([True] * len(remaining_data), index=remaining_data.index)

        constraint_desc = f"Priority {constraint['Priority Score']}: "
        filters_applied = []

        # Store target carrier (this is who we're assigning TO, not filtering BY)
        target_carrier = constraint['Carrier'] if is_valid_value(constraint['Carrier']) else None

        # Store excluded facility if specified
        excluded_facility = constraint['Excluded FC'] if is_valid_value(constraint.get('Excluded FC')) else None

        # If Excluded FC is specified, we MUST have a carrier
        if excluded_facility and not target_carrier:
            log_explanation(f"ERROR: Excluded FC requires a Carrier to be specified!", 'error')
            constraint_summary.append({
                'priority': constraint['Priority Score'],
                'description': f"Priority {constraint['Priority Score']}: Excluded FC without Carrier",
                'status': 'Error: Excluded FC requires Carrier',
                'containers_allocated': 0,
                'eligible_containers': 0,
                'scope': _build_scope_dict(constraint, excluded_facilities=[excluded_facility]),
                'reason': (
                    f"Constraint malformed: 'Excluded FC' was set to {excluded_facility} but no "
                    "'Carrier' was provided. Add a Carrier so the exclusion has a target."
                ),
            })
            continue

        # Apply each active scope filter. build_scope_filters is the single source of
        # truth for which dimensions this constraint scopes on — the same helper drives
        # the per-filter failure diagnosis below, so eligibility and the "why nothing
        # matched" explanation can never disagree about which filters were active.
        # NOTE: Carrier is intentionally absent — it's the TARGET assignment, not a filter.
        for spec in build_scope_filters(constraint, remaining_data):
            mask &= spec['mask']
            filters_applied.append(spec['desc'])

        # CRITICAL: If Excluded FC is specified, we need to filter OUT rows at that facility
        # This prevents the carrier from being allocated containers at that facility
        # Normalize facility codes to first 4 characters for comparison (e.g., HGR6-5 -> HGR6)
        
        # IMPORTANT: Use the pre-collected carrier_facility_exclusions dict
        # This ensures ALL exclusions for this carrier are applied, including from exclusion-only rows
        all_excluded_facilities = []
        
        # First, add the current constraint's excluded facility if specified
        if excluded_facility:
            all_excluded_facilities.append(normalize_facility_code(excluded_facility))
        
        # Then, add ALL pre-collected exclusions for this carrier
        # This ensures exclusions from exclusion-only rows (no allocation amount) are still applied
        if target_carrier and target_carrier in carrier_facility_exclusions:
            for exc_fc in carrier_facility_exclusions[target_carrier]:
                if exc_fc not in all_excluded_facilities:
                    all_excluded_facilities.append(exc_fc)
            
            if len(all_excluded_facilities) > 0:
                log_explanation(f"Applying {len(all_excluded_facilities)} facility exclusion(s) for {target_carrier}: {', '.join(sorted(all_excluded_facilities))}", 'info')
        
        # Snapshot the scope-only mask BEFORE excluded-facility filtering, so attribution
        # can distinguish "claimed by another constraint" from "removed by exclusion rule".
        scope_only_mask = mask.copy()

        # Apply all excluded facilities to the mask (uses pre-computed normalized series)
        excluded_facility_mask = None
        if all_excluded_facilities and 'Facility' in remaining_data.columns:
            # Single vectorized isin check instead of per-facility .apply loop
            combined_exclusion_mask = _facility_norm_series.reindex(remaining_data.index).isin(all_excluded_facilities)
            mask &= ~combined_exclusion_mask
            for exc_fc in all_excluded_facilities:
                filters_applied.append(f"Excluding Facility={exc_fc}")
            excluded_count = combined_exclusion_mask.sum()
            if excluded_count > 0:
                log_explanation(f"Excluding {excluded_count} rows at {len(all_excluded_facilities)} facility(s) for {target_carrier if target_carrier else 'carrier'}", 'exclusion')
            excluded_facility_mask = combined_exclusion_mask

        
        # Add target carrier to description
        filter_desc = ", ".join(filters_applied) if filters_applied else "All data"
        if target_carrier:
            constraint_desc += f"{filter_desc} → Assign to {target_carrier}"
        else:
            constraint_desc += filter_desc
        
        # Get eligible data that matches the filter mask
        eligible_data = remaining_data[mask].copy()

        # Vectorized available-container counting (avoids iterrows)
        def _count_available(cn_str):
            ids = parse_container_ids(cn_str if pd.notna(cn_str) else '')
            return sum(1 for cid in ids if cid not in allocated_containers_tracker)

        eligible_data['_available_containers'] = (
            eligible_data['Container Numbers'].map(_count_available)
            if 'Container Numbers' in eligible_data.columns
            else 0
        )
        eligible_data = eligible_data[eligible_data['_available_containers'] > 0].copy()

        # Original pool size for percent calculations: count containers in the same scope
        # against the snapshot taken before any constraints ran. This freezes the denominator
        # so "30%" always means 30% of the original eligible volume regardless of how much
        # earlier-priority constraints have already claimed.
        original_scope_data = original_data[mask]
        if 'Container Numbers' in original_scope_data.columns:
            original_pool_size = int(
                original_scope_data['Container Numbers'].map(
                    lambda s: len(parse_container_ids(s)) if pd.notna(s) else 0
                ).sum()
            )
        else:
            original_pool_size = 0
        
        # Check if this is a maximum constraint - if so, validate we have a carrier
        is_potential_max_constraint = (
            pd.notna(constraint.get('Maximum Container Count')) and 
            constraint['Maximum Container Count'] > 0
        )
        
        if len(eligible_data) == 0:
            # For maximum constraints with carrier only, this might be OK if we're removing all carrier data
            if is_potential_max_constraint and target_carrier:
                log_explanation(f"No containers matching filters for constraint: {constraint_desc}", 'info')
                log_explanation(f"Will proceed to remove ANY existing {target_carrier} containers from unconstrained table", 'info')
                # Continue to process the constraint to remove carrier from unconstrained table
                total_eligible_containers = 0
            else:
                log_explanation(f"No eligible data for constraint: {constraint_desc}", 'warning')
                # Attribution: did higher-priority constraints already claim what would have matched?
                claimed_total, claimed_by_priority = _attribute_claimed_containers(
                    scope_only_mask, exclude_priority=constraint['Priority Score']
                )
                claimed_by_str = _format_claimed_by(claimed_by_priority)
                # Diagnose why: claimed by others, excluded facilities, or just zero filter matches?
                if claimed_total > 0:
                    no_match_reason = (
                        f"All {claimed_total} container(s) that matched this constraint's scope "
                        f"were already claimed by higher-priority constraint(s): {claimed_by_str}. "
                        "Lower the other constraint(s)' allocations or raise this constraint's priority."
                    )
                elif all_excluded_facilities and excluded_facility_mask is not None and excluded_facility_mask.any():
                    excluded_n = int(excluded_facility_mask.sum())
                    no_match_reason = (
                        f"No containers matched the constraint filters after removing {excluded_n} row(s) "
                        f"at excluded facilities ({', '.join(sorted(all_excluded_facilities))}). "
                        "Check that scope filters and exclusions don't fully eliminate the data."
                    )
                else:
                    # Pinpoint the culprit filter(s) against the pristine source snapshot:
                    # name the dimension(s) whose value is absent from the data, or — if every
                    # filter matches on its own — flag the combination as too narrow.
                    _, diagnosed = diagnose_no_match(constraint, original_data)
                    if diagnosed:
                        no_match_reason = diagnosed
                    else:
                        no_match_reason = (
                            "No containers matched this constraint, and it defines no scope "
                            "filters to blame. Verify the source data is non-empty for this run."
                        )
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'Failed: No matching data',
                    'containers_allocated': 0,
                    'eligible_containers': 0,
                    'claimed_by': claimed_by_priority or None,
                    'scope': _build_scope_dict(constraint, target_carrier, all_excluded_facilities),
                    'reason': no_match_reason,
                })
                continue
        else:
            total_eligible_containers = eligible_data['_available_containers'].sum()
        
        # Determine how many containers to allocate
        target_containers = None
        allocation_method = None
        is_maximum_constraint = False  # Track if this is a hard cap

        # Unified allocation: Percent sets the base target, Min/Max are hard bounds
        # Priority: Percent computes target → clamped by Min (floor) → clamped by Max (ceiling)
        has_max = pd.notna(constraint['Maximum Container Count']) and constraint['Maximum Container Count'] > 0
        has_min = pd.notna(constraint['Minimum Container Count']) and constraint['Minimum Container Count'] > 0
        has_pct = pd.notna(constraint['Percent Allocation']) and constraint['Percent Allocation'] > 0

        # Lockout: Percent Allocation == 0 or Maximum Container Count == 0 means the user
        # wants this carrier blocked from receiving any containers in this scope (allocate
        # nothing AND keep the optimizer from sending volume here). Detect before the
        # has_max/has_min/has_pct gate, since both 0% and max=0 would otherwise fall through
        # to "No allocation amount" and silently leave the carrier as a free target.
        is_zero_pct = (
            pd.notna(constraint.get('Percent Allocation'))
            and constraint['Percent Allocation'] == 0
        )
        is_zero_max = (
            pd.notna(constraint.get('Maximum Container Count'))
            and constraint['Maximum Container Count'] == 0
        )
        if (is_zero_pct or is_zero_max) and target_carrier:
            method_label = "0% (lockout)" if is_zero_pct else "max 0 (lockout)"
            log_explanation(
                f"Lockout: {target_carrier} blocked from this scope ({method_label})",
                'block'
            )
            max_constrained_carriers.append({
                'carrier': target_carrier,
                'category': constraint.get('Category') if is_valid_value(constraint.get('Category')) else None,
                'lane': constraint.get('Lane') if is_valid_value(constraint.get('Lane')) else None,
                'port': constraint.get('Port') if is_valid_value(constraint.get('Port')) else None,
                'week': constraint.get('Week Number') if is_valid_value(constraint.get('Week Number')) else None,
                'day': constraint.get('Day of Week') if is_valid_value(constraint.get('Day of Week')) else None,
            })
            constraint_summary.append({
                'priority': constraint['Priority Score'],
                'description': constraint_desc,
                'status': 'Applied (Lockout)',
                'containers_allocated': 0,
                'eligible_containers': int(total_eligible_containers),
                'method': method_label,
                'scope': _build_scope_dict(constraint, target_carrier, all_excluded_facilities),
                'reason': (
                    f"{target_carrier} is locked out of this scope. The optimizer will not "
                    "send any containers to this carrier in matching groups."
                ),
            })
            continue

        if has_max or has_min or has_pct:
            # Validation: Max constraints require a carrier
            if has_max and not target_carrier:
                log_explanation(f"ERROR: Maximum Container Count constraint requires a Carrier to be specified!", 'error')
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'Error: No carrier specified for maximum constraint',
                    'containers_allocated': 0,
                    'eligible_containers': int(total_eligible_containers),
                    'scope': _build_scope_dict(constraint, target_carrier, all_excluded_facilities),
                    'reason': (
                        "Constraint malformed: 'Maximum Container Count' was set but no 'Carrier' "
                        "was provided. Maximum constraints must name the carrier being capped."
                    ),
                })
                continue

            # Look up how much this carrier has already received from earlier (higher-priority)
            # constraints in the same (port, category) scope. Used as a credit against the
            # current rule so a broader rule serves as the carrier's total ceiling rather
            # than additional volume on top of narrower lane-level rules.
            already_allocated_in_scope = _lookup_carrier_scope_total(target_carrier, constraint)

            # Step 1: Compute base target.
            # For percent, the denominator is the ORIGINAL pool (snapshot before any
            # constraints ran) so "30%" always means 30% of the original scope volume.
            # If the original-pool target can't fit in what's actually still available,
            # fall back to "30% of what's left" so we degrade gracefully instead of
            # silently over-allocating or failing.
            pct_target_against_original = None    # set only when percent is in play
            pct_used_remainder_fallback = False    # toggled when we fell back
            if has_pct:
                percent_value = constraint['Percent Allocation'] / 100

                original_target_raw = original_pool_size * percent_value
                if 0 < original_target_raw < 1:
                    pct_target_against_original = 1
                else:
                    pct_target_against_original = math.ceil(original_target_raw)

                if pct_target_against_original <= total_eligible_containers:
                    target_containers = pct_target_against_original
                else:
                    # Not enough containers left to satisfy the original-pool target —
                    # take the same percent of what's still available.
                    pct_used_remainder_fallback = True
                    fallback_raw = total_eligible_containers * percent_value
                    if 0 < fallback_raw < 1:
                        target_containers = 1
                    else:
                        target_containers = math.ceil(fallback_raw)
                    log_explanation(
                        f"Original-pool target ({pct_target_against_original}) exceeds remaining "
                        f"eligible ({int(total_eligible_containers)}); falling back to "
                        f"{constraint['Percent Allocation']}% of remainder "
                        f"({int(total_eligible_containers)}) = {target_containers}",
                        'info'
                    )
            elif has_min and not has_max:
                target_containers = int(constraint['Minimum Container Count'])
            elif has_max:
                target_containers = int(constraint['Maximum Container Count'])
            else:
                target_containers = total_eligible_containers

            # Step 2: Apply minimum floor
            if has_min:
                requested_minimum = int(constraint['Minimum Container Count'])
                target_containers = max(target_containers, requested_minimum)

            # Step 3: Apply maximum ceiling
            if has_max:
                requested_maximum = int(constraint['Maximum Container Count'])
                target_containers = min(target_containers, requested_maximum)

            # Step 3b: Cumulative cap across priorities — subtract what this carrier already
            # received in this (port, category) scope from earlier constraints. The lower-
            # priority broader rule (e.g. "PGLT NYC CD 30%") becomes the carrier's total
            # ceiling, not extra volume on top of the higher-priority narrow rule (e.g.
            # "PGLT ABE8 70%"). Only applied when the current rule is BROADER (no Lane);
            # narrow lane-level rules don't get clipped by themselves.
            if (
                target_carrier
                and already_allocated_in_scope > 0
                and (has_pct or has_max)
                and not is_valid_value(constraint.get('Lane'))
            ):
                clipped = max(0, target_containers - already_allocated_in_scope)
                if clipped < target_containers:
                    log_explanation(
                        f"{target_carrier} already has {already_allocated_in_scope} container(s) "
                        f"in this scope from higher-priority constraints; "
                        f"reducing target from {target_containers} to {clipped}",
                        'info'
                    )
                target_containers = clipped

            # Step 4: Can't exceed what's available
            target_containers = min(target_containers, total_eligible_containers)

            # Handle case where max constraint has 0 eligible but still needs exclusion
            if has_max and total_eligible_containers == 0:
                target_containers = 0

            # Build allocation method description. Percent normally references the original
            # pool; when fallback fired, surface the remainder denominator so callers can
            # see why the count is below the original-pool target.
            method_parts = []
            if has_pct:
                if pct_used_remainder_fallback:
                    method_parts.append(
                        f"{constraint['Percent Allocation']}% of {int(total_eligible_containers)} "
                        f"(remainder; original pool was {original_pool_size}, target "
                        f"{pct_target_against_original}) = {target_containers}"
                    )
                else:
                    method_parts.append(
                        f"{constraint['Percent Allocation']}% of {int(original_pool_size)} = "
                        f"{pct_target_against_original}"
                    )
            if has_min:
                method_parts.append(f"min {int(constraint['Minimum Container Count'])}")
            if has_max:
                method_parts.append(f"max {int(constraint['Maximum Container Count'])}")
            allocation_method = f"{' | '.join(method_parts)} → {target_containers} containers"

            # Flag as maximum constraint if max is set (hard cap for optimizer)
            if has_max:
                is_maximum_constraint = True
                max_constrained_carriers.append({
                    'carrier': target_carrier,
                    'category': constraint.get('Category') if is_valid_value(constraint.get('Category')) else None,
                    'lane': constraint.get('Lane') if is_valid_value(constraint.get('Lane')) else None,
                    'port': constraint.get('Port') if is_valid_value(constraint.get('Port')) else None,
                    'week': constraint.get('Week Number') if is_valid_value(constraint.get('Week Number')) else None,
                    'day': constraint.get('Day of Week') if is_valid_value(constraint.get('Day of Week')) else None,
                })

            # Percent-only constraints also exclude carrier from optimizer
            # (percent defines their total share — optimizer should not add more)
            if has_pct and not has_max and target_carrier:
                is_maximum_constraint = True
                max_constrained_carriers.append({
                    'carrier': target_carrier,
                    'category': constraint.get('Category') if is_valid_value(constraint.get('Category')) else None,
                    'lane': constraint.get('Lane') if is_valid_value(constraint.get('Lane')) else None,
                    'port': constraint.get('Port') if is_valid_value(constraint.get('Port')) else None,
                    'week': constraint.get('Week Number') if is_valid_value(constraint.get('Week Number')) else None,
                    'day': constraint.get('Day of Week') if is_valid_value(constraint.get('Day of Week')) else None,
                })

            # Warn on minimum shortfall
            if has_min and target_containers < int(constraint['Minimum Container Count']):
                shortfall = int(constraint['Minimum Container Count']) - target_containers
                log_explanation(
                    f"WARNING: Minimum requires {int(constraint['Minimum Container Count'])} containers "
                    f"but only {target_containers} achievable (shortfall: {shortfall})",
                    'warning'
                )
                allocation_method += f" (SHORTFALL: {shortfall})"

        else:
            # No allocation amount specified
            # Check if this is an exclusion-only constraint (has Excluded FC but no allocation)
            # Exclusion-only constraints are considered "Applied" because the exclusion is enforced
            # via the pre-collection mechanism at the start of this function
            if excluded_facility and target_carrier:
                # This is an exclusion-only constraint - it's valid and applied via pre-collection
                log_explanation(f"Exclusion-only constraint: {constraint_desc}", 'info')
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'Applied (Exclusion Rule)',
                    'containers_allocated': 0,
                    'eligible_containers': int(total_eligible_containers),
                    'method': f"Exclusion: {target_carrier} blocked from {excluded_facility}",
                    'scope': _build_scope_dict(constraint, target_carrier, all_excluded_facilities),
                    'reason': (
                        f"Exclusion rule active: {target_carrier} is blocked from {excluded_facility}. "
                        "No containers are allocated by this rule itself; it constrains other allocations."
                    ),
                })
                continue
            else:
                # Truly no allocation amount and no exclusion - skip
                log_explanation(f"No allocation amount specified for constraint: {constraint_desc}", 'warning')
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'No allocation amount',
                    'containers_allocated': 0,
                    'eligible_containers': int(total_eligible_containers),
                    'scope': _build_scope_dict(constraint, target_carrier, all_excluded_facilities),
                    'reason': (
                        "No 'Maximum', 'Minimum', 'Percent Allocation', or 'Excluded FC' was set. "
                        "Add at least one to make this constraint actionable."
                    ),
                })
                continue
        
        # Allocate containers at the CONTAINER ID level (not just counts)
        allocated_containers_count = 0

        # Only process allocation if we have containers to allocate
        if target_containers > 0 and len(eligible_data) > 0:
            # Sort by week for consistency; this is also the order rows are visited
            # WITHIN each day bucket below.
            allocation_data = eligible_data.sort_values('Week Number')

            def _allocate_from_row(row_idx, row, want):
                """Allocate up to ``want`` containers from a single row to the target
                carrier, honoring the scoped-max ceiling. Builds the constrained record,
                credits ceilings/scope tallies, and decrements remaining_data. Returns the
                number of containers actually taken (0 if none/headroom exhausted)."""
                if want <= 0:
                    return 0
                # Hard scoped-max ceiling: never let THIS row push the target carrier past
                # a max rule binding this row (e.g. a vessel cap), even when the current
                # constraint is a different (broader) rule like min-130. If a ceiling is
                # exhausted for this row, skip it — those containers stay free for other
                # carriers rather than violating the cap.
                headroom = _ceiling_headroom(row_idx, target_carrier) if target_carrier else None
                if headroom is not None:
                    if headroom <= 0:
                        return 0
                    want = min(want, headroom)

                # Hard lockout: never allocate to a carrier locked out (Max 0 / Percent 0)
                # of THIS row's scope, even when a different, higher-priority rule for the
                # same carrier (e.g. a global min or percent) would otherwise pull volume
                # here. A lockout is inviolable; those containers stay free for other
                # carriers. Without this, a P10 "FRQT 50%" could seat FRQT on a vessel a
                # lower-priority "FRQT max 0 on EVER LOGIC" rule bans it from — and the
                # unconstrained-only enforcement pass would never claw it back.
                if target_carrier and carrier_locked_out(scoped_lockouts, row_idx, target_carrier):
                    return 0

                week_num_local = row.get('Week Number', None)
                allocated_ids, remaining_ids = allocate_specific_containers(
                    row, want, allocated_containers_tracker, target_carrier, week_num_local,
                    priority=constraint['Priority Score']
                )
                if len(allocated_ids) == 0:
                    return 0

                # Create constrained record with ONLY the allocated container IDs
                constrained_record = row.copy()
                constrained_record['Container Numbers'] = join_container_ids(allocated_ids)
                constrained_record['Container Count'] = len(allocated_ids)

                # ASSIGN to target carrier (override existing carrier)
                if target_carrier:
                    if 'Dray SCAC(FL)' in constrained_record.index:
                        constrained_record['Dray SCAC(FL)'] = target_carrier
                    if 'Carrier' in constrained_record.index:
                        constrained_record['Carrier'] = target_carrier

                constrained_record['Constraint_Priority'] = constraint['Priority Score']
                constrained_record['Constraint_Method'] = allocation_method
                constrained_record['Constraint_Description'] = constraint_desc

                constrained_records.append(constrained_record)

                # Credit these containers against every scoped max ceiling that binds
                # this row+carrier, so subsequent rows (and later constraints) see the
                # reduced headroom and the cap holds across the whole run.
                _credit_ceilings(row_idx, target_carrier, len(allocated_ids))

                # Update remaining_data: Remove allocated containers from this row
                if len(remaining_ids) > 0:
                    remaining_data.loc[row_idx, 'Container Numbers'] = join_container_ids(remaining_ids)
                    remaining_data.loc[row_idx, 'Container Count'] = len(remaining_ids)
                else:
                    remaining_data.loc[row_idx, 'Container Count'] = 0
                    remaining_data.loc[row_idx, 'Container Numbers'] = ''

                return len(allocated_ids)

            # ---- Even weekly distribution (round-robin across day-of-week buckets) ----
            # Group the eligible rows into day buckets by their Ocean ETA weekday
            # (Mon, Tue, Wed, Thu, Fri-Sun — weekend collapsed). Give each bucket a
            # round-robin quota of the target, then fill bucket by bucket. This keeps a
            # constraint's volume from piling onto one weekday when the eligible rows
            # span several days. Rows with no parseable day still allocate, via the
            # spill pass below, so the target is never sacrificed to the spread.
            bucket_rows = {}      # bucket -> list of (row_idx, row)
            bucket_caps = {}      # bucket -> available containers in that bucket
            dow_present = 'Day of Week' in allocation_data.columns
            for row_idx, row in allocation_data.iterrows():
                avail = int(row.get('_available_containers', 0) or 0)
                if avail <= 0:
                    continue
                bucket = day_bucket(row.get('Day of Week')) if dow_present else _NO_DOW_BUCKET
                bucket_rows.setdefault(bucket, []).append((row_idx, row))
                bucket_caps[bucket] = bucket_caps.get(bucket, 0) + avail

            # Quota only across DATED buckets — undated rows are not part of the even
            # spread; they backfill any shortfall in the spill pass.
            dated_caps = {b: c for b, c in bucket_caps.items() if b != _NO_DOW_BUCKET}
            quota = round_robin_quota(target_containers, dated_caps) if dated_caps else {}

            # Pass 1 — fill each dated bucket up to its round-robin quota.
            for bucket in bucket_iter_order(dated_caps):
                want_bucket = quota.get(bucket, 0)
                for row_idx, row in bucket_rows.get(bucket, []):
                    if want_bucket <= 0 or allocated_containers_count >= target_containers:
                        break
                    took = _allocate_from_row(row_idx, row, want_bucket)
                    want_bucket -= took
                    allocated_containers_count += took

            # Pass 2 — spill. The quota pass can fall short when a bucket's ceiling
            # headroom blocked it, or when undated rows hold the only volume. Sweep all
            # rows (dated buckets first, in day order, then undated) to top up to target.
            if allocated_containers_count < target_containers:
                spill_order = bucket_iter_order(dated_caps) + (
                    [_NO_DOW_BUCKET] if _NO_DOW_BUCKET in bucket_rows else []
                )
                for bucket in spill_order:
                    for row_idx, row in bucket_rows.get(bucket, []):
                        if allocated_containers_count >= target_containers:
                            break
                        # Re-fetch the live row so we see containers already taken in pass 1.
                        live_row = remaining_data.loc[row_idx]
                        took = _allocate_from_row(
                            row_idx, live_row,
                            target_containers - allocated_containers_count,
                        )
                        allocated_containers_count += took
                    if allocated_containers_count >= target_containers:
                        break

        # (Cumulative cross-priority credit is now derived on demand from
        # allocated_containers_tracker by exact scope containment — see
        # _lookup_carrier_scope_total — so no per-row rollup is needed here.)

        # For maximum constraints, we DON'T remove containers from unconstrained table
        # Instead, we rely on the max_constrained_carriers exclusion list in optimization
        # This preserves container count while ensuring the carrier cannot receive volume
        if is_maximum_constraint and target_carrier:
            # Log that carrier is blocked but containers remain available for other carriers
            log_explanation(f"{target_carrier} added to exclusion list for optimization", 'info')
            log_explanation(f"{target_carrier} will NOT be able to receive ANY containers in optimization", 'warning')
            log_explanation(f"Containers remain in unconstrained table for other carriers to use", 'info')
        
        # CRITICAL: Handle Excluded FC for this constraint
        # If Excluded FC is specified, ensure carrier CANNOT have containers at that facility
        # in BOTH constrained and unconstrained tables
        if excluded_facility and target_carrier:
            # Normalize the excluded facility for comparison
            normalized_excluded_fc = normalize_facility_code(excluded_facility)
            
            # Check constrained records we just added
            facility_violation_in_constrained = False
            if constrained_records:
                for record in constrained_records:
                    if (record.get('Carrier') == target_carrier or record.get('Dray SCAC(FL)') == target_carrier):
                        # Compare normalized facility codes
                        record_facility_normalized = normalize_facility_code(record.get('Facility', ''))
                        if record_facility_normalized == normalized_excluded_fc:
                            facility_violation_in_constrained = True
                            log_explanation(f"Violation found: {record.get('Facility')} matches excluded {excluded_facility}", 'error')
                            break
            
            if facility_violation_in_constrained:
                log_explanation(f"CONSTRAINT FAILED: Cannot allocate {target_carrier} containers to excluded facility {excluded_facility}", 'error')
                log_explanation(f"No alternative carrier available for containers at {excluded_facility}", 'error')
                # Remove the invalid constrained records (using normalized comparison)
                constrained_records = [r for r in constrained_records 
                                     if not ((r.get('Carrier') == target_carrier or r.get('Dray SCAC(FL)') == target_carrier) 
                                            and normalize_facility_code(r.get('Facility', '')) == normalized_excluded_fc)]
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'FAILED: Carrier allocated to excluded facility',
                    'containers_allocated': 0,
                    'eligible_containers': int(total_eligible_containers),
                    'target_containers': target_containers,
                    'method': allocation_method,
                    'scope': _build_scope_dict(constraint, target_carrier, all_excluded_facilities),
                    'reason': (
                        f"Allocation produced records for {target_carrier} at {excluded_facility}, "
                        "which is on its excluded-facility list. No alternative carrier was available "
                        "for those containers, so the entire constraint was rolled back."
                    ),
                })
                continue
            
            # For unconstrained table: Check if carrier has containers at excluded facility
            # These should be reallocated to other carriers (marked for reallocation)
            if 'Facility' in remaining_data.columns:
                carrier_cols = []
                if 'Dray SCAC(FL)' in remaining_data.columns:
                    carrier_cols.append('Dray SCAC(FL)')
                if 'Carrier' in remaining_data.columns:
                    carrier_cols.append('Carrier')
                
                excluded_mask = pd.Series([False] * len(remaining_data), index=remaining_data.index)
                fc_match = _facility_norm_series.reindex(remaining_data.index) == normalized_excluded_fc
                for col in carrier_cols:
                    excluded_mask |= (remaining_data[col] == target_carrier) & fc_match
                
                if excluded_mask.any():
                    excluded_containers = remaining_data.loc[excluded_mask, 'Container Count'].sum()
                    log_explanation(f"Found {excluded_containers} containers for {target_carrier} at excluded facility {excluded_facility} (normalized: {normalized_excluded_fc})", 'warning')
                    log_explanation(f"These containers must be reallocated to other carriers or constraint will fail", 'warning')
                    # Mark carrier for exclusion at this facility (handled by optimization)
        
        # Attribute already-claimed containers in this constraint's scope (always computed —
        # gives "Why" context for partial/zero-allocated cases). Excludes the current priority
        # so we don't self-attribute.
        claimed_total, claimed_by_priority = _attribute_claimed_containers(
            scope_only_mask, exclude_priority=constraint['Priority Score']
        )
        claimed_by_str = _format_claimed_by(claimed_by_priority)

        # Determine status: flag minimum shortfalls
        constraint_status = 'Applied'
        constraint_reason = None
        if (pd.notna(constraint.get('Minimum Container Count')) and
            constraint['Minimum Container Count'] > 0 and
            allocated_containers_count < int(constraint['Minimum Container Count'])):
            requested_min = int(constraint['Minimum Container Count'])
            shortfall = requested_min - allocated_containers_count
            constraint_status = f"Partial (shortfall: {shortfall})"
            # Diagnose: was the eligible pool too small, or did higher-priority constraints consume it?
            if claimed_total > 0:
                constraint_reason = (
                    f"Minimum requested {requested_min}, only {allocated_containers_count} allocated. "
                    f"{claimed_total} container(s) in this scope were already claimed by: {claimed_by_str}."
                )
            elif int(total_eligible_containers) < requested_min:
                constraint_reason = (
                    f"Minimum requested {requested_min} but only {int(total_eligible_containers)} "
                    "containers matched this constraint's filters in the source data. Loosen the scope "
                    "or lower the minimum."
                )
            else:
                constraint_reason = (
                    f"Minimum requested {requested_min} but only {allocated_containers_count} could be "
                    "allocated. Check facility exclusions or other late-stage filters."
                )
        elif (has_pct and pct_target_against_original is not None
              and allocated_containers_count < pct_target_against_original):
            # Percent shortfall: the original-pool target couldn't be met because higher-priority
            # constraints consumed part of the scope. Recomputed against the remainder so we got
            # *something* instead of failing — but flag the gap so the user sees the impact.
            shortfall = pct_target_against_original - allocated_containers_count
            constraint_status = f"Partial (shortfall: {shortfall})"
            if claimed_total > 0:
                constraint_reason = (
                    f"{constraint['Percent Allocation']}% of the original {original_pool_size}-container "
                    f"pool would have been {pct_target_against_original}, but {claimed_total} "
                    f"container(s) were already claimed by: {claimed_by_str}. Allocated "
                    f"{allocated_containers_count} ({constraint['Percent Allocation']}% of the "
                    f"{int(total_eligible_containers)}-container remainder) instead."
                )
            else:
                constraint_reason = (
                    f"{constraint['Percent Allocation']}% of the original {original_pool_size}-container "
                    f"pool would have been {pct_target_against_original}, but the remainder was only "
                    f"{int(total_eligible_containers)}. Allocated {allocated_containers_count} "
                    f"({constraint['Percent Allocation']}% of the remainder) instead."
                )
        elif allocated_containers_count == 0 and target_containers > 0:
            if claimed_total > 0:
                constraint_reason = (
                    f"Target was {target_containers} but no containers were allocated. "
                    f"{claimed_total} container(s) in this scope were already claimed by: {claimed_by_str}."
                )
            else:
                constraint_reason = (
                    f"Target was {target_containers} but no containers were allocated, and none were "
                    "claimed by other constraints. Check facility exclusions or scope filters."
                )

        constraint_summary.append({
            'priority': constraint['Priority Score'],
            'description': constraint_desc,
            'status': constraint_status,
            'containers_allocated': allocated_containers_count,
            'eligible_containers': int(total_eligible_containers),
            'claimed_by': claimed_by_priority or None,
            'target_containers': target_containers,
            'method': allocation_method,
            'scope': _build_scope_dict(constraint, target_carrier, all_excluded_facilities),
            'reason': constraint_reason,
        })
    
    # ========== ENFORCE SCOPED MAX CEILINGS ON THE UNCONSTRAINED TABLE ==========
    # A scoped Maximum caps a carrier's TOTAL volume in its scope — across BOTH the
    # constrained table AND whatever stays in the unconstrained (reoptimizable) table.
    # The constrained side is already capped (headroom logic above), but volume can be
    # left on its ORIGINAL carrier in remaining_data when that carrier's ceiling is full
    # (e.g. a vessel that is over-subscribed: 40 HJBT containers are locked, the rest
    # must not stay on HJBT or the flip/optimizer would report >40 on that vessel).
    # Here we strip any such over-cap carrier off those unconstrained rows so the cap
    # holds end-to-end: reassign to an eligible alternate carrier on the lane if one
    # exists, otherwise clear the carrier (the scenario optimizer then places it, and
    # the lockout list keeps it off the capped carrier).
    if (scoped_max_ceilings or scoped_lockouts) and len(remaining_data) > 0:
        carrier_col_rd = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in remaining_data.columns else 'Carrier'
        lane_carriers_rd = {}
        if 'Lane' in remaining_data.columns:
            lane_carriers_rd = remaining_data.groupby('Lane')[carrier_col_rd].apply(
                lambda s: set(v for v in s.unique() if pd.notna(v) and str(v).strip())
            ).to_dict()
        rate_lane_carriers_rd = {}
        if rate_data is not None and 'Lane' in rate_data.columns and 'Lookup' in rate_data.columns:
            _rv = rate_data[rate_data['Lookup'].notna() & (rate_data['Lookup'].astype(str).str.len() >= 4)].copy()
            _rv['_scac'] = _rv['Lookup'].astype(str).str[:4]
            rate_lane_carriers_rd = _rv.groupby('Lane')['_scac'].apply(
                lambda s: set(v for v in s.unique() if pd.notna(v) and str(v).strip())
            ).to_dict()

        def _overcap_carrier_for_row(idx, carrier):
            """True if `carrier` has NO remaining headroom in a ceiling binding this row."""
            if not carrier:
                return False
            ck = norm_text(carrier)
            for _ceil in scoped_max_ceilings:
                if norm_text(_ceil['carrier']) != ck:
                    continue
                m = _ceil['mask']
                if idx in m.index and bool(m.loc[idx]) and (_ceil['cap'] - _ceil['allocated']) <= 0:
                    return True
            return False

        def _row_count(idx):
            try:
                v = remaining_data.at[idx, 'Container Count']
                return int(v) if pd.notna(v) else 0
            except Exception:
                return 0

        stripped = 0
        for idx in remaining_data.index:
            cur = remaining_data.at[idx, carrier_col_rd] if carrier_col_rd in remaining_data.columns else None
            if not cur or pd.isna(cur):
                continue
            row_count = _row_count(idx)
            locked = carrier_locked_out(scoped_lockouts, idx, cur)
            # Residual headroom for the CURRENT carrier under any max ceiling binding this
            # row. None = no ceiling applies (unbounded). The constrained pass already
            # credited its allocations, so this is what's LEFT after the constrained side.
            hr_cur = _ceiling_headroom(idx, cur) if not locked else None

            # Keep this row on its current carrier only if it is not locked out AND either
            # no cap binds it (hr_cur is None) or the whole row still fits under the cap.
            # Crucially, when a Max sits ABOVE a smaller Percent/Min target, the constrained
            # side stops at the smaller target and leaves residual headroom — pre-existing
            # unconstrained volume on the capped carrier must CONSUME that headroom and the
            # excess must be stripped, or the carrier ends up over its cap across both tables.
            if not locked and (hr_cur is None or hr_cur >= row_count):
                if hr_cur is not None and row_count > 0:
                    _credit_ceilings(idx, cur, row_count)  # consume headroom for later rows
                continue

            # Over cap (or headroom too small for the whole row) or locked out → re-home.
            # Find an alternate carrier on this lane that is not itself over-cap here, not
            # locked out, and not excluded from this row's facility.
            lane = remaining_data.at[idx, 'Lane'] if 'Lane' in remaining_data.columns else ''
            candidates = (lane_carriers_rd.get(lane, set()) | rate_lane_carriers_rd.get(lane, set()))
            # This row's normalized facility, so we never re-home onto a carrier that is
            # excluded from it (would trade a cap/lockout breach for an exclusion breach).
            row_fac_norm = (
                _facility_norm_series.get(idx)
                if 'Facility' in remaining_data.columns else None
            )
            alt = None
            for c in sorted(candidates):
                if norm_text(c) == norm_text(cur):
                    continue
                # Alternate must have room for the WHOLE row under its own ceiling, else
                # re-homing here would just breach a different carrier's cap.
                hr_c = _ceiling_headroom(idx, c)
                if hr_c is not None and hr_c < row_count:
                    continue
                # Never re-home onto a carrier locked out of this row's scope
                # (e.g. AOYV is Max-0 at TIW): that would trade a cap breach for a
                # lockout breach. Skip such candidates so the row clears instead.
                if carrier_locked_out(scoped_lockouts, idx, c):
                    continue
                # Never re-home onto a carrier excluded from this row's facility
                # (e.g. FRQT is Excluded-FC at BFI3): the exclusion is just as hard as
                # a lockout. Skip so the row clears rather than breaching the exclusion.
                if (row_fac_norm is not None
                        and row_fac_norm in carrier_facility_exclusions.get(c, set())):
                    continue
                alt = c
                break
            remaining_data.at[idx, carrier_col_rd] = alt if alt else ''
            if 'Carrier' in remaining_data.columns and carrier_col_rd != 'Carrier':
                remaining_data.at[idx, 'Carrier'] = alt if alt else ''
            # Credit the row against the alternate's ceilings so a later row in the same
            # scope sees the reduced headroom (prevents piling onto one alternate).
            if alt and row_count > 0:
                _credit_ceilings(idx, alt, row_count)
            stripped += 1
        if stripped:
            log_explanation(
                f"Scoped-max / lockout enforcement: moved {stripped} unconstrained row(s) off "
                "carriers that had exhausted their max ceiling in-scope or were locked out of "
                "the row's scope, so caps and lockouts hold across the unconstrained allocation too.",
                'info'
            )

    # Remove rows with zero containers from remaining data
    remaining_data = remaining_data[remaining_data['Container Count'] > 0].copy()

    # Create constrained dataframe
    if constrained_records:
        constrained_data = pd.DataFrame(constrained_records)
    else:
        constrained_data = pd.DataFrame()
    
    # Summary - log to explanation sheet instead of UI
    total_constrained = constrained_data['Container Count'].sum() if len(constrained_data) > 0 else 0
    total_unconstrained = remaining_data['Container Count'].sum()
    total_original = data['Container Count'].sum()
    
    log_explanation(f"Constraint Application Summary:", 'summary')
    log_explanation(f"Original containers: {total_original:,}", 'summary')
    log_explanation(f"Constrained containers: {total_constrained:,}", 'summary')
    log_explanation(f"Unconstrained containers: {total_unconstrained:,}", 'summary')
    log_explanation(f"Total after split: {total_constrained + total_unconstrained:,}", 'summary')
    
    if abs(total_original - (total_constrained + total_unconstrained)) > 0.01:
        log_explanation(f"Container mismatch! Lost {total_original - (total_constrained + total_unconstrained):,.0f} containers", 'error')
    
    # Log carriers with maximum constraints (hard caps)
    if max_constrained_carriers:
        carrier_names = sorted({mc['carrier'] for mc in max_constrained_carriers})
        log_explanation(f"Carriers with Maximum Constraints (Hard Caps): {', '.join(carrier_names)}", 'info')
        log_explanation(f"These carriers will NOT receive additional volume in matching optimization groups.", 'info')
        for mc in max_constrained_carriers:
            scope_parts = [f"{k}={v}" for k, v in mc.items() if k != 'carrier' and v is not None]
            scope_desc = ', '.join(scope_parts) if scope_parts else 'Global'
            log_explanation(f"  {mc['carrier']}: scope = {scope_desc}", 'info')
    
    # Log carrier+facility exclusions summary
    if carrier_facility_exclusions:
        for carrier, facilities in carrier_facility_exclusions.items():
            log_explanation(f"Carrier+Facility Exclusion: {carrier} excluded from {', '.join(sorted(facilities))}", 'exclusion')
    
    return constrained_data, remaining_data, constraint_summary, max_constrained_carriers, carrier_facility_exclusions, explanation_logs


def _filter_summary_by_active_ports(constraint_summary):
    """Hide constraints whose Port scope doesn't intersect the active Port filter.

    The Applied Constraints Summary is built from the FULL constraint set, but the
    rest of the view is narrowed by the sidebar Port filter. Without this, filtering
    to (say) TIW still lists SAV-scoped constraints with Allocated=0, which reads as
    "the filter isn't working". We keep:
      - constraints with no Port scope (global — apply everywhere), and
      - constraints whose Port resolves to at least one of the active ports.
    A constraint's Port shorthand (e.g. 'NYC') is expanded via resolve_port_filter
    to the same Discharged Port codes the sidebar filter stores, then compared
    case/space-insensitively. When no Port filter is active, nothing is hidden.
    """
    active_ports = st.session_state.get('filter_ports') or []
    if not active_ports:
        return constraint_summary

    active_norm = {norm_text(p) for p in active_ports}
    kept = []
    for item in constraint_summary:
        scope = item.get('scope') or {}
        port_val = scope.get('Port')
        if not is_valid_value(port_val):
            kept.append(item)  # global constraint — always relevant
            continue
        resolved = {norm_text(p) for p in resolve_port_filter(port_val)}
        if resolved & active_norm:
            kept.append(item)
    return kept


def show_constraints_summary(constraint_summary, explanation_logs=None):
    """Display summary of applied constraints with downloadable explanations"""
    if not constraint_summary:
        return

    # Respect the active sidebar Port filter: drop constraints scoped to other ports
    # so the summary matches the rest of the filtered view.
    constraint_summary = _filter_summary_by_active_ports(constraint_summary)
    if not constraint_summary:
        return

    from ..core.config_styling import section_header

    section_header("📊 Applied Constraints Summary")
    
    def _format_scope(scope):
        if not scope:
            return ''
        return ', '.join(
            f"{k}={', '.join(map(str, v))}" if isinstance(v, list) else f"{k}={v}"
            for k, v in scope.items()
        )

    def _format_claimed_by_for_table(claimed_by):
        if not claimed_by:
            return ''
        return ', '.join(
            f"P{p}({n})" for p, n in sorted(claimed_by.items(), key=lambda kv: -kv[1])
        )

    summary_data = []
    for item in constraint_summary:
        summary_data.append({
            'Priority': item['priority'],
            'Scope': _format_scope(item.get('scope')),
            'Method': item.get('method', 'N/A'),
            'Status': item['status'],
            'Eligible': item.get('eligible_containers', 'N/A'),
            'Allocated': item['containers_allocated'],
            'Target': item.get('target_containers', 'N/A'),
            'Claimed By': _format_claimed_by_for_table(item.get('claimed_by')),
            'Why': item.get('reason') or '',
        })

    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    total_allocated = sum(item['containers_allocated'] for item in constraint_summary)
    # Count constraints as successful if status starts with 'Applied' (includes 'Applied', 'Applied (Exclusion Rule)', etc.)
    successful = sum(1 for item in constraint_summary if item['status'].startswith('Applied'))
    partial = sum(1 for item in constraint_summary if item['status'].startswith('Partial'))
    failed_skipped = len(constraint_summary) - successful - partial

    col1.metric("🔒 Total Constrained Containers", f"{total_allocated:,}")
    col2.metric("✅ Successful Constraints", successful)
    col3.metric("⚠️ Partial (Shortfall)", partial)
    col4.metric("❌ Failed/Skipped", failed_skipped)

    if partial > 0:
        st.warning(
            f"{partial} minimum constraint(s) could not be fully satisfied — "
            "not enough eligible containers matched the constraint filters."
        )
    
    # Downloadable constraint explanations sheet
    if explanation_logs:
        st.markdown("---")
        explanation_df = pd.DataFrame(explanation_logs)
        csv = explanation_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Constraint Explanations",
            data=csv,
            file_name="constraint_explanations.csv",
            mime="text/csv",
            use_container_width=True,
            help="Download detailed log of all constraint processing actions, exclusions, and reallocations"
        )
