"""
Summary tables module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header
from .utils import get_rate_columns


def show_summary_tables(final_filtered_data):
    """Display comprehensive summary tables"""
    # Get current rate type for display
    rate_type = st.session_state.get('rate_type', 'Base Rate')
    rate_type_label = f" ({rate_type})" if rate_type == 'CPC' else ""
    
    section_header(f"📊 Summary Tables{rate_type_label}")
    
    # Check if Terminal column exists in the data
    has_terminal = 'Terminal' in final_filtered_data.columns
    
    if has_terminal:
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🚢 By Port", "🚛 By SCAC", "🛣️ By Lane", "🏭 By Facility", "🖥️ By Terminal", "📅 By Week"])
    else:
        tab1, tab2, tab3, tab4, tab6 = st.tabs(["🚢 By Port", "🚛 By SCAC", "🛣️ By Lane", "🏭 By Facility", "📅 By Week"])
    
    with tab1:
        show_port_summary(final_filtered_data)
    
    with tab2:
        show_scac_summary(final_filtered_data)
    
    with tab3:
        show_lane_summary(final_filtered_data)
    
    with tab4:
        show_facility_summary(final_filtered_data)
    
    if has_terminal:
        with tab5:
            show_terminal_summary(final_filtered_data)
    
    with tab6:
        show_week_summary(final_filtered_data)

def create_aggregation_dict():
    """Create standard aggregation dictionary for summary tables"""
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    
    agg_dict = {
        'Container Count': 'sum',
        rate_cols['total_rate']: 'sum',
        rate_cols['rate']: 'mean'
    }
    return agg_dict

def add_performance_to_aggregation(agg_dict, final_filtered_data):
    """Add performance aggregation if data is available"""
    if 'Performance_Score' in final_filtered_data.columns:
        agg_dict['Performance_Score'] = 'mean'
    return agg_dict

def finalize_summary_table(summary_df):
    """Rename performance column if exists"""
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

def show_terminal_summary(final_filtered_data):
    """Show summary by terminal"""
    if 'Terminal' not in final_filtered_data.columns:
        st.info("Terminal data not available")
        return
    
    terminal_agg = create_aggregation_dict()
    terminal_agg = add_performance_to_aggregation(terminal_agg, final_filtered_data)
        
    terminal_summary = final_filtered_data.groupby('Terminal').agg(terminal_agg).round(2)
    terminal_summary = finalize_summary_table(terminal_summary)
        
    st.dataframe(terminal_summary, use_container_width=True)

def show_week_summary(final_filtered_data):
    """Show summary by week"""
    week_agg = create_aggregation_dict()
    week_agg = add_performance_to_aggregation(week_agg, final_filtered_data)
        
    week_summary = final_filtered_data.groupby('Week Number').agg(week_agg).round(2)
    week_summary = finalize_summary_table(week_summary)
        
    st.dataframe(week_summary, use_container_width=True)
