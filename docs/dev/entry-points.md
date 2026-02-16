# Entry Points

## dashboard.py — Main Application
The primary Streamlit application. Orchestrates the full pipeline:

1. **Page setup**: `configure_page()`, `apply_custom_css()`, `show_header()`
2. **File upload**: `show_file_upload_section()` → 4 file uploaders
3. **Data loading**: `load_data_files()` → raw DataFrames
4. **Processing**: `validate_and_process_gvt_data()`, `validate_and_process_rate_data()`, `merge_all_data()`
5. **Comprehensive view**: `create_comprehensive_data()`
6. **Filters**: `show_rate_type_selector()`, `show_filter_interface()`, `apply_filters_to_data()`
7. **Constraints**: `process_constraints_file()`, `apply_constraints_to_data()`
8. **Peel pile constraints**: `apply_peel_pile_as_constraints()` (from session state)
9. **Container deduplication**: `deduplicate_containers_per_lane_week()` on `final_filtered_data`, `constrained_data`, and `unconstrained_data` — ensures each container belongs to only one carrier per lane/week before any calculations
10. **Metrics**: `calculate_enhanced_metrics()` → cost calculations for all 4 scenarios
11. **Display**: `display_current_metrics()` → cost cards, `show_detailed_analysis_table()` → main table
12. **Analytics**: `show_advanced_analytics()`, `show_interactive_visualizations()`
13. **Historic volume**: `show_historic_volume_analysis()`

Run with: `streamlit run dashboard.py`

## streamlit_app.py — Cloud Entry Point
Thin wrapper that imports and calls `dashboard.main()`. Used for Streamlit Cloud deployment where the entry file must be in the root.

## app.py — Desktop Launcher
Starts Streamlit as a subprocess, waits for the server, then opens a browser window. Optionally uses `pywebview` for a native desktop window (set `USE_PYWEBVIEW=1`).

Run with: `python app.py`

## installer/installer.iss
Inno Setup script for building a Windows installer. Packages the Python environment and app files into a distributable `.exe`.
