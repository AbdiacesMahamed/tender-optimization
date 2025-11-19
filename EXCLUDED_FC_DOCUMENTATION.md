# Excluded FC (Excluded Facility) Feature Documentation

## Overview

The Excluded FC feature allows you to specify that a carrier **cannot receive containers at a specific facility** in both the constrained and unconstrained tables. This is useful when operational constraints prevent a carrier from servicing certain facilities.

## Purpose

Prevent a carrier from being allocated volume at specific facilities while still allowing them to service other facilities.

## Requirements

### Required Fields

- **Carrier**: The carrier to which the exclusion applies (REQUIRED)
- **Excluded FC**: The facility code where the carrier cannot receive containers (REQUIRED)

### Optional Fields

- Maximum Container Count
- Minimum Container Count
- Percent Allocation
- Category, Lane, Port, Week Number (filters)

## How It Works

### Step 1: Validation

When a constraint includes Excluded FC:

```
IF Excluded FC is specified:
    IF NO Carrier specified:
        ERROR: "Excluded FC requires a Carrier to be specified!"
        Constraint skipped
```

### Step 2: Filter Application

During allocation, containers at the excluded facility are filtered OUT:

```python
# Find all rows at the excluded facility
excluded_facility_mask = data['Facility'] == excluded_facility

# Remove from eligible data
mask &= ~excluded_facility_mask

# Result: Carrier will only get containers from OTHER facilities
```

### Step 3: Constrained Table Check

After allocation to constrained table:

```python
# Check if any allocated containers are at excluded facility
if any constrained record has:
    (Carrier == target_carrier) AND (Facility == excluded_facility):

    CONSTRAINT FAILS
    ERROR: "Cannot allocate carrier containers to excluded facility"
    Rollback constraint
```

### Step 4: Unconstrained Table Check

Check remaining data for violations:

```python
# Find carrier containers at excluded facility in unconstrained table
if unconstrained data has:
    (Carrier == target_carrier) AND (Facility == excluded_facility):

    WARNING: "Containers must be reallocated to other carriers"
    # Containers marked for reallocation during optimization
```

## Examples

### Example 1: Basic Excluded FC

```excel
Carrier: ATMI
Excluded FC: IUSF
Maximum: 100
```

**Scenario:**

- Total containers: 200
- ATMI at IUSF: 50 containers
- ATMI at GBPT: 150 containers

**Result:**

- **Constrained**: 100 containers from GBPT allocated to ATMI ✅
- **Unconstrained**:
  - ATMI at GBPT: 50 containers (150 - 100 allocated)
  - ATMI at IUSF: 50 containers (must go to other carriers)
- **Status**: SUCCESS (ATMI gets GBPT containers, IUSF skipped)

### Example 2: Excluded FC with Filters

```excel
Carrier: FRGT
Category: Import
Excluded FC: LAXW
Minimum: 50
```

**Scenario:**

- Import containers: 100
- FRGT at LAXW: 60 Import containers
- FRGT at GBPT: 40 Import containers

**Result:**

- **Constrained**: 40 containers from GBPT allocated to FRGT
- **Status**: FAILED (Need 50, only 40 available excluding LAXW)
- **Error**: "Cannot meet minimum without using excluded facility"

### Example 3: Multiple Carriers, Same Facility

```excel
Constraint 1:
  Carrier: ATMI
  Excluded FC: IUSF
  Maximum: 100

Constraint 2:
  Carrier: FRGT
  Excluded FC: IUSF
  Maximum: 80
```

**Result:**

- ATMI gets up to 100 containers from non-IUSF facilities
- FRGT gets up to 80 containers from non-IUSF facilities
- IUSF containers must go to OTHER carriers (not ATMI or FRGT)

### Example 4: Excluded FC Preventing Constraint

```excel
Carrier: ATMI
Excluded FC: IUSF
Category: Import
Maximum: 100
```

**Scenario:**

- Import containers: 120 total
- ALL 120 Import containers are at IUSF facility

**Result:**

- **Constrained**: 0 containers (no Import containers outside IUSF)
- **Status**: FAILED
- **Error**: "No eligible containers - all at excluded facility IUSF"

## Constraint Failure Scenarios

### Scenario 1: All Containers at Excluded Facility

```
Problem: All matching containers are at the excluded facility
Result: CONSTRAINT FAILS - No containers to allocate
Message: "No eligible data - all containers at excluded facility"
```

### Scenario 2: Insufficient Non-Excluded Containers

```
Problem: Minimum/Maximum requires more containers than available outside excluded facility
Result: CONSTRAINT FAILS - Cannot meet requirement
Message: "Cannot meet constraint without using excluded facility"
```

### Scenario 3: Carrier Already Has Containers at Excluded Facility

```
Problem: In unconstrained data, carrier has containers at excluded facility
Result: WARNING - Containers must be reallocated
Message: "Containers for [carrier] at [facility] must be reallocated"
Action: Optimization will reassign to other carriers
```

## Implementation Logic

### During Constraint Processing

```python
# 1. Validate
if excluded_facility and not target_carrier:
    ERROR: "Excluded FC requires Carrier"
    Skip constraint

# 2. Filter eligible data
if excluded_facility:
    # Remove rows at excluded facility from eligible data
    mask &= ~(data['Facility'] == excluded_facility)

# 3. Allocate containers
# (Only non-excluded facility containers are allocated)

# 4. Verify constrained table
for record in constrained_records:
    if record['Carrier'] == target_carrier and record['Facility'] == excluded_facility:
        FAIL: "Carrier allocated to excluded facility"
        Rollback

# 5. Check unconstrained table
if unconstrained has (carrier + excluded_facility):
    WARNING: "Must reallocate to other carriers"
```

### During Optimization

```python
# Optimization should respect excluded facilities
# Option 1: Filter out carrier+facility combinations before optimization
# Option 2: Add carrier+facility pairs to exclusion list
```

## Logging Output

### Successful Application

```
🔍 Applying 1 constraint(s)...

Priority 100: All data → Assign to ATMI
   🚫 Excluding IUSF for ATMI
   ✅ Allocated 100 containers to ATMI (from non-IUSF facilities)

📊 Constraint Application Summary:
- Applied constraints: 1
- Status: SUCCESS
```

### Failed Application

```
🔍 Applying 1 constraint(s)...

Priority 100: All data → Assign to ATMI
   🚫 Excluding IUSF for ATMI
   ❌ CONSTRAINT FAILED: Cannot allocate ATMI containers to excluded facility IUSF
   No alternative carrier available for containers at IUSF

📊 Constraint Application Summary:
- Applied constraints: 0
- Failed constraints: 1
```

### Warning (Reallocation Needed)

```
🔍 Applying 1 constraint(s)...

Priority 100: All data → Assign to ATMI
   🚫 Excluding IUSF for ATMI
   ✅ Allocated 100 containers to ATMI
   ⚠️ Found 50 containers for ATMI at excluded facility IUSF
   These containers must be reallocated to other carriers or constraint will fail

📊 Constraint Application Summary:
- Applied constraints: 1
- Warnings: 1 (reallocation needed)
```

## Use Cases

### Use Case 1: Operational Restrictions

**Scenario**: ATMI cannot operate at IUSF facility due to equipment limitations

**Constraint**:

```
Carrier: ATMI
Excluded FC: IUSF
Maximum: 200
```

**Result**: ATMI gets up to 200 containers from all facilities EXCEPT IUSF

### Use Case 2: Regional Limitations

**Scenario**: FRGT cannot service West Coast facilities

**Constraints**:

```
Constraint 1:
  Carrier: FRGT
  Excluded FC: LAXW
  Maximum: 100

Constraint 2:
  Carrier: FRGT
  Excluded FC: OAKL
  Maximum: 100
```

**Result**: FRGT gets containers from non-West Coast facilities only

### Use Case 3: Temporary Restrictions

**Scenario**: ABC carrier suspended from GBPT for Week 47

**Constraint**:

```
Carrier: ABC
Week Number: 47
Excluded FC: GBPT
Maximum: 50
```

**Result**: ABC gets up to 50 containers in Week 47 from facilities other than GBPT

## Data Validation

### Constraint File Format

```excel
| Carrier | Excluded FC | Maximum | Priority Score |
|---------|-------------|---------|----------------|
| ATMI    | IUSF        | 100     | 100            |
| FRGT    | LAXW        | 80      | 90             |
```

### Column Name Variations (All Accepted)

- "Excluded FC"
- "Excluded Facility"
- "excluded fc"
- "EXCLUDED_FC"

### Validation Rules

1. ✅ Excluded FC requires Carrier
2. ✅ Facility code must match data
3. ✅ Can combine with filters (Category, Lane, Port, Week)
4. ✅ Can combine with Maximum/Minimum/Percent
5. ❌ Cannot use Excluded FC without Carrier

## Benefits

1. **Operational Flexibility**: Prevent carriers from servicing specific facilities
2. **Constraint Compliance**: Ensure operational restrictions are enforced
3. **Automatic Reallocation**: System handles reallocation to compliant carriers
4. **Clear Failure Messages**: Knows when constraints cannot be satisfied
5. **Works with Other Constraints**: Seamlessly integrates with Maximum/Minimum/Percent

## Technical Details

### Files Modified

- `components/constraints_processor.py`: Main constraint processing logic

### Key Functions

- `process_constraints_file()`: Column mapping and validation
- `apply_constraints_to_data()`: Excluded FC filtering and checking

### Data Flow

1. Load constraint file → Map "Excluded FC" column
2. Validate Carrier + Excluded FC pairing
3. Filter eligible data (exclude facility)
4. Allocate containers to constrained table
5. Verify no violations in constrained table
6. Check unconstrained table for violations
7. Warn or fail if violations found

## Testing Checklist

Test these scenarios:

- [ ] Excluded FC with carrier (should work)
- [ ] Excluded FC without carrier (should fail)
- [ ] Carrier has containers only at excluded facility (should fail)
- [ ] Carrier has containers at multiple facilities (should allocate from non-excluded)
- [ ] Multiple carriers with different excluded facilities
- [ ] Excluded FC + Maximum constraint
- [ ] Excluded FC + Minimum constraint (may fail if insufficient non-excluded containers)
- [ ] Excluded FC + Percent Allocation
- [ ] Excluded FC + Category/Lane filters
- [ ] Container count preservation with Excluded FC

## Summary

The Excluded FC feature provides fine-grained control over carrier-facility assignments:

✅ **Prevents** carriers from receiving containers at specific facilities  
✅ **Works** with all constraint types (Maximum, Minimum, Percent)  
✅ **Validates** that constraints can be satisfied  
✅ **Fails** cleanly when constraints cannot be met  
✅ **Integrates** seamlessly with existing constraint logic

This ensures operational restrictions are strictly enforced while maintaining flexibility for valid carrier assignments.
