# components/filters.py

## Purpose
Provides the filter sidebar UI and applies user-selected filters to the comprehensive dataset. Also contains the rate type selector (Base Rate vs CPC) and optimization parameter sliders.

## Key Functions

### `show_filter_interface(comprehensive_data)`
Renders the filter UI. Calls `filter_interface_fragment()` which is wrapped in `@st.fragment` for isolated reruns.

### `filter_interface_fragment(comprehensive_data)`
The actual filter widgets:
- Port multiselect
- Facility multiselect
- Week Number multiselect
- Carrier (SCAC) multiselect

Stores selections in `st.session_state` keys: `selected_ports`, `selected_facilities`, `selected_weeks`, `selected_scacs`.

### `show_rate_type_selector(comprehensive_data)`
Radio button to switch between `Base Rate` and `CPC` cost modes. Stored in `st.session_state.rate_type`.

### `show_optimization_settings()`
Sliders for the Optimized scenario parameters:
- `opt_cost_weight` (default 70)
- `opt_performance_weight` (default 30)
- `opt_max_growth_pct` (default 30)

### `apply_filters_to_data(comprehensive_data) -> tuple`
Applies the selected filters and returns `(final_filtered_data, display_ports, display_fcs, display_weeks, display_scacs)`.

### `show_selection_summary(...)`
Displays a summary of active filters and record counts.

## Session State Keys
- `rate_type` — `'Base Rate'` or `'CPC'`
- `selected_ports`, `selected_facilities`, `selected_weeks`, `selected_scacs` — filter selections
- `opt_cost_weight`, `opt_performance_weight`, `opt_max_growth_pct` — optimization sliders
