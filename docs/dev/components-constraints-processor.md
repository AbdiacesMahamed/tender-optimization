# components/constraints_processor.py

## Purpose
Processes uploaded constraint Excel files and applies them to the filtered data. Constraints lock specific carrier-lane-week allocations so they are excluded from scenario optimization.

## Key Functions

### `process_constraints_file(constraints_file) -> DataFrame | None`
Reads and validates the constraint Excel file. Expected columns vary by constraint type but typically include carrier, port, facility, week, and constraint parameters.

### `apply_constraints_to_data(data, constraints_df, rate_data) -> tuple`
The main constraint application function. Returns:
```python
(constrained_data, unconstrained_data, constraint_summary, max_constrained_carriers, carrier_facility_exclusions, explanation_logs)
```

- **constrained_data**: Rows locked by constraints (not modified by scenarios)
- **unconstrained_data**: Remaining rows available for optimization
- **max_constrained_carriers**: Set of carriers with hard cap constraints
- **carrier_facility_exclusions**: Dict mapping carriers to facility codes where they're excluded
- **explanation_logs**: Downloadable constraint explanation text

### `allocate_specific_containers(row, num_containers, allocated_tracker, target_carrier, week_num)`
Helper that allocates a specific number of containers from a row to a target carrier, tracking which containers have been allocated.

### `show_constraints_summary(constraint_summary, explanation_logs)`
Renders the constraint summary UI with priority, method, and description columns.

## Constraint Types
See `docs/CONSTRAINTS.md` for the full constraint specification.

## Data Flow
```
constraints_file → process_constraints_file() → constraints_df
                                                      ↓
filtered_data + constraints_df → apply_constraints_to_data()
                                                      ↓
                                    constrained_data + unconstrained_data
```
