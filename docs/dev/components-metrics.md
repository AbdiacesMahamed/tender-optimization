# components/metrics.py

## Purpose
The largest module in the project (~2000 lines). Handles all cost/metric calculations, the detailed analysis table with 4 scenario views, peel pile analysis, and carrier flip tracking display.

## Key Functions

### `calculate_enhanced_metrics(data, unconstrained_data, max_constrained_carriers, carrier_facility_exclusions, full_unfiltered_data) -> dict`
Calculates the top-level cost metrics for all 4 scenarios:
- **Current Selection**: Sum of `Total Rate` from the filtered data
- **Performance**: Runs `allocate_to_highest_performance()` on unconstrained data
- **Cheapest**: Finds cheapest carrier per group, sums cost
- **Optimized**: Runs `cascading_allocate_with_constraints()` with LP + historical constraints

Returns a dict with keys: `total_cost`, `total_containers`, `performance_cost`, `cheapest_cost`, `optimized_cost`, etc.

### `display_current_metrics(metrics, constrained_data, unconstrained_data)`
Renders the 4 cost comparison cards at the top of the dashboard (Current, Performance, Cheapest, Optimized) with savings/cost differences.

### `show_detailed_analysis_table(final_filtered_data, unconstrained_data, constrained_data, ...)`
The main analysis table. Contains:
1. **Strategy selector** dropdown (Current / Performance / Cheapest / Optimized)
2. **Constrained data table** (locked allocations, shown for all scenarios)
3. **Unconstrained data table** (manipulated by the selected scenario)
4. **Peel pile analysis** section at the bottom

Each scenario builds its own `display_data` DataFrame with scenario-specific columns, then renders it with formatting.

**Display column order** (for Current/Performance/Optimized):
```
Port → Category → SSL → Vessel → Carrier → Lane → Facility → Terminal → Week → Ocean ETA → Container Numbers → Carrier Flips → Container Count → Rate → Total Cost → Performance → [scenario-specific columns]
```

### `show_peel_pile_analysis(data)`
Renders the peel pile table (vessel groups with 30+ containers) and the allocation UI:
- Uses `@st.fragment` to isolate the queue UI from full page reruns
- Dropdowns for group selection + carrier assignment
- Queue system: Add to Queue → Apply All workflow
- Applied allocations stored in `st.session_state.peel_pile_allocations`

### `apply_peel_pile_as_constraints(final_filtered_data, constrained_data, unconstrained_data, constraint_summary) -> tuple`
Converts peel pile allocations into constraints. Moves matching rows from unconstrained to constrained data, reassigns carrier, adds to constraint summary.

### `add_carrier_flips_column(current_data, original_data, carrier_col)`
Adds a column showing how carrier allocations changed (gained/lost/new/kept) compared to the original data.

## Session State Keys
- `peel_pile_allocations` — dict of applied peel pile assignments `{group_key: carrier}`
- `peel_pile_pending` — dict of queued (not yet applied) assignments

## Dependencies
- `optimization.performance_logic.allocate_to_highest_performance`
- `optimization.cascading_logic.cascading_allocate_with_constraints`
- `components.container_tracer.add_detailed_carrier_flips_column`
- `components.utils` (formatting, grouping, rate columns)
