# Historical Allocation Percentage Verification

## Purpose
Verify that historical allocation percentages sum to 100% for each lane+category group, and ensure that the cascading/optimization logic does not affect the calculation of historical percentages.

## How Historical % is Calculated

### Step 1: Filter to Historical Weeks Only
```python
historical_data = get_last_n_weeks(data, n_weeks=5, week_column=week_column)
```
- Gets ONLY the last 5 completed weeks
- Excludes current and future weeks
- This ensures optimization logic doesn't affect historical calculations

### Step 2: Group by Carrier + Lane + Category
```python
carrier_volume = historical_data.groupby([carrier_column, category_column, lane_column]).agg({
    container_column: 'sum',
    week_column: 'nunique'
}).reset_index()
```
- Sums containers per carrier for each lane+category
- Counts how many weeks the carrier was active

### Step 3: Calculate Lane Totals
```python
lane_totals = historical_data.groupby([category_column, lane_column])[container_column].sum()
```
- Sums total containers per lane+category across ALL carriers

### Step 4: Calculate Percentage
```python
Volume_Share_Pct = (carrier_total / lane_total) × 100
```

## Mathematical Guarantee

For each lane+category group:
- Sum of all carrier_totals = lane_total (by definition)
- Therefore: Sum of all (carrier_total / lane_total × 100) = 100%

The percentages MUST sum to 100% for each group, provided:
1. ✅ All carriers in the group are included in the result
2. ✅ No data filtering happens after the calculation
3. ✅ Rounding doesn't cause significant drift

## Potential Issues

### Issue 1: Missing Carriers in Display
**Problem**: If only carriers with current allocations are shown, and some carriers had historical volume but no current allocation, their historical % won't appear in the table.

**Solution**: The cascading logic only shows carriers that receive allocation in the current scenario. Historical carriers with no current allocation are not displayed. This is correct behavior - we only show historical % for carriers being considered.

**Impact**: Displayed historical % values may not sum to 100% if carriers are filtered out.

### Issue 2: Rounding
**Problem**: `Volume_Share_Pct` is rounded to 2 decimal places, which could cause sum to be 99.99% or 100.01%.

**Current Code**:
```python
result['Volume_Share_Pct'] = result['Volume_Share_Pct'].round(2)
```

**Impact**: Minimal - rounding error typically < 0.1%

### Issue 3: Container Count Recalculation Timing
**Problem**: If Container Count is recalculated AFTER historical % is calculated, the displayed Container Count might not match the count used for historical %.

**Current Flow**:
1. Data loaded → Container Count calculated from Container Numbers
2. Historical % calculated using Container Count
3. Cascading logic runs → redistributes Container Numbers
4. Container Count recalculated from redistributed Container Numbers
5. New % calculated from new Container Count

**Status**: ✅ CORRECT - Historical % uses original Container Count before cascading logic runs

## Verification Checklist

To verify historical % is correct:

1. ✅ Historical % calculation uses `get_last_n_weeks()` to filter to historical data only
2. ✅ Calculation happens BEFORE cascading logic modifies Container Numbers
3. ✅ Formula is mathematically sound: carrier_total / lane_total × 100
4. ✅ Cascading logic creates new result rows, doesn't modify input data
5. ⚠️ Only carriers with current allocation are shown (may not sum to 100% in display)

## Expected Behavior

### For Each Lane + Category Group:

**Scenario A: All Historical Carriers Have Current Allocation**
- Historical % values SHOULD sum to ~100% (within rounding)
- Each carrier's historical % = their share of last 5 weeks' volume

**Scenario B: Some Historical Carriers Have No Current Allocation**
- Displayed historical % values WILL NOT sum to 100%
- This is correct - we only show carriers being allocated
- Missing carriers' historical % simply aren't displayed

**Scenario C: New Carriers (No Historical Data)**
- Carrier shows Historical % = 0%
- This is correct - carrier had no volume in last 5 weeks

## Date
November 10, 2025

## Related Files
- `optimization/historic_volume.py` - Historical calculation logic
- `optimization/cascading_logic.py` - Uses historical % for allocation constraints
