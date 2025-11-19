# Maximum Container Constraint Logic - Complete Flow

## Overview

This document explains how Maximum Container Count constraints work to ensure carriers with hard caps don't receive additional volume in optimization.

## User Requirement

> "If a carrier has a maximum container volume, the result appears in the constrained table. Then I want no volume to be allocated to that carrier in the unconstrained table. The optimization should still work with the same volume but move the volume as if that carrier doesn't exist in the unconstrained table."

## Implementation

### Step 1: Constraint Definition

When a constraint is uploaded with:

- **Carrier**: ABC (target carrier)
- **Category**: Import (filter)
- **Lane**: LAX-CHI (filter)
- **Maximum Container Count**: 100

### Step 2: Filter Application

The system filters the data by:

- Category = Import
- Lane = LAX-CHI
- Port (if specified)
- Week Number (if specified)

**IMPORTANT**: The Carrier field is NOT a filter - it's the TARGET carrier to assign containers TO.

### Step 3: Allocation to Constrained Table

1. From the filtered data, allocate 100 containers
2. Re-assign these containers to Carrier ABC (regardless of their original carrier)
3. Add these containers to the **constrained table** with:
   - `Dray SCAC(FL)` = ABC
   - `Carrier` = ABC
   - All other attributes (Lane, Category, Port, Week, etc.) preserved
   - Container Numbers and Container Count tracked precisely

### Step 4: Removal from Unconstrained Table (THREE-PHASE APPROACH)

#### Phase 1: Remove Allocated Containers

- All 100 allocated containers are removed from their original rows in `remaining_data`
- If a row is fully allocated, set `Container Count = 0` and `Container Numbers = ''`
- If partially allocated, update `Container Numbers` to remove allocated IDs

#### Phase 2: Remove Remaining Eligible Containers

For Maximum constraints, after allocating the specified amount:

- Continue processing remaining rows in `eligible_data` (rows matching the filter)
- Mark these containers for removal even though they weren't allocated
- This ensures ALL containers matching the filter are processed
- Set `Container Count = 0` and `Container Numbers = ''` for these rows

#### Phase 3: Remove Carrier-Specific Rows (CRITICAL FOR MAXIMUM CONSTRAINTS)

This is the **key step** that prevents the carrier from getting more volume:

```python
# Find ALL rows that match BOTH:
# 1. The constraint filter (Category/Lane/Port/Week)
# 2. Are currently assigned to the target carrier

carrier_mask = (remaining_data['Dray SCAC(FL)'] == 'ABC') | (remaining_data['Carrier'] == 'ABC')
rows_to_remove_mask = mask & carrier_mask

# Remove these rows from unconstrained table
for idx in rows_to_remove_indices:
    remaining_data.loc[idx, 'Container Count'] = 0
    remaining_data.loc[idx, 'Container Numbers'] = ''
```

This ensures that:

- Any containers for Carrier ABC in the Import/LAX-CHI segment are removed
- Carrier ABC will NOT appear in the unconstrained table for this segment
- Optimization cannot assign additional volume to ABC for this segment

### Step 5: Optimization Exclusion

The carrier is added to `max_constrained_carriers` set, which is passed to:

1. `calculate_enhanced_metrics()` - for calculating optimized scenarios
2. `cascading_allocate_with_constraints()` - for cascading allocation logic

In the optimization:

```python
excluded_carriers=max_constrained_carriers
```

The cascading logic filters out these carriers:

```python
# Separate excluded carrier data from allocatable data
if excluded_carriers:
    excluded_mask = data[carrier_column].isin(excluded_carriers)
    excluded_data = data[excluded_mask].copy()
    data = data[~excluded_mask].copy()
```

## Complete Example

### Input Data

```
Row 1: Category=Import, Lane=LAX-CHI, Carrier=XYZ, Container Count=150
Row 2: Category=Import, Lane=LAX-CHI, Carrier=ABC, Container Count=80
Row 3: Category=Import, Lane=LAX-CHI, Carrier=DEF, Container Count=70
Row 4: Category=Import, Lane=NY-BOS, Carrier=ABC, Container Count=50
```

### Constraint Applied

```
Carrier=ABC, Category=Import, Lane=LAX-CHI, Maximum Container Count=100
```

### Processing Steps

1. **Filter by Category=Import, Lane=LAX-CHI**

   - Eligible: Rows 1, 2, 3 (300 containers total)
   - Not eligible: Row 4 (different lane)

2. **Allocate 100 containers to ABC**

   - Take containers from Rows 1, 2, 3 (whichever are available, in order)
   - Create new constrained records with Carrier=ABC
   - Example: 100 containers from Row 1 (XYZ) are re-assigned to ABC

3. **Phase 1: Remove allocated containers**

   - Row 1: Update from 150 to 50 containers (100 removed)

4. **Phase 2: Remove remaining eligible containers**

   - If any containers remain in eligible_data after allocation (Rows 2, 3 in this case)
   - Mark them for removal: Set Container Count = 0

5. **Phase 3: Remove carrier-specific rows**
   - Find rows matching filter AND assigned to ABC
   - Row 2 matches (Import, LAX-CHI, ABC)
   - Remove Row 2 from unconstrained table
   - Row 4 stays (different lane, not affected by this constraint)

### Final Result

**Constrained Table:**

```
Category=Import, Lane=LAX-CHI, Carrier=ABC, Container Count=100
```

**Unconstrained Table:**

```
Row 1: Category=Import, Lane=LAX-CHI, Carrier=XYZ, Container Count=50 (reduced from 150)
Row 3: Category=Import, Lane=LAX-CHI, Carrier=DEF, Container Count=70 (unchanged)
Row 4: Category=Import, Lane=NY-BOS, Carrier=ABC, Container Count=50 (unchanged - different lane)
```

**Key Points:**

- Carrier ABC has 100 containers in constrained table for Import/LAX-CHI segment ✅
- Carrier ABC has 0 containers in unconstrained table for Import/LAX-CHI segment ✅
- Carrier ABC still has 50 containers for Import/NY-BOS (different lane) ✅
- Optimization will work with XYZ (50) and DEF (70) for Import/LAX-CHI ✅
- Total containers preserved: 100 (constrained) + 50 + 70 + 50 = 270 ✅

## Compatibility with Other Constraints

The maximum constraint logic works seamlessly with:

### 1. **Minimum Container Count**

- Applied with same filter logic but without removal phases 2 & 3
- Carrier can still receive additional volume in optimization

### 2. **Percent Allocation**

- Applied with same filter logic but without removal phases 2 & 3
- Carrier can still receive additional volume in optimization

### 3. **Multiple Constraints on Same Carrier**

- Example: Max on Import/LAX-CHI, Min on Export/CHI-LAX
- Each constraint processes independently
- Different filters = different segments affected
- Carrier blocked only for segments with Maximum constraints

### 4. **Combined Constraints**

- Example: Carrier ABC has Max=100 on Import/LAX-CHI + Min=50 on Export/SF-LA
- Import/LAX-CHI: ABC removed from unconstrained table
- Export/SF-LA: ABC gets minimum 50 in constrained, can get more in optimization

## Priority Handling

When multiple constraints affect the same data:

1. Constraints sorted by Priority Score (higher = first)
2. Each constraint processes in order
3. Containers tracked individually by Container ID
4. Already-allocated containers skipped in subsequent constraints
5. Maximum constraints always remove carrier from unconstrained for that segment

## Validation

The system validates:

1. **Container Count Consistency**: Original = Constrained + Unconstrained
2. **Container ID Tracking**: Each container ID appears exactly once
3. **Carrier Removal Logging**: Shows how many rows/containers removed
4. **Summary Display**: Shows carriers with hard caps

## Benefits

1. **Precise Control**: Carrier volumes capped exactly at specified maximum
2. **Optimization Integrity**: Optimization works with available carriers only
3. **Flexibility**: Different caps for different segments (Lane/Category/Week)
4. **Transparency**: Clear logging of what was removed and why
5. **Seamless Integration**: Works with all other constraint types

## Technical Implementation Details

### Key Data Structures

1. **`allocated_containers_tracker`**: Dict tracking each container ID

   ```python
   {
       'CONT12345': {
           'carrier': 'ABC',
           'week': 5,
           'row_idx': 42,
           'removed_due_to_max_constraint': True  # For phase 2 removals
       }
   }
   ```

2. **`max_constrained_carriers`**: Set of carriers with hard caps

   ```python
   {'ABC', 'XYZ'}  # Passed to optimization functions
   ```

3. **`rows_processed_for_removal`**: Set of row indices for phase 2
   ```python
   {15, 23, 47}  # Rows with remaining containers after max allocation
   ```

### Filter Mask Construction

```python
mask = pd.Series([True] * len(remaining_data))
if Category: mask &= (data['Category'] == Category)
if Lane: mask &= (data['Lane'] == Lane)
if Port: mask &= (data['Discharged Port'] == Port)
if Week: mask &= (data['Week Number'] == Week)
# Carrier is NOT part of mask - it's the target!
```

### Three-Phase Removal Logic

```python
# Phase 1: During allocation loop
for row in eligible_data:
    if allocated_count < target:
        allocate_containers()
        update_remaining_data()  # Remove allocated containers

# Phase 2: After allocation loop
if is_maximum_constraint:
    for row in remaining_eligible_rows:
        mark_for_removal()  # Containers that matched filter but weren't allocated

# Phase 3: After constraint processed
if is_maximum_constraint:
    carrier_mask = (data[carrier_col] == target_carrier)
    remove_mask = filter_mask & carrier_mask
    remove_rows(remove_mask)  # ALL carrier rows for this segment
```

## Conclusion

This three-phase approach ensures that Maximum Container Count constraints create true hard caps:

1. ✅ Allocated volume appears in constrained table
2. ✅ No volume for that carrier/segment in unconstrained table
3. ✅ Optimization treats carrier as unavailable for that segment
4. ✅ Works seamlessly with all other constraint types
5. ✅ Preserves total container counts
6. ✅ Provides clear audit trail

The carrier is effectively "locked" at the maximum for that specific segment, while remaining available for other segments without maximum constraints.
