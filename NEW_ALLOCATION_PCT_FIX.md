# New Allocation Percentage Recalculation Fix

## Issue
The `New_Allocation_Pct` (displayed as "🆕 New %") was not being recalculated after Container Count was updated from Container Numbers. This caused the displayed percentage to be based on the cascading allocation logic's container count, which could differ from the actual container count after Container Numbers were proportionally distributed.

## Root Cause
In `optimization/cascading_logic.py`, the flow was:

1. **Cascading allocation determines** `allocated_count` for each carrier
2. **Calculate** `New_Allocation_Pct` = `allocated_count / total_containers * 100`
3. **Store** this percentage in the result row
4. **Later, recalculate Container Count** from Container Numbers (due to proportional distribution)
5. **Recalculate Total Cost** using new Container Count
6. ❌ **BUT: New_Allocation_Pct was NOT recalculated**

This meant the displayed percentage reflected the allocation logic's intended distribution, not the actual final container counts after proportional distribution of Container Numbers.

## Solution
Added recalculation of `New_Allocation_Pct` after Container Count is updated from Container Numbers:

```python
# CRITICAL: Recalculate New_Allocation_Pct using the NEW Container Count
# This ensures the percentage reflects the actual container count after recalculation
total_containers_actual = result[container_column].sum()
if total_containers_actual > 0 and 'New_Allocation_Pct' in result.columns:
    result['New_Allocation_Pct'] = (result[container_column] / total_containers_actual * 100).fillna(0)
```

## Impact
- **New %** now accurately reflects the actual container count each carrier received
- Percentages now match the actual Container Count values in the table
- Historical % remains unchanged (correctly calculated from last 5 weeks of historical data)

## Historical % Calculation
The `Historical_Allocation_Pct` (displayed as "📊 Historical %") is calculated correctly:

1. Gets last 5 completed weeks of historical data
2. For each carrier+lane+category combination:
   - Sums the container count across all weeks where they had volume (1-5 weeks)
   - Counts how many weeks they were active
3. Calculates percentage = (carrier total / lane total) × 100
4. This naturally handles carriers with less than 5 weeks of data

The formula: **Historical % = (Carrier's containers in last N weeks) / (Lane's total containers in last N weeks) × 100**

Where N = number of weeks the carrier was active (up to 5).

## Files Modified
- `optimization/cascading_logic.py` - Added New_Allocation_Pct recalculation after Container Count update

## Date Applied
November 10, 2025

## Testing
After this fix:
1. ✅ New % should match Container Count proportions
2. ✅ Historical % should reflect past 5 weeks (or fewer if carrier has less history)
3. ✅ Both percentages should add up correctly per group
4. ✅ Total Cost calculations remain accurate
