# optimization/ Module

## Purpose
Contains all carrier allocation optimization algorithms. Each strategy takes a DataFrame of carrier options per lane/week and returns a DataFrame with containers allocated to the selected carriers.

## Module Structure

### optimization/optimization.py — Orchestrator
Main entry point via `optimize_allocation(data, strategy, cost_weight, performance_weight)`.
Routes to the appropriate strategy:
- `"linear_programming"` → `linear_programming.optimize_carrier_allocation()`
- `"performance"` → `performance_logic.allocate_to_highest_performance()`

Also provides `calculate_optimization_metrics()` for before/after comparison.

### optimization/linear_programming.py — LP Optimization
Uses PuLP to solve a weighted cost/performance optimization per lane group.

Key functions:
- `optimize_carrier_allocation(data, cost_weight, performance_weight)` — Main LP entry point
- `_optimize_single_group(group_data, ...)` — Solves LP for one lane/week group
- `_normalize_values(values, lower_is_better)` — Min-max normalization for objective function

Decision variables are **Continuous** (fractional splits allowed). After solving, allocations are rounded to integers using the **largest-remainder method** which guarantees `sum(rounded) == total_containers`. This prevents container loss from rounding.

The objective minimizes `cost_weight * normalized_cost + performance_weight * (1 - normalized_performance)`.

### optimization/performance_logic.py — Highest Performance Allocation
Allocates 100% of containers in each lane/week to the carrier with the highest `Performance_Score`.

Key function: `allocate_to_highest_performance(data, ...)` — Groups by lane/week, picks best performer, concatenates + deduplicates all container numbers, recalculates costs.

Group columns: `['Lane', 'Week Number']` (defined in `DEFAULT_GROUP_COLUMNS`).

### optimization/cascading_logic.py — Cascading LP + Historical Constraints
The most sophisticated optimization. Combines LP ranking with historical volume share constraints.

Key functions:
- `cascading_allocate_with_constraints(data, max_growth_pct, cost_weight, performance_weight, n_historical_weeks, ...)` — Main entry point
- `_cascading_allocate_single_group(group_data, ...)` — Per-group allocation
- `_rank_carriers_from_lp(group_data, ...)` — Uses LP to rank carriers by cost/performance score
- `_get_historical_percentages(carrier, lane, historical_data, ...)` — Looks up carrier's historical market share
- `_cascade_allocate_volume(ranked_carriers, total_volume, historical_pcts, max_growth_pct)` — Distributes volume respecting growth caps, uses largest-remainder rounding to preserve totals

Flow per group:
1. Rank carriers using LP objective scores
2. Look up each carrier's historical volume share (last N weeks)
3. Allocate volume top-down, capping each carrier at `historical_share + max_growth_pct`
4. Overflow goes to next-ranked carrier
5. Final rounding uses largest-remainder method to preserve total container count

### optimization/historic_volume.py — Historical Volume Analysis
Calculates carrier market share from historical data.

Key functions:
- `get_last_n_weeks(data, n)` — Get the last N week numbers
- `filter_historical_weeks(data, n_weeks)` — Filter data to last N weeks
- `calculate_carrier_volume_share(data, ...)` — Carrier % share per lane
- `calculate_carrier_weekly_trends(data, ...)` — Week-over-week volume trends
- `get_carrier_lane_participation(data, ...)` — Which carriers serve which lanes

### optimization/historic_volume_display.py — Historic Volume UI
Streamlit display for historical volume analysis:
- Market share pie/bar charts
- Weekly trend line charts
- Lane participation matrix
- Data export

## Parameters (from UI sliders in filters.py)
| Parameter | Session State Key | Default | Description |
|-----------|------------------|---------|-------------|
| Cost Weight | `opt_cost_weight` | 70 | % weight for cost in LP objective |
| Performance Weight | `opt_performance_weight` | 30 | % weight for performance in LP objective |
| Max Growth | `opt_max_growth_pct` | 30 | Max % a carrier can grow beyond historical share |

## Logging
All `print()` statements replaced with `logging.getLogger(__name__).debug()`. Clean console by default.
