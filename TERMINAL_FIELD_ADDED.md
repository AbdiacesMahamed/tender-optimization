# Terminal Field Support Added

## Summary

Added Terminal field support throughout the application. Terminal data from GVT files now appears in data tables and can be used as a constraint filter.

## Changes Made

### 1. Data Processor (`components/data_processor.py`) - CRITICAL FIX

**Group Columns in merge_all_data() (Line ~138)**

- **Added Terminal to grouping columns** when it exists in GVT data
- This is THE critical change that ensures Terminal is preserved through data processing
- Terminal is inserted before 'Lookup' in the group_cols list
- Without this change, Terminal would be lost during the aggregation step

### 2. Optimization Modules - Terminal Support in All Scenarios

**Performance Logic (`optimization/performance_logic.py`)**

- Added Terminal to DEFAULT_GROUP_COLUMNS
- Ensures Terminal is preserved in performance-based allocation scenarios

**Cheapest Logic (`optimization/cheapest_logic.py` and `components/cheapest_logic.py`)**

- Added Terminal to DEFAULT_GROUP_COLUMNS in both files
- Maintains Terminal grouping in cost optimization scenarios

**Linear Programming (`optimization/linear_programming.py`)**

- Added Terminal to DEFAULT_GROUP_COLUMNS
- Terminal included in LP optimization grouping

**Cascading Logic (`optimization/cascading_logic.py`)**

- Added Terminal to dynamic group_columns building
- Terminal preserved in cascading allocation with growth constraints

**Historic Volume (`optimization/historic_volume.py`)**

- Added Terminal to group_columns and lane_group
- Terminal included in historical volume analysis and trending

### 3. Constraints Processor (`components/constraints_processor.py`)

**Column Mapping (Line ~136)**

- Added Terminal to column mapping: Maps "Terminal" column from constraints Excel file
- Terminal is normalized alongside other text fields

**Expected Columns (Line ~144)**

- Added 'Terminal' to expected_cols list
- Terminal is treated as optional constraint field (like Category, Lane, Port, Week Number)

**Text Field Cleanup (Line ~157)**

- Added Terminal to text cleanup loop
- Empty strings are converted to None for consistent handling

**Filter Application (Line ~379)**

- Added Terminal filter in `apply_constraints_to_data()` function
- Terminal filter is applied if specified in constraint row
- Logged in filters_applied description

**Updated Docstring**

- Documented Terminal as an optional constraint field

### 4. Metrics Display (`components/metrics.py`)

**Constrained Data Display (Line ~562)**

- Added Terminal column to constrained data table display
- Inserted after Facility, before Week Number
- Terminal only displayed if column exists in data

**Unconstrained Data Display (Line ~857)**

- Added Terminal column to unconstrained data table display
- Positioned between Facility and Week Number
- Conditional display based on column existence

**Performance Allocation Grouping (Line ~768)**

- Added Terminal to group_cols for performance scenario
- Terminal is now included in aggregation groups for performance-based reallocation

### 5. Summary Tables (`components/summary_tables.py`)

**Tab Navigation (Line ~29)**

- Added conditional Terminal tab when Terminal data exists
- Tab only appears if 'Terminal' column is present in data
- Icon: 🖥️ By Terminal

**New Function: `show_terminal_summary()` (Line ~113)**

- Aggregates data by Terminal
- Shows Container Count, Total Cost, Average Rate
- Includes Average Carrier Performance if available
- Gracefully handles missing Terminal data

## How to Use Terminal Constraints

### 1. Add Terminal Column to GVT Data

Ensure your GVT Excel file includes a "Terminal" column with terminal identifiers.

### 2. Add Terminal Column to Constraints File

In your constraints Excel file, add a "Terminal" column to filter constraints by terminal.

### 3. Example Constraint with Terminal

```
Priority Score: 1
Carrier: ATMI
Terminal: Terminal A
Maximum Container Count: 100
```

This constraint assigns 100 containers from "Terminal A" to ATMI.

### 4. Combined Filters with Terminal

```
Priority Score: 2
Carrier: RTSC
Category: Import
Lane: LAX-CHI
Terminal: Terminal B
Percent Allocation: 30%
```

This allocates 30% of Import containers on LAX-CHI lane at Terminal B to RTSC.

## Terminal in Data Tables

### Constrained Data Table

Terminal appears between Facility and Week Number columns:

- Discharged Port | Category | Carrier | Lane | Facility | **Terminal** | Week Number | Container Numbers | ...

### Unconstrained Data Table

Same column ordering as constrained data:

- Discharged Port | Category | Carrier | Lane | Facility | **Terminal** | Week Number | Container Numbers | ...

### Summary Tables

New "By Terminal" tab shows aggregated metrics:

- Container Count by Terminal
- Total Cost by Terminal
- Average Rate by Terminal
- Average Carrier Performance by Terminal (if available)

## Compatibility Notes

- **Backward Compatible**: If Terminal column doesn't exist in GVT data, tables display normally without Terminal column
- **Optional Field**: Terminal is optional in constraints file (like Category, Lane, Port)
- **No Breaking Changes**: Existing data files without Terminal column continue to work
- **Graceful Degradation**: Terminal tab only appears when Terminal data exists

## Testing Recommendations

1. **Test with Terminal data**: Upload GVT file with Terminal column, verify Terminal appears in tables
2. **Test without Terminal data**: Upload GVT file without Terminal column, verify no errors
3. **Test Terminal constraints**: Add Terminal filter to constraint, verify filtering works correctly
4. **Test combined filters**: Use Terminal with Category, Lane, Port, Week Number filters together
5. **Test Terminal summary**: Check "By Terminal" tab shows correct aggregations

## Technical Details

- Terminal is treated as a categorical filter (like Category, Lane, Port)
- Terminal filtering uses exact string matching
- Terminal is included in performance allocation grouping
- Terminal appears consistently across all table displays
- No special normalization applied to Terminal (unlike Facility codes)
