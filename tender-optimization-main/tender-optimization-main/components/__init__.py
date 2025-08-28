# components/__init__.py
"""
Components package for the Carrier Tender Optimization Dashboard
"""

# Configuration and styling
from .config_styling import configure_page, apply_custom_css, show_header

# Data handling
from .data_loader import show_file_upload_section, load_data_files
from .data_processor import (
    process_performance_data, validate_and_process_gvt_data, 
    validate_and_process_rate_data, merge_all_data, 
    apply_volume_weighted_performance, create_comprehensive_data, 
    perform_lane_analysis
)

# Filtering
from .filters import show_filter_interface, apply_filters_to_data, show_selection_summary

# Metrics
from .metrics import (
    calculate_enhanced_metrics, display_current_metrics, show_detailed_analysis_table,
    show_top_savings_opportunities, show_complete_data_export, show_performance_score_analysis,
    show_carrier_performance_matrix
)

# Analysis components
from .suboptimal_analysis import show_suboptimal_analysis
from .summary_tables import show_summary_tables

# Optimization
from .optimization import show_optimization_section

# Analytics and visualizations
from .analytics import show_advanced_analytics
from .visualizations import show_interactive_visualizations

# Performance assignments
from .performance_assignments import show_performance_assignments_table, export_performance_assignments

# Utilities
from .calculation_logic import show_calculation_logic, show_debug_performance_merge, show_footer

# Make all functions available at package level
__all__ = [
    # Configuration
    'configure_page', 'apply_custom_css', 'show_header',
    
    # Data handling
    'show_file_upload_section', 'load_data_files', 'process_performance_data',
    'validate_and_process_gvt_data', 'validate_and_process_rate_data', 'merge_all_data', 
    'apply_volume_weighted_performance', 'create_comprehensive_data','perform_lane_analysis',
    
    # Filtering
    'show_filter_interface', 'apply_filters_to_data', 'show_selection_summary',
    
    # Metrics
    'calculate_enhanced_metrics', 'display_current_metrics', 'show_detailed_analysis_table',
    'show_top_savings_opportunities', 'show_complete_data_export', 'show_performance_score_analysis',
    'show_carrier_performance_matrix', 'show_suboptimal_analysis',
    
    # Tables and analysis
    'show_summary_tables',
    
    # Optimization
    'show_optimization_section',
    
    # Analytics and visualizations
    'show_advanced_analytics', 'show_interactive_visualizations',
    
    # Utilities
    'show_calculation_logic', 'show_debug_performance_merge', 'show_footer',
    'show_performance_assignments_table', 'export_performance_assignments'
]
