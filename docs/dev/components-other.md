# Other Component Modules

## components/config_styling.py
Page configuration and CSS. Functions: `configure_page()`, `apply_custom_css()`, `show_header()`, `section_header(title)`, `info_box(msg)`, `success_box(msg)`.

## components/summary_tables.py
Renders summary aggregation tables in tabs: By Port, By SCAC, By Lane, By Facility, By Terminal, By Week. Each tab groups the filtered data and shows Container Count, Total Rate, Avg Rate, and Avg Performance.

## components/analytics.py
Advanced analytics section with 3 tabs:
- **Predictive Analytics**: Linear regression forecasting of container volumes per lane
- **Performance Trends**: Carrier performance over time with multi-carrier comparison
- **Anomaly Detection**: IQR-based rate anomaly detection with box plot visualization

Uses `scikit-learn` for forecasting and `plotly` for charts.

## components/visualizations.py
Interactive Plotly visualizations:
- Cost vs Performance scatter/quadrant analysis
- Geographic port analysis
- Lane heatmap
- Weekly time series trends
- Growth rate analysis
- Correlation heatmap and insights

## components/performance_assignments.py
Tracks and displays how performance scores were assigned to carriers during data processing. Uses a global `PerformanceAssignmentTracker` singleton. Shows assignment type (direct match, volume-weighted, fallback), records affected, and average scores.

## components/performance_calculator.py
Standalone performance optimization calculator. Functions:
- `calculate_performance_optimization()` — Calculates what-if performance scenario
- `get_carrier_weighted_performance()` — Volume-weighted performance per carrier
- `find_best_performer_for_lane_week()` — Best carrier for a specific lane/week

## components/missing_rate_analysis.py
Identifies and reports lanes/carriers with missing rate data. Shows which container groups have no pricing and their impact on cost calculations.

## components/constraints_advanced.py
UI for creating constraints interactively (not from file upload). Provides a template builder, validation, and application interface. Separate from `constraints_processor.py` which handles file-based constraints.

## components/calculation_logic.py
- `show_calculation_logic()` — Renders the "how calculations work" explanation panel
- `show_debug_performance_merge()` — Debug view for performance data merge diagnostics
- `show_footer()` — Dashboard footer
