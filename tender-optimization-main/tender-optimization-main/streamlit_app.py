"""
Carrier Tender Optimization Dashboard
Main application file that orchestrates all components
"""

# Import necessary libraries
import pandas as pd
import streamlit as st

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
    
    # Metrics
    calculate_enhanced_metrics, display_current_metrics, show_detailed_analysis_table,
    show_top_savings_opportunities, show_complete_data_export, show_performance_score_analysis,
    show_carrier_performance_matrix, show_suboptimal_analysis,
    
    # Tables and analysis
    show_summary_tables,
    
    # Optimization
    show_optimization_section,
    
    # Analytics and visualizations
    show_advanced_analytics, show_interactive_visualizations,
    
    # Utilities
    show_calculation_logic, show_debug_performance_merge, show_footer,
    show_performance_assignments_table, export_performance_assignments
)

def main():
    """Main dashboard application"""
    
    # Configure page and apply styling
    configure_page()
    apply_custom_css()
    show_header()
    
    # File upload and data loading
    gvt_file, rate_file, performance_file = show_file_upload_section()
    GVTdata, Ratedata, Performancedata, has_performance = load_data_files(gvt_file, rate_file, performance_file)
    
    # Process performance data
    performance_clean, has_performance = process_performance_data(Performancedata, has_performance)
    
    # Validate and process data
    GVTdata = validate_and_process_gvt_data(GVTdata)
    Ratedata = validate_and_process_rate_data(Ratedata)
    
    # Perform lane analysis
    cheapest_rates_by_lane = perform_lane_analysis(Ratedata)
    
    # Merge all data
    merged_data = merge_all_data(GVTdata, Ratedata, cheapest_rates_by_lane, performance_clean, has_performance)
    
    # Apply volume-weighted performance calculations to fill missing data
    merged_data = apply_volume_weighted_performance(merged_data)
    
    # Show performance assignments table
    show_performance_assignments_table()
    
    comprehensive_data = create_comprehensive_data(merged_data)
    
    # Show filters
    show_filter_interface(comprehensive_data)
    
    # Apply filters
    final_filtered_data, display_ports, display_fcs, display_weeks, display_scacs = apply_filters_to_data(comprehensive_data)
    
    # Show selection summary
    show_selection_summary(display_ports, display_fcs, display_weeks, display_scacs, final_filtered_data)
    
    # Calculate and display metrics
    metrics = calculate_enhanced_metrics(final_filtered_data)
    display_current_metrics(metrics)
    
    # Show detailed analysis if data exists
    if len(final_filtered_data) > 0:
        show_detailed_analysis_table(final_filtered_data, metrics)
        show_suboptimal_analysis(final_filtered_data)
        show_performance_score_analysis(final_filtered_data)
        show_summary_tables(final_filtered_data)
        show_top_savings_opportunities(final_filtered_data)
        show_complete_data_export(final_filtered_data)
        export_performance_assignments()  # Export performance assignment data
    
    # Show optimization section
    show_optimization_section(final_filtered_data)
    
    # Show missing rate analysis for optimization (temporarily hidden)
    # show_missing_rate_analysis_for_optimization(final_filtered_data, merged_data)
    
    # Show advanced analytics
    show_advanced_analytics(final_filtered_data)
    
    # Show interactive visualizations
    show_interactive_visualizations(final_filtered_data)
    
    # Footer
    show_footer()

if __name__ == "__main__":
    main()
