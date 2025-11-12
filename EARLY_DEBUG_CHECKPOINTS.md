# Early Debug Checkpoints Added

## Problem Identified

User reported expecting **49 containers** for BAL Week 47, but DEBUG 8 showed only **24 containers** from the very first checkpoint. This means containers are being lost **before the merge** - either during:

1. Initial Excel load
2. Data processing in `load_gvt_data()`
3. Groupby aggregation in `merge_all_data()`

## New Debug Checkpoints Added

### In `components/data_loader.py`

#### DEBUG 1 (Enhanced): GVT Data Initial Load

**Location:** Right after `pd.read_excel(gvt_file)`
**Purpose:** Verify raw data from Excel before ANY processing

**Tracks:**

- Total rows loaded from Excel
- Available columns
- Total Week 47 rows (all ports)
- Unique Lanes in Week 47
- Rows with Lane starting with 'BAL'
- **Total Week 47 container IDs (all ports)**
- **BAL Week 47 rows**
- **BAL Week 47 total container IDs**
- **BAL Week 47 unique container IDs**
- First 10 BAL container IDs

**Critical:** This shows the EXACT number of containers in the Excel file before any filtering or processing.

#### DEBUG 2.5: Before Column Selection

**Location:** Just before `gvt_data = gvt_data[select_cols]`
**Purpose:** Verify no rows lost during data processing

**Tracks:**

- BAL Week 47 rows before column selection
- BAL Week 47 Container Count sum

#### DEBUG 2.6: After Column Selection

**Location:** Right after `gvt_data = gvt_data[select_cols]`
**Purpose:** Verify column selection doesn't drop rows

**Tracks:**

- BAL Week 47 rows after column selection
- BAL Week 47 Container Count sum
- Total rows after selection
- Sample data display

### In `components/data_processor.py`

#### DEBUG 7.5: Input to merge_all_data

**Location:** Beginning of `merge_all_data()` function
**Purpose:** Verify data passed from `load_gvt_data()` is correct

**Tracks:**

- Total GVTdata rows
- BAL Week 47 rows
- BAL Week 47 Container Count sum
- **BAL Week 47 actual container IDs in Container Numbers column**
- Sample input data

**Critical:** This shows if data is already wrong before merge operations.

#### DEBUG 7.6: Before groupby aggregation

**Location:** Just before `GVTdata.groupby(group_cols)`
**Purpose:** Establish baseline before critical aggregation

**Tracks:**

- Total rows before groupby
- Grouping columns being used
- Container column being aggregated

#### DEBUG 7.7: After groupby aggregation

**Location:** Right after `GVTdata.groupby(group_cols).agg(agg_dict)`
**Purpose:** **CRITICAL CHECKPOINT** - Groupby can aggregate multiple rows into one

**Tracks:**

- Total rows after groupby
- BAL Week 47 rows after groupby
- **BAL Week 47 container IDs after groupby (from aggregated Container Numbers)**
- Sample aggregated data

**What to Look For:**

- If container IDs drop here, it means multiple Excel rows are being combined into single grouped rows
- The groupby uses: `['Week Number', 'Discharged Port', 'Dray SCAC(FL)', 'Facility', 'Lane', 'Lookup']`
- If you have duplicate combinations of these columns, they'll be grouped together

#### DEBUG 7.8: After rate merge

**Location:** After `pd.merge(lane_count, Ratedata, how='left', on='Lookup')`
**Purpose:** Verify merge with rate data doesn't drop rows

**Tracks:**

- Total rows after rate merge
- BAL Week 47 rows after rate merge
- BAL Week 47 container IDs after rate merge

## Expected Debug Flow

When you run the app and filter to BAL Week 47, you'll see:

```
🔍 DEBUG 1: GVT Data Initial Load (RAW from Excel)
- Total rows loaded from Excel: XXX
- Total Week 47 rows (all ports): XX
- Week 47 rows with Lane starting with 'BAL': XX
- BAL Week 47 total container IDs: 49 ← SHOULD BE 49 HERE
- BAL Week 47 unique container IDs: 49

🔍 DEBUG 2: After Container Count Calculation
- BAL Week 47 rows: XX
- BAL Week 47 total Container Count (sum): 49 ← SHOULD STILL BE 49

🔍 DEBUG 2.5: Before Column Selection
- BAL Week 47 rows before select: XX
- BAL Week 47 Container Count sum: 49 ← SHOULD STILL BE 49

🔍 DEBUG 2.6: After Column Selection
- BAL Week 47 rows after select: XX
- BAL Week 47 Container Count sum: 49 ← SHOULD STILL BE 49

🔍 DEBUG 3: GVT Data Final (Before Return)
- BAL Week 47 rows: XX
- BAL Week 47 total Container Count: 49 ← SHOULD STILL BE 49

🔍 DEBUG 7.5: Input to merge_all_data
- BAL Week 47 rows: XX
- BAL Week 47 Container Count sum: 49 ← SHOULD STILL BE 49
- BAL Week 47 actual container IDs in Container Numbers: 49 ← CRITICAL CHECK

🔍 DEBUG 7.6: Before groupby aggregation
- Total rows before groupby: XXX

🔍 DEBUG 7.7: After groupby aggregation
- BAL Week 47 rows after groupby: XX
- BAL Week 47 container IDs after groupby: ?? ← LIKELY WHERE CONTAINERS DROP

🔍 DEBUG 7.8: After rate merge
- BAL Week 47 rows after rate merge: XX
- BAL Week 47 container IDs after rate merge: ??

🔍 DEBUG 8: After merge_all_data
- BAL Week 47 rows: 12
- BAL Week 47 total Container Count: 24 ← YOU SEE 24 HERE
```

## Key Questions to Answer

1. **Does DEBUG 1 show 49 containers?**

   - YES → Excel file has all 49 containers
   - NO → Excel file doesn't have 49 containers (need to check source file)

2. **Do DEBUG 2-3 maintain 49 containers?**

   - YES → Data processing in `load_gvt_data()` is fine
   - NO → Problem in Container Count calculation or column selection

3. **Does DEBUG 7.5 show 49 containers?**

   - YES → Data passed correctly to merge function
   - NO → Data lost in `load_gvt_data()` return

4. **Does DEBUG 7.7 drop containers?**

   - **THIS IS THE MOST LIKELY CULPRIT**
   - If containers drop from 49 to 24 here, it means:
     - Multiple Excel rows with same grouping keys are being combined
     - The groupby is treating them as duplicates
     - Container Numbers are being concatenated but Container Count might not reflect all containers

5. **Does DEBUG 7.8 maintain container count?**
   - Should stay same as 7.7
   - If it drops, rate merge is excluding rows (shouldn't happen with `how='left'`)

## Most Likely Scenario

Based on the pattern (49 → 24), the most likely issue is:

**The Excel file has multiple rows per container group (e.g., same Week, Port, Carrier, Lane, Facility), and the groupby operation is aggregating them.**

For example:

- Excel might have 4 separate rows for SCAC "ABC" in BAL Week 47 Lane XYZ
- Each row has some containers
- Groupby combines them into 1 row
- Container Numbers get concatenated correctly: "C1, C2, C3, C4"
- But Container Count calculation might be using `.size()` which counts input ROWS (4) not actual containers

## How to Fix (If This Is the Issue)

After groupby, recalculate Container Count from the concatenated Container Numbers:

```python
def count_actual_containers(container_str):
    if pd.isna(container_str) or not str(container_str).strip():
        return 0
    return len([c.strip() for c in str(container_str).split(',') if c.strip()])

lane_count['Container Count'] = lane_count['Container Numbers'].apply(count_actual_containers)
```

This ensures Container Count matches the actual number of container IDs in the string.

## Files Modified

1. ✅ `components/data_loader.py` - Enhanced DEBUG 1, added DEBUG 2.5, 2.6
2. ✅ `components/data_processor.py` - Added DEBUG 7.5, 7.6, 7.7, 7.8

## Next Steps

1. **Run the application**
2. **Upload your Excel file**
3. **Filter to BAL Week 47**
4. **Read through ALL debug output from DEBUG 1 to DEBUG 8**
5. **Identify the exact checkpoint where containers drop from 49 to 24**
6. **Share the debug output** so we can pinpoint the exact cause

---

**Status:** Early debug checkpoints added
**Goal:** Find the exact location where 49 containers become 24 containers
**Expected Result:** Identify if problem is in Excel load, data processing, or groupby aggregation
