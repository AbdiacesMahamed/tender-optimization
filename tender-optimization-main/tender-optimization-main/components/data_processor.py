"""
Data processing and merging module for the Carrier Tender Optimization Dashboard
"""
import pandas as pd
import logging
from .config_styling import section_header

def validate_and_process_gvt_data(GVTdata):
    """Validate and process GVT data"""
    # Check if required columns exist and handle missing ones
    required_gvt_columns = ['SSL ATA', 'Discharged Port', 'Dray SCAC(FL)', 'Facility']
    missing_columns = [col for col in required_gvt_columns if col not in GVTdata.columns]

    if missing_columns:
        raise ValueError(f"Missing required columns in GVT data: {missing_columns}. Available columns: {list(GVTdata.columns)}")

    # Calculate week number from SSL ATA date
    GVTdata['SSL ATA'] = pd.to_datetime(GVTdata['SSL ATA'], errors='coerce')
    GVTdata['Week Number'] = GVTdata['SSL ATA'].dt.isocalendar().week

    # Remove rows where SSL ATA is null (couldn't be converted to date)
    GVTdata = GVTdata.dropna(subset=['SSL ATA'])

    # Process columns for lookup creation
    # Add "US" prefix to Discharged Port
    GVTdata['Port_Processed'] = 'US' + GVTdata['Discharged Port'].astype(str)

    # Take first 4 characters of Facility
    GVTdata['Facility_Processed'] = GVTdata['Facility'].astype(str).str[:4]

    # Create lookup key in GVT data (SCAC + Port + FC)
    GVTdata['Lookup'] = (GVTdata['Dray SCAC(FL)'].astype(str) + 
                         GVTdata['Port_Processed'].astype(str) + 
                         GVTdata['Facility_Processed'].astype(str))
    
    # Create corresponding Lane column in GVT data
    GVTdata['Lane'] = GVTdata['Port_Processed'].astype(str) + GVTdata['Facility_Processed'].astype(str)
    
    return GVTdata

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
            rate_col = col
            break

    if rate_col is None:
        raise ValueError(f"Rate column not found in rate data. Available columns: {list(Ratedata.columns)}")
    else:
        if rate_col != 'Base Rate':
            Ratedata = Ratedata.rename(columns={rate_col: 'Base Rate'})
    
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

    # Get cheapest rate per lane
    cheapest_rates_by_lane = Ratedata.groupby('Lane')['Base Rate'].min().reset_index()
    cheapest_rates_by_lane = cheapest_rates_by_lane.rename(columns={'Base Rate': 'Cheapest Base Rate'})
    
    return cheapest_rates_by_lane

def merge_all_data(GVTdata, Ratedata, cheapest_rates_by_lane, performance_clean, has_performance):
    """Merge all data sources together"""
    # Update lane_count to include Lane column - MOVED BEFORE THE MERGE
    lane_count = GVTdata.groupby(['Week Number', 'Discharged Port', 'Dray SCAC(FL)', 'Facility', 'Lane', 'Lookup']).size().reset_index(name='Container Count')

    # Merge with rate data first
    merged_data = pd.merge(lane_count, Ratedata, how='left', on='Lookup', suffixes=('', '_rate'))

    # Handle potential Lane column conflicts
    if 'Lane' not in merged_data.columns:
        if 'Lane_rate' in merged_data.columns:
            # Use the Lane from rate data if it exists
            merged_data['Lane'] = merged_data['Lane_rate']
        else:
            # Recreate Lane column from the original data
            merged_data['Lane'] = merged_data['Discharged Port'].apply(lambda x: 'US' + str(x)) + merged_data['Facility'].astype(str).str[:4]

    # Now merge with cheapest rates by lane - Lane column should exist now
    merged_data = pd.merge(merged_data, cheapest_rates_by_lane, how='left', on='Lane')

    # Merge with performance data (only if available)
    if has_performance and len(performance_clean) > 0:
        merged_data = pd.merge(
            merged_data, 
            performance_clean, 
            left_on=['Dray SCAC(FL)', 'Week Number'], 
            right_on=['Carrier', 'Week Number'], 
            how='left'
        )
        
    # NOW CALCULATE PROPER VOLUME-WEIGHTED PERFORMANCE SCORES
    merged_data = apply_volume_weighted_performance(merged_data)

    # Remove rows where Base Rate is null (no matching rate found)
    merged_data = merged_data.dropna(subset=['Base Rate'])

    merged_data['Total Rate'] = merged_data['Base Rate'] * merged_data['Container Count']

    # Calculate potential savings (now based on cheapest lane rate)
    merged_data['Cheapest Total Rate'] = merged_data['Cheapest Base Rate'] * merged_data['Container Count']
    merged_data['Potential Savings'] = merged_data['Total Rate'] - merged_data['Cheapest Total Rate']

    return merged_data

def apply_volume_weighted_performance(merged_data):
    """Apply proper volume-weighted performance scores after merging with container counts"""
    from .performance_calculator import get_carrier_weighted_performance
    from .performance_assignments import track_performance_assignment, track_processing_step, clear_performance_tracking
    
    # Check if already processed to avoid duplicate processing
    if hasattr(merged_data, '_performance_processed') and merged_data._performance_processed:
        return merged_data
    
    # Clear previous tracking data
    clear_performance_tracking()
    
    # Only process if we have performance data
    if 'Performance_Score' not in merged_data.columns:
        print("Warning: No Performance_Score column found - skipping performance calculation")
        return merged_data
    
    # Count missing before processing
    missing_before = merged_data['Performance_Score'].isna().sum()
    
    # If no missing scores, mark as processed and return
    if missing_before == 0:
        merged_data._performance_processed = True
        print("All performance scores already complete - no processing needed")
        return merged_data
    
    track_processing_step("Initial Assessment", f"Found {missing_before} missing performance scores")
    
    # Calculate volume-weighted performance averages for each carrier
    carrier_weighted_performance = get_carrier_weighted_performance(merged_data)
    track_processing_step("Carrier Analysis", f"Calculated performance for {len(carrier_weighted_performance)} carriers with existing data")
    
    # Get all unique carriers in the dataset
    all_carriers = merged_data['Dray SCAC(FL)'].unique()
    
    # For carriers not in performance dict (no performance data at all), assign default score
    global_avg_performance = merged_data['Performance_Score'].dropna().mean() if not merged_data['Performance_Score'].dropna().empty else 3.0
    
    carriers_with_no_data = []
    for carrier in all_carriers:
        if carrier not in carrier_weighted_performance:
            carrier_weighted_performance[carrier] = global_avg_performance
            carriers_with_no_data.append(carrier)
    
    if carriers_with_no_data:
        track_processing_step("Default Assignment", f"Assigned global average ({global_avg_performance:.3f}) to {len(carriers_with_no_data)} carriers with no performance data")
    
    # Fill missing performance scores with volume-weighted averages
    filled_count = 0
    for carrier, weighted_avg in carrier_weighted_performance.items():
        # Find records for this carrier with missing performance scores
        missing_mask = (
            (merged_data['Dray SCAC(FL)'] == carrier) & 
            (merged_data['Performance_Score'].isna())
        )
        
        if missing_mask.any():
            records_affected = missing_mask.sum()
            merged_data.loc[missing_mask, 'Performance_Score'] = weighted_avg
            filled_count += records_affected
            
            # Determine assignment type
            if carrier in carriers_with_no_data:
                assignment_type = "Global Average (No Data)"
            else:
                assignment_type = "Volume-Weighted Average"
            
            # Track this assignment
            track_performance_assignment(carrier, assignment_type, weighted_avg, records_affected)
    
    # Verify all missing scores were filled
    missing_after = merged_data['Performance_Score'].isna().sum()
    
    # Display summary
    if missing_after > 0:
        print(f"Error: Still have {missing_after} missing performance scores after processing!")
    else:
        print(f"Performance scores completed: {filled_count} values filled across {len(carrier_weighted_performance)} carriers")
    
    track_processing_step("Final Result", f"Filled {filled_count} missing values, {missing_after} remaining")
    
    # Mark as processed to prevent duplicate runs
    merged_data._performance_processed = True
    
    return merged_data

def create_comprehensive_data(merged_data):
    """Create comprehensive data table with additional calculated columns"""
    # Create comprehensive table with all data
    comprehensive_data = merged_data.copy()

    # Add additional calculated columns
    comprehensive_data['Rate Difference'] = comprehensive_data['Base Rate'] - comprehensive_data['Cheapest Base Rate']
    comprehensive_data['Savings Percentage'] = (comprehensive_data['Potential Savings'] / comprehensive_data['Total Rate'] * 100).round(2)
    
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
