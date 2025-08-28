"""
Summary tables module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header
from .optimization_calculations import get_optimization_results

def get_optimization_results_from_session():
    """Get optimization results from session state"""
    return st.session_state.get('optimization_results', None)

def show_summary_tables(final_filtered_data):
    """Display comprehensive summary tables"""
    section_header("📊 Summary Tables")
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🚢 By Port", "🚛 By SCAC", "🛣️ By Lane", "🏭 By Facility", "📅 By Week", "📊 SCAC by Port %"])
    
    with tab1:
        show_port_summary(final_filtered_data)
    
    with tab2:
        show_scac_summary(final_filtered_data)
    
    with tab3:
        show_lane_summary(final_filtered_data)
    
    with tab4:
        show_facility_summary(final_filtered_data)
    
    with tab5:
        show_week_summary(final_filtered_data)
        
    with tab6:
        show_scac_by_port_percentage(final_filtered_data)

def create_aggregation_dict():
    """Create standard aggregation dictionary for summary tables"""
    agg_dict = {
        'Container Count': 'sum',
        'Total Rate': 'sum',
        'Cheapest Total Rate': 'sum',
        'Potential Savings': 'sum',
        'Base Rate': 'mean',
        'Cheapest Base Rate': 'mean'
    }
    return agg_dict

def add_performance_to_aggregation(agg_dict, final_filtered_data):
    """Add performance aggregation if data is available"""
    if 'Performance_Score' in final_filtered_data.columns:
        agg_dict['Performance_Score'] = 'mean'
    return agg_dict

def finalize_summary_table(summary_df):
    """Add savings percentage and rename performance column"""
    summary_df['Savings %'] = (summary_df['Potential Savings'] / summary_df['Total Rate'] * 100).round(1)
    
    if 'Performance_Score' in summary_df.columns:
        summary_df = summary_df.rename(columns={'Performance_Score': 'Avg Carrier Performance'})
    
    return summary_df

def show_port_summary(final_filtered_data):
    """Show summary by port"""
    port_agg = create_aggregation_dict()
    port_agg = add_performance_to_aggregation(port_agg, final_filtered_data)
        
    port_summary = final_filtered_data.groupby('Discharged Port').agg(port_agg).round(2)
    port_summary = finalize_summary_table(port_summary)
        
    st.dataframe(port_summary, use_container_width=True)

def show_scac_summary(final_filtered_data):
    """Show summary by SCAC"""
    scac_agg = create_aggregation_dict()
    scac_agg = add_performance_to_aggregation(scac_agg, final_filtered_data)
        
    scac_summary = final_filtered_data.groupby('Dray SCAC(FL)').agg(scac_agg).round(2)
    scac_summary = finalize_summary_table(scac_summary)
        
    st.dataframe(scac_summary, use_container_width=True)

def show_lane_summary(final_filtered_data):
    """Show summary by lane"""
    lane_agg = create_aggregation_dict()
    lane_agg = add_performance_to_aggregation(lane_agg, final_filtered_data)
        
    lane_summary = final_filtered_data.groupby('Lane').agg(lane_agg).round(2)
    lane_summary = finalize_summary_table(lane_summary)
        
    st.dataframe(lane_summary, use_container_width=True)

def show_facility_summary(final_filtered_data):
    """Show summary by facility"""
    facility_agg = create_aggregation_dict()
    facility_agg = add_performance_to_aggregation(facility_agg, final_filtered_data)
        
    facility_summary = final_filtered_data.groupby('Facility').agg(facility_agg).round(2)
    facility_summary = finalize_summary_table(facility_summary)
        
    st.dataframe(facility_summary, use_container_width=True)

def show_week_summary(final_filtered_data):
    """Show summary by week"""
    week_agg = create_aggregation_dict()
    week_agg = add_performance_to_aggregation(week_agg, final_filtered_data)
        
    week_summary = final_filtered_data.groupby('Week Number').agg(week_agg).round(2)
    week_summary = finalize_summary_table(week_summary)
        
    st.dataframe(week_summary, use_container_width=True)

def show_scac_by_port_percentage(final_filtered_data):
    """Show SCAC container percentage by port with current vs optimized values"""
    st.markdown("### Container Distribution by SCAC and Port")
    
    # Check if optimization is available
    try:
        current_cost_weight = st.session_state.get('cost_weight', 0.7)
        current_performance_weight = st.session_state.get('performance_weight', 0.3)
        optimization_results = get_optimization_results(final_filtered_data, current_cost_weight, current_performance_weight)
        has_optimization = optimization_results is not None and len(optimization_results) > 0
    except:
        has_optimization = False
        optimization_results = None
    
    # Create current allocation table
    current_allocation = create_scac_port_percentage_table(final_filtered_data, "Current")
    
    if has_optimization:
        # Create optimized allocation table
        optimized_allocation = create_scac_port_percentage_table(optimization_results, "Optimized")
        
        # Display both tables side by side
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**📊 Current Allocation**")
            st.dataframe(current_allocation, use_container_width=True)
        
        with col2:
            st.markdown("**🎯 Optimized Allocation**")
            st.dataframe(optimized_allocation, use_container_width=True)
        
        # Create comparison table showing the changes
        st.markdown("**🔄 Optimization Impact**")
        comparison_table = create_allocation_comparison_table(current_allocation, optimized_allocation)
        st.dataframe(comparison_table, use_container_width=True)
        
    else:
        st.markdown("**📊 Current Allocation**")
        st.dataframe(current_allocation, use_container_width=True)
        st.info("💡 Optimization results not available. Upload performance data and ensure multiple carriers per lane for optimization comparison.")

def create_scac_port_percentage_table(data, label):
    """Create a SCAC by port percentage allocation table"""
    # Group by Port and SCAC to get container counts
    port_scac_summary = data.groupby(['Discharged Port', 'Dray SCAC(FL)'])['Container Count'].sum().reset_index()
    
    # Calculate total containers per port
    port_totals = data.groupby('Discharged Port')['Container Count'].sum().reset_index()
    port_totals.columns = ['Discharged Port', 'Port Total']
    
    # Merge to get port totals
    port_scac_summary = port_scac_summary.merge(port_totals, on='Discharged Port')
    
    # Calculate percentages
    port_scac_summary['Percentage'] = (port_scac_summary['Container Count'] / port_scac_summary['Port Total'] * 100).round(1)
    
    # Pivot to create the percentage table
    percentage_table = port_scac_summary.pivot(index='Discharged Port', 
                                               columns='Dray SCAC(FL)', 
                                               values='Percentage').fillna(0)
    
    # Add total containers column
    percentage_table = percentage_table.merge(port_totals.set_index('Discharged Port'), 
                                             left_index=True, right_index=True, how='left')
    
    # Round all percentage columns
    for col in percentage_table.columns:
        if col != 'Port Total':
            percentage_table[col] = percentage_table[col].round(1)
    
    return percentage_table

def create_allocation_comparison_table(current_allocation, optimized_allocation):
    """Create a comparison table showing changes between current and optimized allocations"""
    # Ensure both tables have the same structure
    all_ports = set(current_allocation.index) | set(optimized_allocation.index)
    all_scacs = set(current_allocation.columns) | set(optimized_allocation.columns)
    all_scacs.discard('Port Total')  # Remove the total column from SCAC comparison
    
    comparison_data = []
    
    for port in all_ports:
        for scac in all_scacs:
            current_pct = current_allocation.loc[port, scac] if port in current_allocation.index and scac in current_allocation.columns else 0
            optimized_pct = optimized_allocation.loc[port, scac] if port in optimized_allocation.index and scac in optimized_allocation.columns else 0
            
            change = optimized_pct - current_pct
            
            if abs(change) > 0.1:  # Only show meaningful changes
                comparison_data.append({
                    'Port': port,
                    'SCAC': scac,
                    'Current %': f"{current_pct:.1f}%",
                    'Optimized %': f"{optimized_pct:.1f}%",
                    'Change': f"{change:+.1f}%",
                    'Direction': '📈 Increase' if change > 0 else '📉 Decrease'
                })
    
    if comparison_data:
        comparison_df = pd.DataFrame(comparison_data)
        # Sort by absolute change descending
        comparison_df['abs_change'] = comparison_df['Change'].str.replace('%', '').str.replace('+', '').astype(float).abs()
        comparison_df = comparison_df.sort_values('abs_change', ascending=False).drop('abs_change', axis=1)
        return comparison_df
    else:
        return pd.DataFrame({'Message': ['No significant changes in allocation']})
