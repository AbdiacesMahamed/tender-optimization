# Debug Guide: Container Count Troubleshooting

## Debug Features Added

I've added comprehensive debug statements to help identify where container count mismatches occur in your scenario tables.

## What the Debug Output Shows

### 1. **Input Data Validation** (Cheapest Cost Scenario)

When you select "Cheapest Cost", you'll now see:

```
🔍 DEBUG: Cheapest Cost Scenario - INPUT DATA
- Total rows in source data: X
- Total containers (sum): Y
- Sample of input data with Container Numbers
```

**Key Check:** The debug will compare `Container Count` vs the actual number of IDs in `Container Numbers` in the INPUT data.

- ✅ If they match: "Input data is consistent"
- ❌ If they don't match: "INPUT DATA HAS MISMATCHES!"

**This tells you:** If the problem is in your input data (before scenarios run) or if it's caused by the scenario logic.

### 2. **Before Grouping** (Cheapest Cost)

Shows the data BEFORE aggregation happens:

```
🔍 DEBUG: Cheapest Cost Scenario - BEFORE Grouping
- Displays first 10 rows showing:
  - Carrier
  - Lane
  - Week Number
  - Container Count
  - Container Numbers
```

**This tells you:** What each individual row looks like before they get grouped together.

### 3. **After Concatenation** (Cheapest Cost)

Shows the data AFTER grouping and concatenating container numbers:

```
🔍 DEBUG: After Concatenation - Sample Rows
- Shows the concatenated Container Numbers
- Shows "Counted IDs" - the actual count from the string
```

**This tells you:** How many container IDs are in the concatenated string after grouping.

### 4. **Container Count Comparison** (Cheapest Cost)

Shows a detailed comparison:

```
🔍 DEBUG: Container Count Comparison
- Displays ALL rows with:
  - Summed Count (from adding Container Count values)
  - Actual Count from IDs (from counting the concatenated string)
  - Container Numbers (the actual IDs)
```

**This tells you:**

- Which rows have mismatches
- What the old (incorrect) count was
- What the new (correct) count is
- Shows detailed analysis of the first mismatch with manual comma count

### 5. **Performance Scenario Debug**

When you select "Performance", if there are mismatches:

```
⚠️ Performance Scenario - Container Count Mismatch Detected!
- Shows rows where summed count differs from actual IDs
```

## How to Use This Debug Information

### Step 1: Check Input Data

1. Select "Cheapest Cost" scenario
2. Look for the first debug section: **INPUT DATA**
3. Check if it says "INPUT DATA HAS MISMATCHES!"

**If YES:** The problem is in your source data. The Container Count column doesn't match the Container Numbers before any scenario logic runs.

- **Solution:** Check your data loading logic in `data_loader.py` or `data_processor.py`
- Check how Container Count is initially calculated

**If NO (data is consistent):** The problem happens during scenario aggregation. Continue to next steps.

### Step 2: Examine Grouping Logic

1. Look at "BEFORE Grouping" section
2. Verify each row has correct Container Count vs Container Numbers
3. Look at "After Concatenation" section
4. Check if the "Counted IDs" column shows the correct count

### Step 3: Review Comparison Table

1. Look at the "Container Count Comparison" table
2. This shows ALL rows after grouping
3. Identify which rows have mismatches
4. Check the "Detailed Analysis of First Mismatch" for the first problematic row

### Step 4: Understand the Root Cause

The debug output will help you identify:

**Problem A: Input Data Issue**

- Mismatch appears in INPUT DATA check
- Fix: Correct the initial data loading/processing

**Problem B: Grouping Logic Issue**

- Input data is fine, but after grouping there are mismatches
- The "Summed Count" doesn't equal "Actual Count from IDs"
- This happens when Container Numbers are concatenated but Container Count is summed separately

**Problem C: Duplicate Containers**

- If you see the same container ID appearing multiple times in different rows before grouping
- When concatenated, they appear once per source row
- But Container Count adds them all up

## Expected Behavior After Fix

With the fix applied, you should see:

- ✅ "All Container Counts Match!" message
- Container Count = number of comma-separated values in Container Numbers
- Correct cost calculations based on actual container counts

## Example Debug Output

### Good Scenario (No Issues):

```
✅ Input data is consistent: All 500 rows have matching Container Count and Container Numbers
✅ All Container Counts Match! All 150 rows have correct counts.
```

### Problem Detected:

```
❌ INPUT DATA HAS MISMATCHES! 25 rows where Container Count != number of IDs in Container Numbers
This means the problem starts in the input data, not in the scenario logic!
```

Or:

```
✅ Input data is consistent: All 500 rows have matching Container Count and Container Numbers
❌ Container Count Mismatch Detected!
Found 15 rows where summed count didn't match actual container list
```

## Files Modified for Debug

1. **`components/metrics.py`** - Cheapest Cost scenario debugging
2. **`optimization/performance_logic.py`** - Performance scenario debugging

## Disable Debug Output

To remove the debug statements once you've identified the issue, look for sections starting with:

- `st.write("🔍 **DEBUG:`
- `st.error(f"❌ **`
- `st.success(f"✅`

Comment them out or remove them.

## Date Added

November 10, 2025
