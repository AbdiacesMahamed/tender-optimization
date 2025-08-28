"""
Main optimization module for the Carrier Tender Optimization Dashboard
Orchestrates UI components and calculation logic with unified interface
"""
import streamlit as st
from .config_styling import section_header
from .optimization_ui_fixed import (
    show_unified_optimization_interface
)
from .optimization_calculations import (
    perform_optimization,
    get_optimization_results
)

def show_optimization_section(final_filtered_data):
    """Display the unified Linear Programming optimization interface"""
    section_header("🧮 Linear Programming Optimization")

    if 'Performance_Score' in final_filtered_data.columns and len(final_filtered_data) > 0:
        st.markdown("**Find the optimal balance between cost savings and carrier performance using our unified optimization system.**")
        
        # Check if we have performance data in filtered results
        perf_data_available = final_filtered_data['Performance_Score'].notna().sum()
        
        if perf_data_available == 0:
            st.warning("⚠️ No performance data found in filtered results. The optimization requires performance scores.")
            return
        
        # Show the unified optimization interface
        show_unified_optimization_interface(final_filtered_data)
        
    else:
        st.info("ℹ️ Linear programming optimization requires performance data. Please upload performance data to use this feature.")

# Legacy function maintained for backward compatibility
def run_optimization(final_filtered_data, cost_weight, performance_weight, container_constraints=None, type_restrictions=None):
    """Legacy function - optimization now handled by unified interface"""
    st.info("⚠️ This function is deprecated. Please use the unified optimization interface above.")

# Export the functions that other modules need
__all__ = ['show_optimization_section', 'get_optimization_results']
