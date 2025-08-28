"""
Performance calculation module for the Carrier Tender Optimization Dashboard
Handles performance-based cost optimization calculations
"""
import pandas as pd

def calculate_performance_optimization(final_filtered_data):
    """
    Calculate performance-based optimization costs and data
    
    Args:
        final_filtered_data: DataFrame with carrier, performance, and cost data
        
    Returns:
        tuple: (highest_perf_cost, performance_data_list)
            - highest_perf_cost: Total cost if all volume goes to best performers
            - performance_data_list: List of dicts with detailed performance optimization data
    """
    if 'Performance_Score' not in final_filtered_data.columns:
        return 0, []
    
    highest_perf_cost = 0
    performance_data_list = []
    
    # First, calculate volume-weighted average performance for each carrier across all weeks
    carrier_weighted_performance = {}
    for carrier, carrier_group in final_filtered_data.groupby('Dray SCAC(FL)'):
        # Get records with valid performance scores
        valid_perf_records = carrier_group.dropna(subset=['Performance_Score'])
        
        if len(valid_perf_records) > 0:
            # Calculate volume-weighted average performance
            total_weighted_performance = (valid_perf_records['Performance_Score'] * 
                                        valid_perf_records['Container Count']).sum()
            total_volume = valid_perf_records['Container Count'].sum()
            carrier_weighted_performance[carrier] = total_weighted_performance / total_volume
        else:
            # No performance data for this carrier at all
            carrier_weighted_performance[carrier] = 0
    
    # Now analyze each Lane-Week combination
    for (lane, week), group in final_filtered_data.groupby(['Lane', 'Week Number']):
        # Get all carriers that service this lane-week with their effective performance
        carriers_performance = {}
        
        for _, record in group.iterrows():
            carrier = record['Dray SCAC(FL)']
            
            # Use actual performance score if available, otherwise use weighted average
            if pd.notna(record['Performance_Score']):
                effective_performance = record['Performance_Score']
                performance_source = 'Actual'
            else:
                # Use volume-weighted average performance
                effective_performance = carrier_weighted_performance.get(carrier, 0)
                performance_source = 'Volume-Weighted Average'
            
            carriers_performance[carrier] = {
                'performance': effective_performance,
                'base_rate': record['Base Rate'],
                'record': record,
                'performance_source': performance_source
            }
        
        # Find the carrier with highest performance for this lane-week
        if carriers_performance:
            best_carrier = max(carriers_performance.keys(), 
                             key=lambda x: carriers_performance[x]['performance'])
            
            best_carrier_info = carriers_performance[best_carrier]
            
            # Get total volume for this lane-week (sum all containers)
            total_lane_week_volume = group['Container Count'].sum()
            
            # Assign ALL volume to the best performing carrier
            best_carrier_rate = best_carrier_info['base_rate']
            lane_week_cost = best_carrier_rate * total_lane_week_volume
            highest_perf_cost += lane_week_cost
            
            # Create detailed performance optimization data for each record in this lane-week
            for _, current in group.iterrows():
                performance_data = {
                    'Lane': lane,
                    'Week_Number': week,
                    'Current_Carrier': current['Dray SCAC(FL)'],
                    'Current_Base_Rate': current['Base Rate'],
                    'Current_Total_Cost': current['Total Rate'],
                    'Current_Performance': current.get('Performance_Score', 0),
                    'Container_Count': current['Container Count'],
                    'Best_Performance_Carrier': best_carrier,
                    'Best_Performance_Rate': best_carrier_rate,
                    'Best_Performance_Score': best_carrier_info['performance'],
                    'Best_Performance_Source': best_carrier_info['performance_source'],
                    'Hypothetical_Total_Cost': best_carrier_rate * current['Container Count'],
                    'Cost_Difference': (best_carrier_rate * current['Container Count']) - current['Total Rate'],
                    'Performance_Difference': best_carrier_info['performance'] - current.get('Performance_Score', 0),
                    'Discharged_Port': current.get('Discharged Port', ''),
                    'Facility': current.get('Facility', ''),
                    'Dray_SCAC': current['Dray SCAC(FL)']
                }
                
                performance_data_list.append(performance_data)
    
    return highest_perf_cost, performance_data_list

def get_carrier_weighted_performance(final_filtered_data):
    """
    Calculate volume-weighted average performance for each carrier across all weeks
    Uses Container Count for proper volume weighting
    """
    carrier_weighted_performance = {}
    
    # Handle different column naming conventions
    carrier_col = 'Carrier' if 'Carrier' in final_filtered_data.columns else 'Dray SCAC(FL)'
    
    # Get all unique carriers first to ensure we process every carrier
    all_carriers = final_filtered_data[carrier_col].unique()
    
    for carrier in all_carriers:
        carrier_group = final_filtered_data[final_filtered_data[carrier_col] == carrier]
        
        # Get records with valid performance scores
        valid_perf_records = carrier_group.dropna(subset=['Performance_Score'])
        
        if len(valid_perf_records) > 0 and 'Container Count' in final_filtered_data.columns:
            # Calculate TRUE volume-weighted average performance
            total_weighted_performance = (
                valid_perf_records['Performance_Score'] * 
                valid_perf_records['Container Count']
            ).sum()
            total_volume = valid_perf_records['Container Count'].sum()
            
            if total_volume > 0:
                carrier_weighted_performance[carrier] = total_weighted_performance / total_volume
            else:
                # Fallback to simple average if total volume is 0
                carrier_weighted_performance[carrier] = valid_perf_records['Performance_Score'].mean()
        elif len(valid_perf_records) > 0:
            # If no container count available, use simple average
            carrier_weighted_performance[carrier] = valid_perf_records['Performance_Score'].mean()
        # Note: Carriers with no performance data will not be in this dict
        # The calling function should handle this case
    
    return carrier_weighted_performance

def find_best_performer_for_lane_week(group, carrier_weighted_performance):
    """
    Find the best performing carrier for a specific lane-week combination
    
    Args:
        group: DataFrame group for a specific lane-week
        carrier_weighted_performance: Dict of carrier -> weighted performance
        
    Returns:
        tuple: (best_carrier, best_performance, performance_source, best_rate)
    """
    carriers_performance = {}
    
    for _, record in group.iterrows():
        carrier = record['Dray SCAC(FL)']
        
        # Use actual performance score if available, otherwise use weighted average
        if pd.notna(record['Performance_Score']):
            effective_performance = record['Performance_Score']
            performance_source = 'Actual'
        else:
            # Use volume-weighted average performance
            effective_performance = carrier_weighted_performance.get(carrier, 0)
            performance_source = 'Volume-Weighted Average'
        
        carriers_performance[carrier] = {
            'performance': effective_performance,
            'base_rate': record['Base Rate'],
            'performance_source': performance_source
        }
    
    if carriers_performance:
        best_carrier = max(carriers_performance.keys(), 
                         key=lambda x: carriers_performance[x]['performance'])
        
        best_info = carriers_performance[best_carrier]
        return (best_carrier, 
                best_info['performance'], 
                best_info['performance_source'],
                best_info['base_rate'])
    
    return None, 0, 'No Data', 0
