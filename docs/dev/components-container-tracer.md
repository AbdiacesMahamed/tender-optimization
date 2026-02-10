# components/container_tracer.py

## Purpose
Traces individual container movements between carriers across scenarios. Provides detailed "Carrier Flips" information showing exactly which containers moved from which carrier to which carrier.

## Key Functions

### `build_container_origin_map(original_data, carrier_col, week_col) -> dict`
Builds a lookup map from the original (baseline) data: `{container_id: {carrier, week, group_key, ...}}`. This is the "before" snapshot.

### `trace_container_movements(current_data, origin_map, carrier_col, group_cols) -> list`
For each row in the current (scenario) data, traces which containers came from which original carriers. Returns a list of trace results per row.

### `format_flip_details(trace_result, ...) -> str`
Formats a trace result into a human-readable string like:
- `"✓ Kept 15"` — no change
- `"✓ Had 10, now 15 (+5 from XPDR)"` — gained containers
- `"🔄 New: 20 (from ABCD: 12, EFGH: 8)"` — carrier is new to this group

### `add_detailed_carrier_flips_column(current_data, original_data, carrier_col) -> DataFrame`
Main entry point. Adds a `Carrier Flips (Detailed)` column to `current_data` by building the origin map and tracing all movements. Used by `metrics.py` for all scenario displays.

### `get_container_movement_summary(current_data, original_data, carrier_col) -> dict`
Returns aggregate movement statistics (total moved, carriers gained/lost, etc.).

## How It Works
1. Parse all container IDs from the baseline data into an origin map
2. For each row in the scenario data, parse its container IDs
3. Look up each container in the origin map to find its original carrier
4. Aggregate: how many came from each original carrier
5. Format into a readable string
