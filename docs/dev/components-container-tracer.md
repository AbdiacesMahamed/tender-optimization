# components/container_tracer.py

## Purpose
Traces individual container movements between carriers across scenarios. Provides detailed "Carrier Flips" information showing exactly which containers moved from which carrier to which carrier.

## Key Functions

### `build_container_origin_map(original_data, carrier_col, week_col) -> dict`
Builds a lookup map from the original (baseline) data: `{container_id: {carrier, week, group_key, ...}}`. This is the "before" snapshot. Stores context for each container including: `original_carrier`, `week`, `discharged_port`, `lane`, `facility`, `terminal`, `category`, `ssl`, `vessel`.

### `trace_container_movements(current_data, origin_map, carrier_col, group_cols) -> list`
For each row in the current (scenario) data, traces which containers came from which original carriers. Builds group keys from both the origin map and current data, normalizing types (int for week, `''` for NaN) to ensure matching. Returns a list of trace results per row plus a container destinations map.

### `format_flip_details(trace_result, ...) -> str`
Formats a trace result into a human-readable string:
- `"No Flip"` — no change (kept all containers, or had 0 and still 0)
- `"Had 10 → From XPDR (+5) → Now 15"` — gained containers from another carrier
- `"Had 10 → Lost 3 → To ABCD (-3) → Now 7"` — lost containers to another carrier

### `add_detailed_carrier_flips_column(current_data, original_data, carrier_col) -> DataFrame`
Main entry point. Adds a `Carrier Flips (Detailed)` column to `current_data` by building the origin map and tracing all movements. Used by `metrics.py` for all scenario displays.

### `get_container_movement_summary(current_data, original_data, carrier_col) -> dict`
Returns aggregate movement statistics (total moved, carriers gained/lost, etc.).

## How It Works
1. Parse all container IDs from the baseline data into an origin map (stores carrier, week, port, lane, facility, terminal, category, SSL, vessel per container)
2. For each row in the scenario data, parse its container IDs
3. Build group keys from both sides using normalized types (int for week, `''` for NaN, matching SSL/Vessel)
4. Look up each container in the origin map to find its original carrier
5. Aggregate: how many came from each original carrier
6. Format: "No Flip" if nothing changed, otherwise show gains/losses with carrier names

## Known Pitfalls
- The origin map `context_cols` must include ALL columns used in group keys (SSL, Vessel were missing before and caused all flips to show as "Had 0")
- Week Number must be normalized to `int` on both sides (origin map stores as int, DataFrame may have float/Int64)
- NaN carrier values must be converted to `'Unknown'` to avoid NaN != NaN comparison failures
