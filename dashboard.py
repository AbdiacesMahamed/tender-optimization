"""
Carrier Tender Optimization Dashboard
Main application file that orchestrates all components
"""

# Import necessary libraries
import pandas as pd
import streamlit as st

# Import diagnostic tool


# Import all dashboard components
from components import (
    # Configuration
    configure_page, apply_custom_css, show_header,
    
    # Data handling
    show_file_upload_section, load_data_files, process_performance_data,
    validate_and_process_gvt_data, validate_and_process_rate_data, merge_all_data, 
    apply_volume_weighted_performance, create_comprehensive_data,perform_lane_analysis,
    
    # Filtering
    show_filter_interface, apply_filters_to_data, show_selection_summary,
    show_rate_type_selector,
    
    # Metrics
    calculate_enhanced_metrics, display_current_metrics, show_detailed_analysis_table,
    show_top_savings_opportunities, show_complete_data_export, show_performance_score_analysis,
    show_carrier_performance_matrix,
    
    # Tables and analysis
    show_summary_tables,
    
    # Analytics and visualizations
    show_advanced_analytics, show_interactive_visualizations,
    
    # Utilities
    show_calculation_logic, show_debug_performance_merge, show_footer,
    show_performance_assignments_table, export_performance_assignments
)

from components.constraints_processor import (
    process_constraints_file,
    apply_constraints_to_data,
    show_constraints_summary,
)

# Import optimization module for historic volume analysis
from optimization import show_historic_volume_analysis

def main():
    """Main dashboard application"""
    
    # Configure page and apply styling
    configure_page()
    apply_custom_css()
    show_header()
    
    # File upload and data loading
    gvt_file, rate_file, performance_file, constraints_file = show_file_upload_section()
    
    with st.spinner('⚙️ Loading and processing data...'):
        GVTdata, Ratedata, Performancedata, has_performance = load_data_files(gvt_file, rate_file, performance_file)
        
        # Process performance data
        performance_clean, has_performance = process_performance_data(Performancedata, has_performance)
        
        # Validate and process data
        GVTdata = validate_and_process_gvt_data(GVTdata)
        Ratedata = validate_and_process_rate_data(Ratedata)
        
        # Merge all data
        merged_data = merge_all_data(GVTdata, Ratedata, performance_clean, has_performance)
        
        # Apply volume-weighted performance calculations to fill missing data
        merged_data = apply_volume_weighted_performance(merged_data)
    
    # Show performance assignments table
    show_performance_assignments_table()
    
    with st.spinner('📊 Creating comprehensive data view...'):
        comprehensive_data = create_comprehensive_data(merged_data)
    
    # Show rate type selector (Base Rate vs CPC)
    show_rate_type_selector(comprehensive_data)
    
    # Show filters
    show_filter_interface(comprehensive_data)
    
    # Apply filters
    final_filtered_data, display_ports, display_fcs, display_weeks, display_scacs = apply_filters_to_data(comprehensive_data)
    
    # Show selection summary
    show_selection_summary(display_ports, display_fcs, display_weeks, display_scacs, final_filtered_data)
    
    # Process and apply constraints if file is uploaded
    with st.spinner('🔒 Processing constraints...'):
        constraints_df = None
        constrained_data = pd.DataFrame()
        unconstrained_data = final_filtered_data.copy()
        constraint_summary = []
        max_constrained_carriers = set()  # Carriers with maximum constraints (hard caps)
        carrier_facility_exclusions = {}  # Carrier+facility exclusions
        
        explanation_logs = []  # For downloadable constraint explanations
        
        if constraints_file is not None:
            st.markdown("---")
            constraints_df = process_constraints_file(constraints_file)
            
            if constraints_df is not None:
                # Apply constraints to filtered data
                constrained_data, unconstrained_data, constraint_summary, max_constrained_carriers, carrier_facility_exclusions, explanation_logs = apply_constraints_to_data(
                    final_filtered_data, constraints_df
                )
                
                # Show constraint summary
                if len(constraint_summary) > 0:
                    show_constraints_summary(constraint_summary, explanation_logs)
            else:
                st.warning("⚠️ Constraints file could not be processed")
        else:
            st.info("ℹ️ No constraints file uploaded - all data is unconstrained")
    
    # Calculate metrics on the FULL filtered data (before constraint split)
    # Pass unconstrained_data so scenarios (Performance, Cheapest, Optimized) 
    # only run on unconstrained containers when constraints are active
    # Pass max_constrained_carriers so optimization knows which carriers have hard caps
    # Pass carrier_facility_exclusions so scenarios respect facility-level exclusions
    metrics = calculate_enhanced_metrics(final_filtered_data, unconstrained_data, max_constrained_carriers, carrier_facility_exclusions)
    
    if metrics is None:
        st.warning("⚠️ No data available after applying filters.")
        return
    
    # Display cost analysis dashboard - pass constraint data for proper cost calculation
    display_current_metrics(metrics, constrained_data, unconstrained_data)
    
    # Show detailed analysis table with constrained and unconstrained data
    # Pass carrier_facility_exclusions so scenarios respect facility-level exclusions
    show_detailed_analysis_table(final_filtered_data, unconstrained_data, constrained_data, metrics, max_constrained_carriers, carrier_facility_exclusions)
    
    # 🔬 DIAGNOSTIC TOOL - Enable to debug container count discrepancies
    
    # Show advanced analytics
    show_advanced_analytics(final_filtered_data)
    
    # Show interactive visualizations
    show_interactive_visualizations(final_filtered_data)
    
    # Show historic volume analysis at the bottom
    st.markdown("---")
    show_historic_volume_analysis(final_filtered_data, n_weeks=5)
    
    # Footer
    show_footer()

if __name__ == "__main__":
    main()
