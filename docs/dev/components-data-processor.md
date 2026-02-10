# components/data_processor.py

## Purpose
Validates, transforms, and merges the three data sources (GVT, Rate, Performance) into a single comprehensive DataFrame that powers the entire dashboard. This is the core data pipeline module.

## Key Functions

### `validate_and_process_gvt_data(GVTdata) -> DataFrame`
- Parses `Ocean ETA` to datetime
- Calculates `Week Number` from `Ocean ETA` (or uses existing `WK num` column)
- Drops rows with null `Ocean ETA`
- Creates derived columns: `Discharged Port`, `Port_Processed`, `Facility_Processed`, `Lookup`, `Lane`

### `validate_and_process_rate_data(Ratedata) -> DataFrame`
- Validates rate data has required columns (`Lookup`, `Base Rate`)
- Cleans and normalizes rate values

### `merge_all_data(GVTdata, Ratedata, performance_clean, has_performance) -> DataFrame`
**This is the most critical function in the pipeline.** It:
1. Groups GVT data by `group_cols` (Week, Port, Carrier, Facility, Lane, Lookup + optional Category/SSL/Vessel/Terminal)
2. Aggregates `Container Numbers` (concatenate + deduplicate within each group)
3. Calculates `Container Count` from the aggregated container string
4. Merges with Rate data on `Lookup` key
5. Merges with Performance data on normalized carrier name + Week Number
6. Applies volume-weighted performance scores
7. Marks rows with missing rates (`Missing_Rate` flag)
8. Calculates `Total Rate = Base Rate × Container Count`

**When adding new columns from GVT**: Add them to the `agg_dict` with an appropriate aggregation function (usually `'first'`).

### `apply_volume_weighted_performance(merged_data) -> DataFrame`
Calculates volume-weighted performance scores per carrier across all their lanes/weeks.

### `create_comprehensive_data(merged_data) -> DataFrame`
Currently a passthrough — returns `merged_data` unchanged. Exists as an extension point.

## Group Columns
The standard grouping used throughout the pipeline:
```python
['Week Number', 'Discharged Port', 'Dray SCAC(FL)', 'Facility', 'Lane', 'Lookup']
# + optional: 'Category', 'SSL', 'Vessel', 'Terminal'
```

## Data Flow
```
validate_and_process_gvt_data(GVT) ──┐
validate_and_process_rate_data(Rate) ─┤
process_performance_data(Perf) ───────┘
                                      ↓
                              merge_all_data()
                                      ↓
                           comprehensive DataFrame
```
