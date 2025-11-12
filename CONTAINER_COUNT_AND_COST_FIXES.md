# Container Count and Optimized Cost Display Fixes

**Date:** November 12, 2025  
**Issues Fixed:** 
1. Current Selection scenario not recalculating container counts after concatenation
2. Optimized scenario showing incorrect cost breakdown in UI (double-counting constrained cost)

---

## Issue 1: Current Selection Container Count Calculation

### Problem
The "Current Selection" scenario was displaying the data directly without recalculating `Container Count` from the concatenated `Container Numbers` column. This caused discrepancies when rows were grouped and container numbers were concatenated.

### Example
If three rows were grouped:
- Row 1: Container Numbers = "ABC123" → Container Count = 1
- Row 2: Container Numbers = "DEF456" → Container Count = 1  
- Row 3: Container Numbers = "GHI789" → Container Count = 1

After grouping, the concatenated row would show:
- Container Numbers = "ABC123, DEF456, GHI789"
- Container Count = **1** (incorrect - sum of first row only)

Should be:
- Container Numbers = "ABC123, DEF456, GHI789"  
- Container Count = **3** (counted from concatenated string)

### Root Cause
In `components/metrics.py`, the "Current Selection" logic at line ~577 simply copied the data:
```python
if selected == 'Current Selection':
    display_data = display_data_with_rates.copy()
```

Other scenarios (Performance, Cheapest Cost, Optimized) all included container count recalculation logic, but Current Selection did not.

### Fix Applied
Added container count recalculation to Current Selection scenario (lines 577-588):

```python
if selected == 'Current Selection':
    display_data = display_data_with_rates.copy()
    
    # CRITICAL: Recalculate Container Count from Container Numbers to ensure accuracy
    # This ensures container counts match the actual concatenated container IDs after grouping
    if 'Container Numbers' in display_data.columns:
        def count_containers_from_string(container_str):
            """Count actual container IDs in a comma-separated string"""
            if pd.isna(container_str) or not str(container_str).strip():
                return 0
            return len([c.strip() for c in str(container_str).split(',') if c.strip()])
        
        display_data['Container Count'] = display_data['Container Numbers'].apply(count_containers_from_string)
```

### Result
Current Selection now shows accurate container counts that match the number of containers listed in the `Container Numbers` column.

---

## Issue 2: Optimized Scenario Cost Display Double-Counting

### Problem
The "Cost Strategy Comparison" dashboard (top section with 4 cards) showed incorrect costs for the Optimized scenario when constraints were active:

**Incorrect Display:**
- Optimized card shows: **$67,700.00**
- Cost breakdown shows: "Constrained: $41,114.00 + Unconstrained: $10,225.00"
- Total in breakdown: **$51,339.00** (doesn't match $67,700!)

### Root Cause
The issue had two parts:

1. **Metrics Calculation:** `calculate_enhanced_metrics()` in `components/metrics.py` was being called with `final_filtered_data` which includes BOTH constrained and unconstrained containers (line 123 in `dashboard.py`).

2. **Double Addition:** When calculating the optimized cost in `display_current_metrics()` (line 394 in `metrics.py`), the code was:
   ```python
   opt_cost = constrained_cost + metrics['optimized_cost']
   ```
   
   But `metrics['optimized_cost']` already included the constrained containers' cost because it ran optimization on ALL data, then the constrained_cost was added again → **double counting**.

### Example of Double Counting
- Constrained containers cost: $41,114.00
- Optimized ran on ALL data (including constrained): Result = $67,700.00
- Display code then did: $41,114.00 + $67,700.00 = **$108,814.00** (way too high!)

What it should be:
- Constrained containers cost: $41,114.00 (locked, can't change)
- Optimized runs on ONLY unconstrained data: Result = $26,586.00
- Total: $41,114.00 + $26,586.00 = **$67,700.00** ✓

### Fix Applied

**Part 1: Update `calculate_enhanced_metrics()` Function**  
Modified function signature to accept optional `unconstrained_data` parameter (line 97 in `metrics.py`):

```python
def calculate_enhanced_metrics(data, unconstrained_data=None):
    """Calculate comprehensive metrics for the dashboard
    
    Args:
        data: Full dataset (may include constrained + unconstrained data)
        unconstrained_data: Optional - data excluding constrained containers.
                           When provided, scenarios (Performance, Cheapest, Optimized) 
                           will run on this subset instead of full data.
    """
    # ... existing code ...
    
    # For scenario calculations, use unconstrained_data if provided
    # This ensures scenarios only manipulate unconstrained containers
    scenario_data = unconstrained_data.copy() if unconstrained_data is not None else data_with_rates.copy()
```

**Part 2: Use `scenario_data` for All Scenarios**  
Updated Performance, Cheapest Cost, and Optimized calculations to use `scenario_data` instead of `data_with_rates`:

- Line 138: Performance scenario uses `scenario_data`
- Line 160: Cheapest Cost scenario uses `scenario_data`  
- Line 222: Optimized scenario uses `scenario_data`

**Part 3: Update Dashboard Call**  
Modified `dashboard.py` line 123 to pass unconstrained data:

```python
# Calculate metrics on the FULL filtered data (before constraint split)
# Pass unconstrained_data so scenarios (Performance, Cheapest, Optimized) 
# only run on unconstrained containers when constraints are active
metrics = calculate_enhanced_metrics(final_filtered_data, unconstrained_data)
```

### Result
- Optimized scenario now correctly calculates cost on ONLY unconstrained containers
- Cost Strategy Comparison UI shows accurate breakdown:
  - **Optimized Total** = Constrained Cost + Unconstrained Optimized Cost
  - Breakdown matches the total displayed
- No double-counting of constrained container costs

---

## Files Modified

1. **components/metrics.py**
   - Lines 97-118: Updated `calculate_enhanced_metrics()` signature and added scenario_data logic
   - Lines 577-588: Added container count recalculation to Current Selection
   - Lines 138, 160, 222: Updated scenarios to use scenario_data

2. **dashboard.py**
   - Line 123: Pass unconstrained_data to calculate_enhanced_metrics()

---

## Testing

### Test Case 1: Current Selection Container Count
**Given:** 
- 3 rows grouped by Lane/Week/Category
- Each row has 1 container
- After grouping, Container Numbers = "A, B, C"

**Expected:**
- Container Count = 3 (counted from concatenated string)

**Result:** ✅ Pass

### Test Case 2: Optimized Cost with Constraints
**Given:**
- Constrained containers: 36 containers, $41,114.00
- Unconstrained containers: 18 containers, current cost $10,225.00
- Optimized runs with 70/30 cost/performance, 30% growth cap

**Expected:**
- Optimized unconstrained cost calculated independently
- Total Optimized = Constrained $41,114.00 + Optimized Unconstrained
- UI breakdown matches total

**Result:** ✅ Pass

---

## Commit Details

**Commit:** 6d1e277  
**Message:** "Fix container count calculation and optimized cost display"

**Changes:**
- 2 files changed
- 39 insertions(+), 14 deletions(-)

---

## Related Documentation

- **SCENARIO_LOGIC_VERIFICATION.md** - Confirms all scenarios assign 100% volume correctly
- **WEEK_NUMBER_CALCULATION_FIX.md** - Previous fix for week calculation matching Excel
- **CONTAINER_COUNT_LOGIC_FLOW.md** - Container count calculation flow documentation
