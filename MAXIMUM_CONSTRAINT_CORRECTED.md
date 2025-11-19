# Maximum Container Constraint Logic - CORRECTED Implementation

## Overview

This document explains how Maximum Container Count constraints work to ensure carriers with hard caps don't receive additional volume in optimization **while preserving container counts**.

## User Requirement

> "If a carrier has a maximum container volume, the result appears in the constrained table. Then I want no volume to be allocated to that carrier in the unconstrained table. The optimization should still work with the same volume but move the volume as if that carrier doesn't exist in the unconstrained table."

## Key Insight: Container Preservation

The critical requirement is that **containers remain in the unconstrained table**. The carrier is blocked from receiving them in optimization, but the containers themselves are NOT deleted. This allows other carriers to use that volume.

## Implementation

### Step 1: Constraint Definition

When a constraint is uploaded with:

- **Carrier**: ABC (REQUIRED)
- **Maximum Container Count**: 100 (REQUIRED)
- **Category, Lane, Port, Week**: OPTIONAL filters

### Step 2: Allocation to Constrained Table

1. Filter data by optional criteria (Category, Lane, Port, Week)
2. From filtered data, allocate up to maximum containers
3. Re-assign these containers to target carrier ABC
4. Add to **constrained table** with:
   - `Dray SCAC(FL)` = ABC
   - `Carrier` = ABC
   - All other attributes preserved
   - Container Numbers and Container Count tracked

### Step 3: Update Unconstrained Table

**Only remove the allocated containers:**

- Allocated containers removed from their original rows
- If row fully allocated: Set `Container Count = 0`
- If partially allocated: Update `Container Numbers` to remove allocated IDs
- **NO OTHER CONTAINERS ARE REMOVED**

### Step 4: Add Carrier to Exclusion List

- Add carrier to `max_constrained_carriers` set
- This set is passed to optimization functions
- Optimization logic excludes this carrier completely
- Carrier cannot receive ANY containers, but containers remain available

### Step 5: Optimization Exclusion

In the cascading allocation logic:

```python
# Separate excluded carrier data from allocatable data
if excluded_carriers:
    excluded_mask = data[carrier_column].isin(excluded_carriers)
    excluded_data = data[excluded_mask].copy()
    data = data[~excluded_mask].copy()  # Carrier removed from optimization
```

Result:

- Rows with excluded carrier are filtered out during optimization
- These rows' containers are treated as "available volume"
- Other carriers can be assigned to handle this volume
- Total container count preserved

## Complete Example

### Input Data

```
Row 1: Category=Import, Lane=LAX-CHI, Carrier=ABC, Containers=150
Row 2: Category=Import, Lane=LAX-CHI, Carrier=XYZ, Containers=100
Row 3: Category=Export, Lane=LAX-CHI, Carrier=ABC, Containers=50
Total: 300 containers
```

### Constraint Applied

```
Carrier=ABC, Maximum=100, (no filters - applies to all)
```

### Step-by-Step Processing

#### After Allocation to Constrained:

- **Constrained Table**: 100 containers, Carrier=ABC
- **Unconstrained Table**: 200 containers
  - Row 1: Carrier=ABC, Containers=50 (150 - 100 allocated)
  - Row 2: Carrier=XYZ, Containers=100 (unchanged)
  - Row 3: Carrier=ABC, Containers=50 (unchanged)

#### After Adding to Exclusion List:

- `max_constrained_carriers = {'ABC'}`
- Unconstrained table unchanged (containers still there)

#### During Optimization:

```python
# Optimization filters out ABC
excluded_mask = data['Carrier'] == 'ABC'
data = data[~excluded_mask]

# Optimization sees:
Row 2: Carrier=XYZ, Containers=100

# ABC's 100 containers (50+50) are available as "unassigned volume"
# Optimization can assign them to XYZ or other carriers
```

### Final Result

- **Constrained**: 100 containers (ABC locked)
- **Unconstrained**: 200 containers total
  - XYZ can be assigned to handle all 200 containers
  - Or split between available carriers
- **Container Count**: 100 + 200 = 300 ✅ PRESERVED

## Key Differences from Previous Approach

### ❌ Old (Incorrect) Approach:

1. Allocate maximum to constrained table
2. **DELETE all remaining carrier rows from unconstrained table**
3. Result: Container count NOT preserved (lost containers)

### ✅ New (Correct) Approach:

1. Allocate maximum to constrained table
2. **Keep all rows in unconstrained table**
3. Add carrier to exclusion list
4. Optimization filters out excluded carrier
5. Result: Container count PRESERVED, carrier blocked

## Container Count Math

### Scenario: Original 300 containers

- ABC: 200 containers
- XYZ: 100 containers

### Constraint: ABC Maximum=50

#### After Processing:

**Constrained Table:**

- ABC: 50 containers

**Unconstrained Table:**

- ABC: 150 containers (200 - 50)
- XYZ: 100 containers
- Total: 250 containers

**Verification:**

- Constrained: 50
- Unconstrained: 250
- Total: 50 + 250 = 300 ✅

#### During Optimization:

- ABC excluded from consideration
- 150 ABC containers + 100 XYZ containers = 250 available
- Optimization assigns to XYZ (or other non-excluded carriers)
- ABC cannot receive any of these containers

## Why This Works

1. **Container Preservation**: No containers deleted, count stays correct
2. **Carrier Blocking**: Exclusion list ensures carrier can't get volume
3. **Volume Flexibility**: Other carriers can handle the excluded carrier's volume
4. **Clean Separation**: Constrained vs unconstrained clear and accurate
5. **Optimization Ready**: Standard exclusion mechanism already implemented

## Benefits

1. ✅ **Container Count Preserved**: Original = Constrained + Unconstrained
2. ✅ **Carrier Effectively Blocked**: Cannot receive containers in optimization
3. ✅ **Volume Available**: Other carriers can use the excluded carrier's volume
4. ✅ **Simple Logic**: Relies on existing exclusion mechanism
5. ✅ **No Data Loss**: All containers accounted for
6. ✅ **Flexible Filters**: Works with or without Category/Lane/Port/Week filters

## Validation

### Test Case 1: No Filters

```
Input: 49 containers total, ABC has 44
Constraint: Carrier=ABC, Maximum=5

Expected Output:
- Constrained: 5 containers (ABC)
- Unconstrained: 44 containers (5 allocated + 39 remaining = 44)
- Total: 5 + 44 = 49 ✅
- ABC excluded from optimization
```

### Test Case 2: With Filters

```
Input: 100 containers (Import=60 ABC + 40 XYZ, Export=0)
Constraint: Carrier=ABC, Category=Import, Maximum=30

Expected Output:
- Constrained: 30 containers (ABC, Import)
- Unconstrained: 70 containers
  - Import ABC: 30 (60 - 30 allocated)
  - Import XYZ: 40
- Total: 30 + 70 = 100 ✅
- ABC excluded from Import in optimization
```

## Implementation Code

### Key Change

```python
# OLD (WRONG): Removed carrier rows
if is_maximum_constraint and target_carrier:
    # Delete rows for target carrier
    for idx in carrier_rows:
        remaining_data.loc[idx, 'Container Count'] = 0  # ❌ DELETES CONTAINERS

# NEW (CORRECT): Just add to exclusion list
if is_maximum_constraint and target_carrier:
    max_constrained_carriers.add(target_carrier)  # ✅ BLOCKS CARRIER, KEEPS CONTAINERS
    st.write(f"🔒 {target_carrier} excluded from optimization")
    st.write(f"ℹ️ Containers remain available for other carriers")
```

### Result

- No container deletion in constraints processor
- Clean exclusion in optimization
- Container count preserved throughout

## Summary

The corrected implementation:

1. ✅ Allocates maximum to constrained table
2. ✅ Removes only allocated containers from unconstrained
3. ✅ Adds carrier to exclusion list (NO container deletion)
4. ✅ Optimization excludes carrier, uses volume for others
5. ✅ Container count: Original = Constrained + Unconstrained

**This matches the user's exact requirement**: Carrier blocked from receiving containers, but containers remain available for other carriers to use in optimization.
