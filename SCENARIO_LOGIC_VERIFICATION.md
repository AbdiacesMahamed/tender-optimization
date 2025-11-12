# Scenario Logic Verification

## Summary

Both Performance and Cheapest Cost scenarios correctly assign **100% of container volume** to the best carrier for each lane/category/week combination.

## Performance Scenario

**Location**: `optimization/performance_logic.py` → `allocate_to_highest_performance()`

**Logic**:

1. **Group by**: Category, Week Number, Lane, Discharged Port, Facility
2. **Sort by** (descending):
   - Performance_Score (highest first)
   - Then Total Rate/CPC (lowest - tie breaker)
   - Then Carrier name (alphabetical - tie breaker)
3. **Select**: First carrier per group = highest performance carrier
4. **Allocate**: Sum ALL containers in the group → assign 100% to selected carrier

**Code Reference** (lines 109-124):

```python
# Get the best carrier per group (highest performance)
best_carriers = working.groupby(group_cols).head(1).copy()

# Sum all containers in each group
container_totals = (
    working
    .groupby(group_cols)[container_column]
    .sum()
    .rename(columns={container_column: "__total_containers"})
)

# Assign 100% to the best carrier
best_carriers = best_carriers.merge(container_totals, on=group_cols, how="left")
best_carriers[container_column] = best_carriers["__total_containers"].fillna(0)
```

**Result**: ✅ Highest performance carrier gets 100% of volume

---

## Cheapest Cost Scenario

**Location**: `components/metrics.py` → `show_detailed_analysis_table()`

**Logic**:

1. **Group by**: Category, Week Number, Lane, Discharged Port, Facility
2. **Sort by** (ascending):
   - Base Rate or CPC (lowest first)
   - Then Carrier name (alphabetical - tie breaker)
3. **Select**: First carrier per group = cheapest carrier
4. **Allocate**: Sum ALL containers in the group → assign 100% to selected carrier

**Code Reference** (lines 981-1026):

```python
# Sort by rate (cheapest first)
working['_rate_sort'] = working[rate_cols['rate']].fillna(float('inf'))
working['_carrier_sort'] = working[carrier_col].astype(str)
working = working.sort_values(['_rate_sort', '_carrier_sort'], ascending=[True, True])

# Get the first (cheapest) carrier for each group
cheapest_per_group = working.groupby(group_cols, as_index=False).first()

# Sum all containers in each group
container_totals = (
    working.groupby(group_cols)['Container Count']
    .sum()
    .rename(columns={'Container Count': '_total_containers'})
)

# Assign 100% to the cheapest carrier
cheapest_per_group = cheapest_per_group.merge(container_totals, on=group_cols, how='left')
cheapest_per_group['Container Count'] = cheapest_per_group['_total_containers'].fillna(0)
```

**Result**: ✅ Cheapest carrier gets 100% of volume

---

## Example

### Input Data:

| Lane       | Category | Week | Carrier | Containers | Performance | Rate |
| ---------- | -------- | ---- | ------- | ---------- | ----------- | ---- |
| USBAL-HIA1 | FBA FCL  | 47   | ARVY    | 5          | 0.85        | $500 |
| USBAL-HIA1 | FBA FCL  | 47   | FRQT    | 3          | 0.90        | $600 |
| USBAL-HIA1 | FBA FCL  | 47   | HDDR    | 2          | 0.75        | $450 |

**Total Containers in Group**: 5 + 3 + 2 = **10 containers**

### Performance Scenario Output:

| Lane       | Category | Week | Carrier  | Containers | Performance | Rate |
| ---------- | -------- | ---- | -------- | ---------- | ----------- | ---- |
| USBAL-HIA1 | FBA FCL  | 47   | **FRQT** | **10**     | 0.90        | $600 |

**Result**: FRQT (highest performance 0.90) gets ALL 10 containers

### Cheapest Cost Scenario Output:

| Lane       | Category | Week | Carrier  | Containers | Performance | Rate |
| ---------- | -------- | ---- | -------- | ---------- | ----------- | ---- |
| USBAL-HIA1 | FBA FCL  | 47   | **HDDR** | **10**     | 0.75        | $450 |

**Result**: HDDR (cheapest rate $450) gets ALL 10 containers

---

## Verification Status

- ✅ **Performance Scenario**: Assigns 100% volume to highest performance carrier per lane/category/week
- ✅ **Cheapest Cost Scenario**: Assigns 100% volume to lowest cost carrier per lane/category/week
- ✅ **Grouping**: Both use same grouping logic (Category, Week Number, Lane, Port, Facility)
- ✅ **Tie-Breaking**: Both have proper tie-breaking logic for deterministic results

## Date

November 12, 2025
