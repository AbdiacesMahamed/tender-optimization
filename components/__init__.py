"""
Main imports file for all dashboard components
"""

# Shared utilities (import first as other modules depend on these)
from .utils import (
    get_rate_columns,
    count_containers,
    parse_container_ids,
    join_container_ids,
    concat_and_dedupe_containers,
    get_grouping_columns,
    normalize_facility_code,
    safe_numeric,
    format_currency,
    format_percentage,
    format_number,
    filter_excluded_carrier_facility_rows,
    deduplicate_containers_per_lane_week
)

# Configuration and styling
from .config_styling import configure_page, apply_custom_css, show_header, section_header

# Data loading and processing
from .data_loader import show_file_upload_section, load_data_files, process_performance_data
from .data_processor import (
    validate_and_process_gvt_data, 
    validate_and_process_rate_data, 
    perform_lane_analysis, 
    merge_all_data, 
    apply_volume_weighted_performance,
    create_comprehensive_data
)

# Filtering
from .filters import (
    show_filter_interface, 
    apply_filters_to_data, 
    show_selection_summary,
    show_rate_type_selector
)

# Metrics and analysis
from .metrics import (
    calculate_enhanced_metrics, 
    display_current_metrics, 
    show_detailed_analysis_table, 
    show_top_savings_opportunities,
    show_complete_data_export,
    show_performance_score_analysis,
    show_carrier_performance_matrix,
    show_container_movement_summary,
    apply_peel_pile_as_constraints
)

# Summary tables
from .summary_tables import show_summary_tables

# Analytics
from .analytics import show_advanced_analytics

# Visualizations
from .visualizations import show_interactive_visualizations

# Calculation logic and utilities
from .calculation_logic import show_calculation_logic, show_debug_performance_merge, show_footer
from .performance_assignments import show_performance_assignments_table, export_performance_assignments
from .constraints_processor import (
    process_constraints_file,
    apply_constraints_to_data,
    show_constraints_summary
)

# Import optimization functions - imported after components to avoid circular dependencies
try:
    from optimization.performance_logic import allocate_to_highest_performance
except ImportError:
    # Fallback if optimization module is not available
    allocate_to_highest_performance = None

__all__ = [
    # Utilities
    'get_rate_columns', 'count_containers', 'parse_container_ids', 'join_container_ids',
    'concat_and_dedupe_containers', 'get_grouping_columns', 'normalize_facility_code',
    'safe_numeric', 'format_currency', 'format_percentage', 'format_number',
    'filter_excluded_carrier_facility_rows',
    
    # Configuration
    'configure_page', 'apply_custom_css', 'show_header', 'section_header',
    
    # Data handling
    'show_file_upload_section', 'load_data_files', 'process_performance_data',
    'validate_and_process_gvt_data', 'validate_and_process_rate_data', 
    'perform_lane_analysis', 'merge_all_data', 'apply_volume_weighted_performance', 'create_comprehensive_data',
    
    # Filtering
    'show_filter_interface', 'apply_filters_to_data', 'show_selection_summary', 'show_rate_type_selector',
    
    # Constraints
    'process_constraints_file', 'apply_constraints_to_data', 'show_constraints_summary',
    
    # Metrics
    'calculate_enhanced_metrics', 'display_current_metrics', 'show_detailed_analysis_table',
    'show_top_savings_opportunities', 'show_complete_data_export', 'show_performance_score_analysis',
    'show_carrier_performance_matrix', 'show_container_movement_summary',
    'apply_peel_pile_as_constraints',
    
    # Tables and analysis
    'show_summary_tables',
    
    # Analytics and visualizations
    'show_advanced_analytics', 'show_interactive_visualizations',
    
    # Utilities
    'show_calculation_logic', 'show_debug_performance_merge', 'show_footer',
    'show_performance_assignments_table', 'export_performance_assignments',
]

# Add optimization functions if they were successfully imported
if allocate_to_highest_performance is not None:
    __all__.append('allocate_to_highest_performance')
