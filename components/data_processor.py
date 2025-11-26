"""
Data processing and merging module for the Carrier Tender Optimization Dashboard
"""
import pandas as pd
import logging
import streamlit as st
from .config_styling import section_header

@st.cache_data(show_spinner=False)
def validate_and_process_gvt_data(GVTdata):
    """Validate and process GVT data"""
    # Check if required columns exist and handle missing ones
    required_gvt_columns = ['Ocean ETA', 'Discharged Port', 'Dray SCAC(FL)', 'Facility']
    missing_columns = [col for col in required_gvt_columns if col not in GVTdata.columns]

    if missing_columns:
        raise ValueError(f"Missing required columns in GVT data: {missing_columns}. Available columns: {list(GVTdata.columns)}")

    # Calculate week number from Ocean ETA date - use inplace operations
    GVTdata['Ocean ETA'] = pd.to_datetime(GVTdata['Ocean ETA'], errors='coerce')
    
    # Check if WK num column already exists (from Excel WEEKNUM formula)
    # If it exists, use it directly to match Excel's calculation exactly
    if 'WK num' in GVTdata.columns:
        GVTdata['Week Number'] = GVTdata['WK num'].astype(float).round().astype('Int64')
    else:
        # Calculate week number to match Excel's WEEKNUM(date, 1) formula
        # Excel WEEKNUM with return_type=1: weeks start on SUNDAY, first week contains Jan 1
        # Python equivalent: strftime('%U') gives week number with Sunday as first day
        # Add 1 because strftime %U counts from 0, but WEEKNUM counts from 1
        GVTdata['Week Number'] = GVTdata['Ocean ETA'].apply(
            lambda x: int(x.strftime('%U')) + 1 if pd.notna(x) else None
        )

    # Remove rows where Ocean ETA is null (couldn't be converted to date)
    GVTdata = GVTdata.dropna(subset=['Ocean ETA'])

    # Optimize column operations - convert to string once and reuse
    port_str = GVTdata['Discharged Port'].astype(str)
    facility_str = GVTdata['Facility'].astype(str)
    scac_str = GVTdata['Dray SCAC(FL)'].astype(str)
    
    # Vectorized string operations
    GVTdata['Port_Processed'] = 'US' + port_str
    GVTdata['Facility_Processed'] = facility_str.str[:4]
    
    # Create lookup key and lane in one pass using pre-converted strings
    GVTdata['Lookup'] = scac_str + GVTdata['Port_Processed'] + GVTdata['Facility_Processed']
    GVTdata['Lane'] = GVTdata['Port_Processed'] + GVTdata['Facility_Processed']
    
    return GVTdata

@st.cache_data(show_spinner=False)
def validate_and_process_rate_data(Ratedata):
    """Validate and process Rate data"""
    # Check if Lookup already exists in Rate data
    if 'Lookup' not in Ratedata.columns:
        raise ValueError(f"Lookup column not found in Rate data. Available columns: {list(Ratedata.columns)}")

    # Create Lane column in Rate data (Port + FC concatenation)
    # First, identify Port and FC columns in Rate data
    port_col_rate = None
    fc_col_rate = None

    for col in Ratedata.columns:
        if 'PORT' in col.upper():
            port_col_rate = col
        if 'FC' in col.upper() or 'FACILITY' in col.upper():
            fc_col_rate = col

    if port_col_rate and fc_col_rate:
        Ratedata['Lane'] = Ratedata[port_col_rate].astype(str) + Ratedata[fc_col_rate].astype(str)
    else:
        raise ValueError(f"Cannot create Lane column. Port or FC column not found in rate data. Available columns: {list(Ratedata.columns)}")

    # Check if Base Rate column exists
    rate_col = None
    for col in Ratedata.columns:
        if 'RATE' in col.upper() or 'COST' in col.upper():
            # Skip CPC column for base rate detection
            if 'CPC' not in col.upper() and 'COST PER CONTAINER' not in col.upper():
                rate_col = col
                break

    if rate_col is None:
        raise ValueError(f"Rate column not found in rate data. Available columns: {list(Ratedata.columns)}")
    else:
        if rate_col != 'Base Rate':
            Ratedata = Ratedata.rename(columns={rate_col: 'Base Rate'})
    
    # Check if CPC (Cost Per Container) column exists
    cpc_col = None
    for col in Ratedata.columns:
        col_upper = col.upper()
        if 'CPC' in col_upper or 'COST PER CONTAINER' in col_upper:
            cpc_col = col
            break
    
    if cpc_col and cpc_col != 'CPC':
        Ratedata = Ratedata.rename(columns={cpc_col: 'CPC'})
    
    return Ratedata

def perform_lane_analysis(Ratedata):
    """Perform lane analysis and show results"""
    section_header("📊 Lane Analysis")
    
    lane_analysis = Ratedata.groupby('Lane').agg({
        'Base Rate': ['count', 'min', 'max', 'mean'],
        'Lookup': 'count'
    }).round(2)
    lane_analysis.columns = ['Rate_Count', 'Min_Rate', 'Max_Rate', 'Avg_Rate', 'Lookup_Count']
    lane_analysis = lane_analysis.reset_index()

    # Show lanes with multiple rates
    duplicate_lanes = lane_analysis[lane_analysis['Rate_Count'] > 1]
    if len(duplicate_lanes) > 0:
        print("Lanes with multiple rates:")
        try:
            print(duplicate_lanes.to_string())
        except Exception:
            print(duplicate_lanes)
    else:
        print("No duplicate lanes found")

@st.cache_data(show_spinner=False)
def merge_all_data(GVTdata, Ratedata, performance_clean, has_performance):
    """Merge all data sources together"""
    
    # Detect container column once at the start
    container_col = None
    for col in GVTdata.columns:
        col_lower = col.lower()
        if col_lower in ['container', 'container number', 'container numbers', 'container #', 'container_number', 'containers']:
            container_col = col
            break
    
    # Build grouping columns list once
    group_cols = ['Week Number', 'Discharged Port', 'Dray SCAC(FL)', 'Facility', 'Lane', 'Lookup']
    if 'Category' in GVTdata.columns:
        group_cols.insert(1, 'Category')
    if 'Terminal' in GVTdata.columns:
        group_cols.insert(len(group_cols) - 1, 'Terminal')  # Insert before 'Lookup'
    
    if container_col:
        # DEBUG: Count containers BEFORE any processing - FOCUS ON WEEK 47
        debug_all_containers_before = []
        debug_wk47_containers_before = []
        debug_container_counts_by_group = {}
        debug_wk47_groups = {}
        
        for _, row in GVTdata.iterrows():
            container_str = row.get(container_col, '')
            week_num = row.get('Week Number', None)
            
            if pd.notna(container_str) and str(container_str).strip():
                # Build group key
                group_key_parts = [str(row.get(col, '')) for col in group_cols]
                group_key = '|'.join(group_key_parts)
                
                # Parse containers
                containers_in_row = [c.strip() for c in str(container_str).split(',') if c.strip() and c.strip().lower() != 'nan']
                debug_all_containers_before.extend(containers_in_row)
                
                if group_key not in debug_container_counts_by_group:
                    debug_container_counts_by_group[group_key] = []
                debug_container_counts_by_group[group_key].extend(containers_in_row)
                
                # Track Week 47 specifically
                if week_num == 47:
                    debug_wk47_containers_before.extend(containers_in_row)
                    if group_key not in debug_wk47_groups:
                        debug_wk47_groups[group_key] = []
                    debug_wk47_groups[group_key].extend(containers_in_row)
        
        print(f"\n{'='*80}")
        print(f"🔍 DEBUG - WEEK 47 ANALYSIS - BEFORE GROUPING")
        print(f"{'='*80}")
        print(f"  📦 WEEK 47 Container entries in raw data: {len(debug_wk47_containers_before)}")
        print(f"  📦 WEEK 47 Unique containers: {len(set(debug_wk47_containers_before))}")
        print(f"  📦 WEEK 47 Number of groups: {len(debug_wk47_groups)}")
        print(f"\n  First 10 WK47 containers: {debug_wk47_containers_before[:10]}")
        print(f"  Last 10 WK47 containers: {debug_wk47_containers_before[-10:]}")
        
        print(f"\n  ALL DATA:")
        print(f"  Total container entries in raw data: {len(debug_all_containers_before)}")
        print(f"  Unique containers in raw data: {len(set(debug_all_containers_before))}")
        print(f"  Number of groups: {len(debug_container_counts_by_group)}")
        
        # Combine containers - keep all instances but remove duplicates WITHIN each group
        # This allows same container in different weeks, but not duplicated within same week/group
        def combine_containers_unique_per_group(x):
            """Join containers, removing duplicates only within this specific group"""
            containers = []
            for v in x.astype(str):
                v_str = str(v).strip()
                if v_str and v_str.lower() != 'nan':
                    containers.append(v_str)
            # Remove duplicates within this group only (same container can exist in other groups/weeks)
            unique_containers = []
            seen = set()
            for c in containers:
                if c not in seen:
                    unique_containers.append(c)
                    seen.add(c)
            return ', '.join(unique_containers)
        
        agg_dict = {container_col: combine_containers_unique_per_group}
        
        # Use dropna=False to include rows with blank Terminal or other NaN values in grouping columns
        lane_count = GVTdata.groupby(group_cols, dropna=False).agg(agg_dict).reset_index()
        lane_count = lane_count.rename(columns={container_col: 'Container Numbers'})
        
        # CRITICAL: Calculate Container Count from actual unique container IDs, not row count
        # This ensures the count matches the actual containers in the Container Numbers column
        def count_containers_from_string(container_str):
            """Count actual container IDs in comma-separated string"""
            if pd.isna(container_str) or not str(container_str).strip():
                return 0
            # Split by comma, strip whitespace, and filter out empty strings and 'nan'
            containers = [c.strip() for c in str(container_str).split(',') if c.strip() and c.strip().lower() != 'nan']
            return len(containers)
        
        lane_count['Container Count'] = lane_count['Container Numbers'].apply(count_containers_from_string)
        
        # DEBUG: Count containers AFTER grouping and aggregation - FOCUS ON WEEK 47
        debug_all_containers_after = []
        debug_wk47_containers_after = []
        debug_duplicates_removed_per_group = []
        debug_wk47_duplicates_removed = []
        
        for _, row in lane_count.iterrows():
            container_str = row.get('Container Numbers', '')
            week_num = row.get('Week Number', None)
            
            if pd.notna(container_str) and str(container_str).strip():
                containers_in_row = [c.strip() for c in str(container_str).split(',') if c.strip() and c.strip().lower() != 'nan']
                debug_all_containers_after.extend(containers_in_row)
                
                # Check how many were in this group before
                group_key_parts = [str(row.get(col, '')) for col in group_cols]
                group_key = '|'.join(group_key_parts)
                
                if group_key in debug_container_counts_by_group:
                    original_count = len(debug_container_counts_by_group[group_key])
                    after_count = len(containers_in_row)
                    if original_count != after_count:
                        duplicates_removed = original_count - after_count
                        dup_info = {
                            'group': group_key,
                            'original': original_count,
                            'after': after_count,
                            'removed': duplicates_removed
                        }
                        debug_duplicates_removed_per_group.append(dup_info)
                        if week_num == 47:
                            debug_wk47_duplicates_removed.append(dup_info)
                
                # Track Week 47 specifically
                if week_num == 47:
                    debug_wk47_containers_after.extend(containers_in_row)
        
        print(f"\n{'='*80}")
        print(f"🔍 DEBUG - WEEK 47 ANALYSIS - AFTER GROUPING")
        print(f"{'='*80}")
        print(f"  📦 WEEK 47 Containers after aggregation: {len(debug_wk47_containers_after)}")
        print(f"  📦 WEEK 47 Unique containers: {len(set(debug_wk47_containers_after))}")
        
        wk47_rows = lane_count[lane_count['Week Number'] == 47]
        print(f"  📦 WEEK 47 Container Count (sum): {wk47_rows['Container Count'].sum()}")
        print(f"  📦 WEEK 47 Number of rows after grouping: {len(wk47_rows)}")
        
        if debug_wk47_duplicates_removed:
            print(f"\n  ⚠️ WEEK 47 Duplicates removed within groups:")
            for dup_info in debug_wk47_duplicates_removed:
                print(f"    Group: {dup_info['group'][:100]}")
                print(f"      Before: {dup_info['original']}, After: {dup_info['after']}, Removed: {dup_info['removed']}")
        
        # Check for missing containers in Week 47
        wk47_before_set = set(debug_wk47_containers_before)
        wk47_after_set = set(debug_wk47_containers_after)
        missing_wk47_containers = wk47_before_set - wk47_after_set
        
        if missing_wk47_containers:
            print(f"\n  ❌ WEEK 47 MISSING CONTAINERS ({len(missing_wk47_containers)}):")
            for container in sorted(missing_wk47_containers):
                print(f"    - {container}")
                # Find which group this container was in
                for group_key, containers in debug_wk47_groups.items():
                    if container in containers:
                        print(f"      Was in group: {group_key[:100]}")
        else:
            print(f"\n  ✅ No Week 47 containers missing during aggregation")
        
        print(f"\n  ALL DATA:")
        print(f"  Total containers after aggregation: {len(debug_all_containers_after)}")
        print(f"  Unique containers after aggregation: {len(set(debug_all_containers_after))}")
        print(f"  Total Container Count (sum): {lane_count['Container Count'].sum()}")
        
        # Check for missing containers overall
        containers_before_set = set(debug_all_containers_before)
        containers_after_set = set(debug_all_containers_after)
        missing_containers = containers_before_set - containers_after_set
        
        if missing_containers:
            print(f"\n  ❌ ALL DATA MISSING CONTAINERS ({len(missing_containers)}):")
            for container in sorted(missing_containers):
                print(f"    - {container}")
        else:
            print(f"\n  ✅ No containers missing during aggregation")
        
        print(f"{'='*80}\n")
        
    else:
        # Fallback if no Container column
        # Use dropna=False to include rows with blank Terminal or other NaN values
        lane_count = GVTdata.groupby(group_cols, dropna=False).size().reset_index(name='Container Count')

    # Merge with rate data first
    merged_data = pd.merge(lane_count, Ratedata, how='left', on='Lookup', suffixes=('', '_rate'))

    # Handle potential Lane column conflicts
    if 'Lane' not in merged_data.columns:
        if 'Lane_rate' in merged_data.columns:
            merged_data['Lane'] = merged_data['Lane_rate']
        else:
            # Recreate Lane column from the original data
            merged_data['Lane'] = 'US' + merged_data['Discharged Port'].astype(str) + merged_data['Facility'].astype(str).str[:4]

    # Merge with performance data (only if available)
    if has_performance and len(performance_clean) > 0:
        # DEBUG: Print carrier names from both datasets to identify mismatches
        gvt_carriers = set(merged_data['Dray SCAC(FL)'].dropna().unique())
        perf_carriers = set(performance_clean['Carrier'].dropna().unique())
        
        print(f"\n=== PERFORMANCE DATA MERGE DEBUG ===")
        print(f"GVT carriers count: {len(gvt_carriers)}")
        print(f"Performance carriers count: {len(perf_carriers)}")
        print(f"GVT carriers sample: {sorted(list(gvt_carriers))[:10]}")
        print(f"Performance carriers sample: {sorted(list(perf_carriers))[:10]}")
        
        # Check for exact matches
        matching_carriers = gvt_carriers.intersection(perf_carriers)
        print(f"Matching carriers (exact): {len(matching_carriers)}")
        
        # Check for case-insensitive matches
        gvt_carriers_lower = {c.strip().upper() for c in gvt_carriers if isinstance(c, str)}
        perf_carriers_lower = {c.strip().upper() for c in perf_carriers if isinstance(c, str)}
        matching_case_insensitive = gvt_carriers_lower.intersection(perf_carriers_lower)
        print(f"Matching carriers (case-insensitive): {len(matching_case_insensitive)}")
        
        # Show non-matching carriers
        gvt_only = gvt_carriers - perf_carriers
        perf_only = perf_carriers - gvt_carriers
        if gvt_only:
            print(f"Carriers in GVT but NOT in Performance: {sorted(list(gvt_only))[:10]}")
        if perf_only:
            print(f"Carriers in Performance but NOT in GVT: {sorted(list(perf_only))[:10]}")
        
        # Normalize carrier names before merge to handle case/whitespace differences
        # Create normalized versions for matching
        merged_data['_carrier_normalized'] = merged_data['Dray SCAC(FL)'].astype(str).str.strip().str.upper()
        performance_clean = performance_clean.copy()  # Avoid modifying cached data
        performance_clean['_carrier_normalized'] = performance_clean['Carrier'].astype(str).str.strip().str.upper()
        
        # Ensure Week Number types match
        merged_data['Week Number'] = pd.to_numeric(merged_data['Week Number'], errors='coerce')
        performance_clean['Week Number'] = pd.to_numeric(performance_clean['Week Number'], errors='coerce')
        
        print(f"Week Number range in GVT: {merged_data['Week Number'].min()} - {merged_data['Week Number'].max()}")
        print(f"Week Number range in Performance: {performance_clean['Week Number'].min()} - {performance_clean['Week Number'].max()}")
        
        # Check for week number overlap
        gvt_weeks = set(merged_data['Week Number'].dropna().unique())
        perf_weeks = set(performance_clean['Week Number'].dropna().unique())
        overlapping_weeks = gvt_weeks.intersection(perf_weeks)
        print(f"GVT weeks: {sorted(gvt_weeks)}")
        print(f"Performance weeks: {sorted(perf_weeks)}")
        print(f"Overlapping weeks: {sorted(overlapping_weeks)}")
        
        if not overlapping_weeks:
            print("⚠️ WARNING: No overlapping weeks between GVT and Performance data!")
            print("   This means no performance scores can be matched to any containers.")
        
        # Perform the merge using normalized carrier names
        merged_data = pd.merge(
            merged_data, 
            performance_clean[['_carrier_normalized', 'Week Number', 'Performance_Score']], 
            left_on=['_carrier_normalized', 'Week Number'], 
            right_on=['_carrier_normalized', 'Week Number'], 
            how='left'
        )
        
        # Drop the helper column
        merged_data = merged_data.drop(columns=['_carrier_normalized'], errors='ignore')
        
        # Ensure Performance_Score is numeric after merge
        merged_data['Performance_Score'] = pd.to_numeric(merged_data['Performance_Score'], errors='coerce')
        
        # DEBUG: Check merge results
        non_null_scores = merged_data['Performance_Score'].notna().sum()
        total_rows = len(merged_data)
        print(f"After merge: {non_null_scores}/{total_rows} rows have performance scores ({non_null_scores/total_rows*100:.1f}%)")
        if non_null_scores > 0:
            print(f"Performance score range: {merged_data['Performance_Score'].min():.3f} - {merged_data['Performance_Score'].max():.3f}")
            print(f"Unique performance scores: {merged_data['Performance_Score'].dropna().nunique()}")
        print(f"=====================================\n")
        
    # NOW CALCULATE PROPER VOLUME-WEIGHTED PERFORMANCE SCORES
    merged_data = apply_volume_weighted_performance(merged_data)

    # Mark rows where Base Rate is null - vectorized operation
    merged_data['Missing_Rate'] = merged_data['Base Rate'].isna()
    
    # Fill missing rates with 0 - use fillna with inplace=False (default) but assign back
    merged_data['Base Rate'] = merged_data['Base Rate'].fillna(0)

    # Handle CPC columns efficiently
    has_cpc = 'CPC' in merged_data.columns
    if has_cpc:
        merged_data['CPC'] = merged_data['CPC'].fillna(0)
        merged_data['Total CPC'] = merged_data['CPC'] * merged_data['Container Count']
    else:
        # Add empty CPC columns if not present
        merged_data['CPC'] = 0
        merged_data['Total CPC'] = 0

    # Vectorized calculation
    merged_data['Total Rate'] = merged_data['Base Rate'] * merged_data['Container Count']

    return merged_data

def apply_volume_weighted_performance(merged_data):
    """Apply proper volume-weighted performance scores after merging with container counts
    
    For each carrier, calculates a volume-weighted average performance score across all weeks
    where the carrier has data, then fills in missing weeks with that weighted average.
    """
    from .performance_calculator import get_carrier_weighted_performance
    from .performance_assignments import track_performance_assignment, track_processing_step, clear_performance_tracking
    
    # Make a copy to avoid modifying cached data
    merged_data = merged_data.copy()
    
    # Clear previous tracking data
    clear_performance_tracking()
    
    # Only process if we have performance data
    if 'Performance_Score' not in merged_data.columns:
        print("⚠️ No Performance_Score column found in merged data - skipping performance calculations")
        return merged_data
    
    # Count missing before processing
    missing_before = merged_data['Performance_Score'].isna().sum()
    total_records = len(merged_data)
    
    # DEBUG: Show distribution of performance scores
    print(f"\n=== APPLY VOLUME WEIGHTED PERFORMANCE DEBUG ===")
    print(f"Total records: {total_records}")
    print(f"Missing Performance_Score: {missing_before} ({missing_before/total_records*100:.1f}%)")
    print(f"Non-missing Performance_Score: {total_records - missing_before}")
    
    # Check if ALL performance scores are missing - this indicates a merge problem
    if missing_before == total_records:
        print("❌ CRITICAL: ALL performance scores are NULL/NaN!")
        print("   This indicates the performance data merge completely failed.")
        print("   Likely causes:")
        print("   1. Carrier names don't match between GVT and Performance data")
        print("   2. Week numbers don't match between datasets")
        print("   3. Performance data was not loaded correctly")
        print("   Returning data without filling - check merge debug output above.")
        print(f"=============================================\n")
        return merged_data
    
    if total_records - missing_before > 0:
        non_null_scores = merged_data['Performance_Score'].dropna()
        print(f"Score range: {non_null_scores.min():.3f} - {non_null_scores.max():.3f}")
        print(f"Unique scores: {non_null_scores.nunique()}")
        
        # Show which carriers have data
        carriers_with_scores = merged_data[merged_data['Performance_Score'].notna()]['Dray SCAC(FL)'].unique()
        print(f"Carriers with performance data: {len(carriers_with_scores)}")
        print(f"Carriers with data: {sorted(list(carriers_with_scores))[:10]}...")
        
        print(f"Score distribution:\n{non_null_scores.value_counts().head(10)}")
    print(f"=============================================\n")
    
    # If no missing scores, nothing to do - keep existing performance data as-is
    # Do NOT reset scores just because they're all the same value
    if missing_before == 0:
        print("✓ All records have performance scores - no filling needed")
        return merged_data
    
    track_processing_step("Initial Assessment", f"Found {missing_before} missing performance scores")
    
    # Calculate volume-weighted performance averages for each carrier
    carrier_weighted_performance = get_carrier_weighted_performance(merged_data)
    track_processing_step("Carrier Analysis", f"Calculated performance for {len(carrier_weighted_performance)} carriers with existing data")
    
    # Get all unique carriers in the dataset
    all_carriers = merged_data['Dray SCAC(FL)'].unique()
    
    # For carriers not in performance dict (no performance data at all), assign global default
    carriers_with_some_data = set(carrier_weighted_performance.keys())
    carriers_with_no_data = [c for c in all_carriers if c not in carriers_with_some_data]
    
    if carriers_with_no_data:
        # Calculate global average from all available performance scores
        global_avg_performance = merged_data['Performance_Score'].dropna().mean() if not merged_data['Performance_Score'].dropna().empty else 0.75
        
        for carrier in carriers_with_no_data:
            carrier_weighted_performance[carrier] = global_avg_performance
        
        track_processing_step("Default Assignment", f"Assigned global average ({global_avg_performance:.3f}) to {len(carriers_with_no_data)} carriers with no performance data")
    
    # Fill missing performance scores with volume-weighted averages
    filled_count = 0
    carriers_filled = {}
    
    for carrier, weighted_avg in carrier_weighted_performance.items():
        # Find records for this carrier with missing performance scores
        missing_mask = (
            (merged_data['Dray SCAC(FL)'] == carrier) & 
            (merged_data['Performance_Score'].isna())
        )
        
        if missing_mask.any():
            records_affected = missing_mask.sum()
            
            # Fill the missing scores
            merged_data.loc[missing_mask, 'Performance_Score'] = weighted_avg
            filled_count += records_affected
            
            # Track for reporting
            carriers_filled[carrier] = {
                'count': records_affected,
                'score': weighted_avg,
                'type': 'Global Average' if carrier in carriers_with_no_data else 'Volume-Weighted'
            }
            
            # Track this assignment (for detailed logging)
            assignment_type = "Global Average (No Data)" if carrier in carriers_with_no_data else "Volume-Weighted Average"
            track_performance_assignment(carrier, assignment_type, weighted_avg, records_affected)

    
    # Verify all missing scores were filled
    missing_after = merged_data['Performance_Score'].isna().sum()
    
    track_processing_step("Final Result", f"Filled {filled_count} missing values, {missing_after} remaining")
    
    return merged_data

def perform_lane_analysis(Ratedata):
    """Perform lane analysis and show results"""
    section_header("📊 Lane Analysis")
    
    lane_analysis = Ratedata.groupby('Lane').agg({
        'Base Rate': ['count', 'min', 'max', 'mean'],
        'Lookup': 'count'
    }).round(2)
    lane_analysis.columns = ['Rate_Count', 'Min_Rate', 'Max_Rate', 'Avg_Rate', 'Lookup_Count']
    lane_analysis = lane_analysis.reset_index()

    # Show lanes with multiple rates
    duplicate_lanes = lane_analysis[lane_analysis['Rate_Count'] > 1]
    if len(duplicate_lanes) > 0:
        print("Lanes with multiple rates:")
        try:
            print(duplicate_lanes.to_string())
        except Exception:
            print(duplicate_lanes)
    else:
        print("No duplicate lanes found")

def create_comprehensive_data(merged_data):
    """Create comprehensive data table with additional calculated columns"""
    # Create comprehensive table with all data
    comprehensive_data = merged_data.copy()
    
    return comprehensive_data

def process_performance_data(Performancedata, has_performance):
    """Process performance data if available"""
    if not has_performance or Performancedata is None:
        return None, False
    
    try:
        # Your data structure: Carrier, Metrics, WK27, WK28, WK29, WK30, etc.
        performance_clean = Performancedata.copy()
        
        # Clean up column names by removing trailing spaces
        performance_clean.columns = performance_clean.columns.str.strip()
        
        # Filter for 'Total Score %' metrics only (your data shows this in Metrics column)
        if 'Metrics' in performance_clean.columns:
            performance_clean = performance_clean[performance_clean['Metrics'] == 'Total Score %'].copy()
        
        # Find week columns (WK27, WK28, WK29, WK30, etc.)
        week_columns = []
        for col in performance_clean.columns:
            if col.upper().startswith('WK') and len(col) > 2:
                try:
                    # Extract week number (WK27 -> 27)
                    week_num = int(col[2:])
                    week_columns.append(col)
                except ValueError:
                    continue
        
        if not week_columns:
            print("Warning: No week columns (WK27, WK28, etc.) found in performance data.")
            return None, False
        
        # Create week mapping (WK27 -> 27, WK28 -> 28, etc.)
        week_mapping = {}
        for col in week_columns:
            week_num = int(col[2:])
            week_mapping[col] = week_num
        
        # Melt the performance data to long format
        performance_melted = performance_clean.melt(
            id_vars=['Carrier'],
            value_vars=week_columns,
            var_name='Week_Column',
            value_name='Performance_Score'
        )
        
        # Map week column names to week numbers
        performance_melted['Week Number'] = performance_melted['Week_Column'].map(week_mapping)
        
        # Clean up performance scores (remove % and convert to decimal)
        performance_melted['Performance_Score'] = (
            performance_melted['Performance_Score']
            .astype(str)
            .str.replace('%', '')
            .str.replace('nan', '')  # Handle NaN values
            .replace('', None)       # Replace empty strings with None
        )
        
        # Convert to float, handling missing values
        performance_melted['Performance_Score'] = pd.to_numeric(
            performance_melted['Performance_Score'], errors='coerce'
        ) / 100
        
        # Ensure performance scores are between 0 and 1 (only for non-null values)
        performance_melted['Performance_Score'] = performance_melted['Performance_Score'].clip(0, 1)
        
        # Remove any rows with missing carriers
        performance_melted = performance_melted.dropna(subset=['Carrier'])
        
        # Remove the temporary Week_Column
        performance_clean = performance_melted.drop('Week_Column', axis=1)
        
        # NOW USE PERFORMANCE CALCULATOR TO FILL MISSING VALUES
        performance_filled = fill_missing_performance_scores(performance_clean)
        
        if len(performance_filled) > 0:
            missing_before = performance_clean['Performance_Score'].isna().sum()
            missing_after = performance_filled['Performance_Score'].isna().sum()
            filled_count = missing_before - missing_after
            
            print(f"Performance data processed: {len(performance_filled)} records from {len(week_columns)} weeks")
            if filled_count > 0:
                print(f"Filled {filled_count} missing performance scores using volume-weighted averages")
            
            return performance_filled, True
        else:
            print("No valid performance data after processing")
            return None, False
            
    except Exception as e:
        print(f"Warning: Error processing performance data: {str(e)}. Continuing without performance metrics.")
        return None, False

def fill_missing_performance_scores(performance_data):
    """Use performance calculator logic to fill missing performance scores"""
    from .performance_calculator import get_carrier_weighted_performance
    
    # Create a temporary container count column for weighting (assume equal weight if not available)
    if 'Container Count' not in performance_data.columns:
        performance_data['Container Count'] = 1  # Equal weighting
        temp_container_col = True
    else:
        temp_container_col = False
    
    # Calculate volume-weighted performance averages for each carrier
    carrier_weighted_performance = get_carrier_weighted_performance(performance_data)
    
    # Fill missing performance scores with volume-weighted averages
    performance_filled = performance_data.copy()
    
    for carrier, weighted_avg in carrier_weighted_performance.items():
        # Find records for this carrier with missing performance scores
        missing_mask = (
            (performance_filled['Carrier'] == carrier) & 
            (performance_filled['Performance_Score'].isna())
        )
        
        if missing_mask.any():
            performance_filled.loc[missing_mask, 'Performance_Score'] = weighted_avg
    
    # Remove temporary container count column if we added it
    if temp_container_col:
        performance_filled = performance_filled.drop('Container Count', axis=1)
    
    return performance_filled
