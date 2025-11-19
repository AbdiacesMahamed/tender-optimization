"""
Constraints Processing Module
Handles operational constraints uploaded via Excel file
"""
import pandas as pd
import streamlit as st
import math


# ==================== HELPER FUNCTIONS FOR CONTAINER-LEVEL TRACKING ====================

def normalize_facility_code(facility_str):
    """
    Normalize facility code to first 4 characters for comparison
    Examples: 'HGR6-5' -> 'HGR6', 'IUSF' -> 'IUSF', 'GBPT-3' -> 'GBPT'
    """
    if pd.isna(facility_str) or not str(facility_str).strip():
        return ''
    # Convert to string and strip whitespace
    fc = str(facility_str).strip().upper()
    # Take first 4 characters
    return fc[:4] if len(fc) >= 4 else fc


def split_container_numbers(container_str):
    """Split container numbers string into list of container IDs"""
    if pd.isna(container_str) or not str(container_str).strip():
        return []
    return [c.strip() for c in str(container_str).split(',') if c.strip()]


def join_container_numbers(container_list):
    """Join list of container IDs into comma-separated string"""
    return ', '.join(str(c) for c in container_list if c)


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
    container_ids = split_container_numbers(row.get('Container Numbers', ''))
    
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
        
        # Apply column mapping
        constraints_df = constraints_df.rename(columns=column_mapping)
        
        # Define expected columns
        expected_cols = [
            'Category', 'Carrier', 'Lane', 'Port', 'Week Number', 'Terminal',
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
        for col in ['Category', 'Lane', 'Carrier', 'Port', 'Terminal', 'Excluded FC']:
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


def apply_constraints_to_data(data, constraints_df):
    """
    Apply constraints to data based on priority score
    
    Args:
        data: DataFrame with comprehensive data
        constraints_df: DataFrame with constraints sorted by priority
    
    Returns:
        constrained_data: DataFrame with containers locked by constraints
        unconstrained_data: DataFrame with remaining containers for scenarios
        constraint_summary: List of applied constraints with details
        max_constrained_carriers: Set of carriers that have Maximum Container Count constraints
                                   (these carriers should NOT receive additional volume in optimization)
    
    Maximum Constraint Logic:
        When a carrier has a Maximum Container Count constraint:
        1. Allocate specified amount to constrained table (assigned to target carrier)
        2. Add carrier to max_constrained_carriers exclusion set
        3. Containers remain in unconstrained table (not deleted)
        4. Optimization will exclude this carrier, making containers available to other carriers
        
        IMPORTANT: Maximum constraints only REQUIRE a Carrier field.
        - Carrier (REQUIRED): The carrier to cap
        - Filters (OPTIONAL): Category, Lane, Port, Week Number
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
        return pd.DataFrame(), data.copy(), [], set()
    
    constrained_records = []
    remaining_data = data.copy().reset_index(drop=True)
    constraint_summary = []
    
    # Track which INDIVIDUAL container IDs have been allocated
    # Key: container_id, Value: dict with {carrier, week, row_idx}
    allocated_containers_tracker = {}
    
    # Track carriers with MAXIMUM constraints (hard caps)
    # These carriers should NOT receive additional volume in optimization scenarios
    max_constrained_carriers = set()
    
    st.write(f"🔍 Applying {len(constraints_df)} constraints...")
    
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
            st.error(f"❌ Excluded FC requires a Carrier to be specified!")
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
        
        # CRITICAL: If Excluded FC is specified, we need to filter OUT rows at that facility
        # This prevents the carrier from being allocated containers at that facility
        # Normalize facility codes to first 4 characters for comparison (e.g., HGR6-5 -> HGR6)
        
        # IMPORTANT: Collect ALL excluded facilities for this carrier from ALL constraints
        # This ensures exclusions apply across all constraints for the same carrier
        all_excluded_facilities = []
        if excluded_facility:
            all_excluded_facilities.append(excluded_facility)
        
        # Look for other constraints for the same carrier with Excluded FC
        if target_carrier and 'Excluded FC' in constraints_df.columns:
            other_exclusions = constraints_df[
                (constraints_df['Carrier'] == target_carrier) &
                (constraints_df['Excluded FC'].notna()) &
                (constraints_df['Excluded FC'] != '')
            ]['Excluded FC'].unique()
            for exc_fc in other_exclusions:
                exc_fc_str = str(exc_fc).strip()
                if exc_fc_str and exc_fc_str not in all_excluded_facilities:
                    all_excluded_facilities.append(exc_fc_str)
                    if exc_fc_str != excluded_facility:
                        st.write(f"   🔗 Also applying exclusion from another constraint: Excluding Facility={exc_fc_str}")
        
        # Apply all excluded facilities to the mask
        excluded_facility_mask = None
        if all_excluded_facilities and 'Facility' in remaining_data.columns:
            for exc_fc in all_excluded_facilities:
                # Normalize the excluded facility to first 4 characters
                normalized_excluded_fc = normalize_facility_code(exc_fc)
                
                # Find rows at the excluded facility (comparing normalized codes)
                current_exclusion_mask = remaining_data['Facility'].apply(normalize_facility_code) == normalized_excluded_fc
                
                # Remove those rows from eligible data
                mask &= ~current_exclusion_mask
                filters_applied.append(f"Excluding Facility={exc_fc}")
                
                # Count how many rows are being excluded
                excluded_count = current_exclusion_mask.sum()
                if excluded_count > 0:
                    st.write(f"   🚫 Excluding {excluded_count} rows at facility {exc_fc} (normalized: {normalized_excluded_fc}) for {target_carrier if target_carrier else 'carrier'}")
                else:
                    st.write(f"   ℹ️ No rows found at facility {exc_fc} (normalized: {normalized_excluded_fc})")
                
                # Combine with overall exclusion mask
                if excluded_facility_mask is None:
                    excluded_facility_mask = current_exclusion_mask
                else:
                    excluded_facility_mask |= current_exclusion_mask

        
        # Add target carrier to description
        filter_desc = ", ".join(filters_applied) if filters_applied else "All data"
        if target_carrier:
            constraint_desc += f"{filter_desc} → Assign to {target_carrier}"
        else:
            constraint_desc += filter_desc
        
        # Get eligible data that matches the filter mask
        eligible_data = remaining_data[mask].copy()
        
        # For each row, calculate how many containers are available (not already allocated)
        available_container_counts = []
        for idx_val, row in eligible_data.iterrows():
            container_ids = split_container_numbers(row.get('Container Numbers', ''))
            available_ids = [cid for cid in container_ids if cid not in allocated_containers_tracker]
            available_container_counts.append(len(available_ids))
        
        eligible_data['_available_containers'] = available_container_counts
        eligible_data = eligible_data[eligible_data['_available_containers'] > 0].copy()
        
        # Check if this is a maximum constraint - if so, validate we have a carrier
        is_potential_max_constraint = (
            pd.notna(constraint.get('Maximum Container Count')) and 
            constraint['Maximum Container Count'] > 0
        )
        
        if len(eligible_data) == 0:
            # For maximum constraints with carrier only, this might be OK if we're removing all carrier data
            if is_potential_max_constraint and target_carrier:
                st.info(f"ℹ️ No containers matching filters for constraint: {constraint_desc}")
                st.info(f"   Will proceed to remove ANY existing {target_carrier} containers from unconstrained table")
                # Continue to process the constraint to remove carrier from unconstrained table
                total_eligible_containers = 0
            else:
                st.warning(f"⚠️ No eligible data for constraint: {constraint_desc}")
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
        
        # Priority: Max Count > Min Count > Percent Allocation
        if pd.notna(constraint['Maximum Container Count']) and constraint['Maximum Container Count'] > 0:
            # VALIDATION: Maximum constraints MUST have a carrier specified
            if not target_carrier:
                st.error(f"❌ Maximum Container Count constraint requires a Carrier to be specified!")
                constraint_summary.append({
                    'priority': constraint['Priority Score'],
                    'description': constraint_desc,
                    'status': 'Error: No carrier specified for maximum constraint',
                    'containers_allocated': 0
                })
                continue
            
            # For MAXIMUM constraints: Allocate specified amount to constrained table
            # AND remove ALL other containers matching this filter for this carrier from unconstrained table
            # For carrier-only constraints (no filters), this removes the carrier entirely
            if total_eligible_containers > 0:
                target_containers = min(int(constraint['Maximum Container Count']), total_eligible_containers)
            else:
                # No eligible containers to allocate, but we'll still remove carrier from unconstrained
                target_containers = 0
            
            allocation_method = f"Max {int(constraint['Maximum Container Count'])} containers"
            is_maximum_constraint = True  # This is a hard cap - carrier should not get more
            
            # Track this carrier as having a maximum constraint (hard cap)
            max_constrained_carriers.add(target_carrier)
            
            # CRITICAL: For maximum constraints, we need to remove ALL containers for this carrier
            # that match the filter criteria from the unconstrained pool
            # This ensures the carrier doesn't appear in unconstrained table for this segment
        
        elif pd.notna(constraint['Minimum Container Count']) and constraint['Minimum Container Count'] > 0:
            target_containers = min(int(constraint['Minimum Container Count']), total_eligible_containers)
            allocation_method = f"Min {int(constraint['Minimum Container Count'])} containers"
        
        elif pd.notna(constraint['Percent Allocation']) and constraint['Percent Allocation'] > 0:
            # Use ceiling to ensure at least 1 container if percentage > 0
            percent_value = constraint['Percent Allocation'] / 100
            calculated_containers = total_eligible_containers * percent_value
            
            # Round up to ensure we get at least 1 container when percentage is specified
            if calculated_containers > 0 and calculated_containers < 1:
                target_containers = 1
            else:
                target_containers = math.ceil(calculated_containers)
            
            # But don't exceed total eligible
            target_containers = min(target_containers, total_eligible_containers)
            
            allocation_method = f"{constraint['Percent Allocation']}% allocation ({target_containers:,} containers)"
        
        else:
            # No allocation amount specified - skip this constraint
            st.warning(f"⚠️ No allocation amount specified for constraint: {constraint_desc}")
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
                    constrained_record['Container Numbers'] = join_container_numbers(allocated_ids)
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
                        remaining_data.loc[row_idx, 'Container Numbers'] = join_container_numbers(remaining_ids)
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
            st.write(f"   🔒 {target_carrier} added to exclusion list for optimization")
            st.write(f"   ⚠️ {target_carrier} will NOT be able to receive ANY containers in optimization")
            st.write(f"   ℹ️ Containers remain in unconstrained table for other carriers to use")
        
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
                            st.error(f"   ❌ Violation found: {record.get('Facility')} matches excluded {excluded_facility}")
                            break
            
            if facility_violation_in_constrained:
                st.error(f"❌ CONSTRAINT FAILED: Cannot allocate {target_carrier} containers to excluded facility {excluded_facility}")
                st.error(f"   No alternative carrier available for containers at {excluded_facility}")
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
                for col in carrier_cols:
                    # Use normalized facility code comparison
                    excluded_mask |= (
                        (remaining_data[col] == target_carrier) & 
                        (remaining_data['Facility'].apply(normalize_facility_code) == normalized_excluded_fc)
                    )
                
                if excluded_mask.any():
                    excluded_containers = remaining_data.loc[excluded_mask, 'Container Count'].sum()
                    st.warning(f"   ⚠️ Found {excluded_containers} containers for {target_carrier} at excluded facility {excluded_facility} (normalized: {normalized_excluded_fc})")
                    st.warning(f"   These containers must be reallocated to other carriers or constraint will fail")
                    # Mark carrier for exclusion at this facility (handled by optimization)
        
        constraint_summary.append({
            'priority': constraint['Priority Score'],
            'description': constraint_desc,
            'status': 'Applied',
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
    
    # Summary
    total_constrained = constrained_data['Container Count'].sum() if len(constrained_data) > 0 else 0
    total_unconstrained = remaining_data['Container Count'].sum()
    total_original = data['Container Count'].sum()
    
    st.write("📊 **Constraint Application Summary:**")
    st.write(f"- Original containers: {total_original:,}")
    st.write(f"- Constrained containers: {total_constrained:,}")
    st.write(f"- Unconstrained containers: {total_unconstrained:,}")
    st.write(f"- Total after split: {total_constrained + total_unconstrained:,}")
    
    if abs(total_original - (total_constrained + total_unconstrained)) > 0.01:
        st.error(f"⚠️ Container mismatch! Lost {total_original - (total_constrained + total_unconstrained):,.0f} containers")
    
    # Show carriers with maximum constraints (hard caps)
    if max_constrained_carriers:
        st.info(f"🔒 **Carriers with Maximum Constraints (Hard Caps):** {', '.join(sorted(max_constrained_carriers))}\n\n"
                f"These carriers will NOT receive additional volume in optimization scenarios.")
    
    return constrained_data, remaining_data, constraint_summary, max_constrained_carriers


def show_constraints_summary(constraint_summary):
    """Display summary of applied constraints"""
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
    col1, col2, col3 = st.columns(3)
    total_allocated = sum(item['containers_allocated'] for item in constraint_summary)
    successful = sum(1 for item in constraint_summary if item['status'] == 'Applied')
    
    col1.metric("🔒 Total Constrained Containers", f"{total_allocated:,}")
    col2.metric("✅ Successful Constraints", successful)
    col3.metric("⚠️ Failed/Skipped Constraints", len(constraint_summary) - successful)
