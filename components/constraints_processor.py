"""
Constraints Processing Module
Handles operational constraints uploaded via Excel file
Version: 2025-11-25 - Moved constraint processing messages to downloadable CSV sheet
"""
import pandas as pd
import streamlit as st
import math
from .utils import (
    normalize_facility_code, parse_container_ids, join_container_ids
)


def allocate_specific_containers(row, num_containers, allocated_tracker, target_carrier, week_num):
    """
    Allocate specific container IDs from a row, tracking which containers are allocated
    
    Args:
        row: Data row containing Container Numbers
        num_containers: Number of containers to allocate
        allocated_tracker: Dict tracking allocated container IDs
        target_carrier: Carrier to assign containers to
        week_num: Week number for tracking
    
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
            'row_idx': row.name if hasattr(row, 'name') else None
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
        expected_cols = [
            'Category', 'Carrier', 'Lane', 'Port', 'Week Number', 'Terminal', 'SSL', 'Vessel',
            'Maximum Container Count', 'Minimum Container Count',
            'Percent Allocation', 'Excluded FC', 'Priority Score'
        ]
        
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
    constraint_summary = []
    
    # Collect explanation logs for downloadable report (not displayed in UI)
    explanation_logs = []
    
    def log_explanation(message, level='info'):
        """Add a message to the explanation log for downloadable report"""
        explanation_logs.append({'Level': level.upper(), 'Message': message})
    
    # Track which INDIVIDUAL container IDs have been allocated
    # Key: container_id, Value: dict with {carrier, week, row_idx}
    allocated_containers_tracker = {}
    
    # Track carriers with MAXIMUM constraints (hard caps)
    # Each entry is a dict with the carrier name and the constraint's scope filters.
    # None values mean "no filter on this dimension" (applies globally for that dimension).
    # Example: {'carrier': 'HDDR', 'category': 'Import', 'lane': 'USNYCREWR', 'port': None, 'week': None}
    max_constrained_carriers = []
    
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
                lambda s: set(v for v in s.unique() if v and v != '')
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

    for idx, constraint in constraints_df.iterrows():
        # Build filter mask based on provided constraint fields
        # NOTE: Carrier is NOT a filter - it's the TARGET carrier to assign containers to
        mask = pd.Series([True] * len(remaining_data), index=remaining_data.index)
        
        # Helper function to check if value is valid (not None, not NaN, not empty string)
        def is_valid_value(val):
            if pd.isna(val):
                return False
            if isinstance(val, str) and val.strip() == '':
                return False
            return True
        
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
                'containers_allocated': 0
            })
            continue
        
        # Apply Category filter if specified
        if is_valid_value(constraint['Category']):
            if 'Category' in remaining_data.columns:
                mask &= remaining_data['Category'] == constraint['Category']
                filters_applied.append(f"Category={constraint['Category']}")
        
        # DO NOT filter by Carrier - Carrier is the TARGET assignment, not a filter!
        # The constraint means "assign X% to this carrier", not "find X% already with this carrier"
        
        # Apply Lane filter if specified
        if is_valid_value(constraint['Lane']):
            mask &= remaining_data['Lane'] == constraint['Lane']
            filters_applied.append(f"Lane={constraint['Lane']}")
        
        # Apply Port filter if specified
        if is_valid_value(constraint['Port']):
            if 'Discharged Port' in remaining_data.columns:
                mask &= remaining_data['Discharged Port'] == constraint['Port']
                filters_applied.append(f"Port={constraint['Port']}")
        
        # Apply Week Number filter if specified
        if is_valid_value(constraint['Week Number']):
            mask &= remaining_data['Week Number'] == constraint['Week Number']
            filters_applied.append(f"Week={int(constraint['Week Number'])}")
        
        # Apply Terminal filter if specified
        if is_valid_value(constraint.get('Terminal')):
            if 'Terminal' in remaining_data.columns:
                mask &= remaining_data['Terminal'] == constraint['Terminal']
                filters_applied.append(f"Terminal={constraint['Terminal']}")
        
        # Apply SSL filter if specified
        if is_valid_value(constraint.get('SSL')):
            if 'SSL' in remaining_data.columns:
                mask &= remaining_data['SSL'] == constraint['SSL']
                filters_applied.append(f"SSL={constraint['SSL']}")
        
        # Apply Vessel filter if specified
        if is_valid_value(constraint.get('Vessel')):
            if 'Vessel' in remaining_data.columns:
                mask &= remaining_data['Vessel'] == constraint['Vessel']
                filters_applied.append(f"Vessel={constraint['Vessel']}")
        
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
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'No matching data',
                    'containers_allocated': 0
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

        if has_max or has_min or has_pct:
            # Validation: Max constraints require a carrier
            if has_max and not target_carrier:
                log_explanation(f"ERROR: Maximum Container Count constraint requires a Carrier to be specified!", 'error')
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'Error: No carrier specified for maximum constraint',
                    'containers_allocated': 0
                })
                continue

            # Step 1: Compute base target from percent (or default to all eligible)
            if has_pct:
                percent_value = constraint['Percent Allocation'] / 100
                calculated_containers = total_eligible_containers * percent_value
                if calculated_containers > 0 and calculated_containers < 1:
                    target_containers = 1
                else:
                    target_containers = math.ceil(calculated_containers)
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

            # Step 4: Can't exceed what's available
            target_containers = min(target_containers, total_eligible_containers)

            # Handle case where max constraint has 0 eligible but still needs exclusion
            if has_max and total_eligible_containers == 0:
                target_containers = 0

            # Build allocation method description
            method_parts = []
            if has_pct:
                method_parts.append(f"{constraint['Percent Allocation']}% = {math.ceil(total_eligible_containers * constraint['Percent Allocation'] / 100)}")
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
                    'method': f"Exclusion: {target_carrier} blocked from {excluded_facility}"
                })
                continue
            else:
                # Truly no allocation amount and no exclusion - skip
                log_explanation(f"No allocation amount specified for constraint: {constraint_desc}", 'warning')
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'No allocation amount',
                    'containers_allocated': 0
                })
                continue
        
        # Allocate containers at the CONTAINER ID level (not just counts)
        allocated_containers_count = 0
        
        # Only process allocation if we have containers to allocate
        if target_containers > 0 and len(eligible_data) > 0:
            # Sort by week for consistency
            allocation_data = eligible_data.sort_values('Week Number')
            
            for row_idx, row in allocation_data.iterrows():
                if allocated_containers_count >= target_containers:
                    # We've allocated enough - stop processing
                    break
                
                # How many MORE containers do we need?
                containers_needed = target_containers - allocated_containers_count
                
                # Allocate specific container IDs from this row
                week_num = row.get('Week Number', None)
                allocated_ids, remaining_ids = allocate_specific_containers(
                    row, containers_needed, allocated_containers_tracker, target_carrier, week_num
                )
                
                if len(allocated_ids) > 0:
                    # Create constrained record with ONLY the allocated container IDs
                    constrained_record = row.copy()
                    constrained_record['Container Numbers'] = join_container_ids(allocated_ids)
                    constrained_record['Container Count'] = len(allocated_ids)
                    
                    # ASSIGN to target carrier (override existing carrier)
                    if target_carrier:
                        # Check which carrier columns exist
                        has_carrier = 'Carrier' in constrained_record.index
                        has_dray_scac = 'Dray SCAC(FL)' in constrained_record.index
                        
                        # Set BOTH carrier columns if they exist
                        if has_dray_scac:
                            constrained_record['Dray SCAC(FL)'] = target_carrier
                        if has_carrier:
                            constrained_record['Carrier'] = target_carrier
                    
                    constrained_record['Constraint_Priority'] = constraint['Priority Score']
                    constrained_record['Constraint_Method'] = allocation_method
                    constrained_record['Constraint_Description'] = constraint_desc
                    
                    constrained_records.append(constrained_record)
                    allocated_containers_count += len(allocated_ids)
                    
                    # Update remaining_data: Remove allocated containers from this row
                    if len(remaining_ids) > 0:
                        # Partial allocation - update with remaining containers
                        remaining_data.loc[row_idx, 'Container Numbers'] = join_container_ids(remaining_ids)
                        remaining_data.loc[row_idx, 'Container Count'] = len(remaining_ids)
                    else:
                        # Full allocation - mark row for removal (set container count to 0)
                        remaining_data.loc[row_idx, 'Container Count'] = 0
                        remaining_data.loc[row_idx, 'Container Numbers'] = ''
        
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
                    'target_containers': target_containers,
                    'method': allocation_method
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
        
        # Determine status: flag minimum shortfalls
        constraint_status = 'Applied'
        if (pd.notna(constraint.get('Minimum Container Count')) and
            constraint['Minimum Container Count'] > 0 and
            allocated_containers_count < int(constraint['Minimum Container Count'])):
            constraint_status = f"Partial (shortfall: {int(constraint['Minimum Container Count']) - allocated_containers_count})"

        constraint_summary.append({
            'priority': constraint['Priority Score'],
            'description': constraint_desc,
            'status': constraint_status,
            'containers_allocated': allocated_containers_count,
            'target_containers': target_containers,
            'method': allocation_method
        })
    
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


def show_constraints_summary(constraint_summary, explanation_logs=None):
    """Display summary of applied constraints with downloadable explanations"""
    if not constraint_summary:
        return
    
    from .config_styling import section_header
    
    section_header("📊 Applied Constraints Summary")
    
    summary_data = []
    for item in constraint_summary:
        summary_data.append({
            'Priority': item['priority'],
            'Description': item['description'],
            'Method': item.get('method', 'N/A'),
            'Status': item['status'],
            'Containers Allocated': item['containers_allocated'],
            'Target': item.get('target_containers', 'N/A')
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
