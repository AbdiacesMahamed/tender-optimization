# Excluded FC Global Application Fix

## Date: November 25, 2025

## Problem Statement

User uploaded constraints with facility exclusions for XPDR:

- XPDR should NOT receive containers at HGR6, BWI4, IUSL, RMN3, TEB4, XLX1
- Each exclusion was in a separate row with no allocation amount (Percent Allocation empty, Max/Min empty or 0)
- Despite these constraints, XPDR was still receiving containers at HGR6 (`TGBU8890143`)

Example constraint rows:
| Port | Carrier | Percent Allocation | Week | Excluded FC | Priority |
|------|---------|-------------------|------|-------------|----------|
| BAL | XPDR | 20% | 48 | | 2 |
| BAL | XPDR | | 48 | IUSL | 5 |
| BAL | XPDR | | 48 | HGR6 | 5 |
| ... | ... | ... | ... | ... | ... |

## Root Cause Analysis

### Issue 1: Exclusion-only rows were being skipped

Rows without allocation amounts (Percent Allocation, Maximum, Minimum all empty) were skipped entirely:

```python
else:
    # No allocation amount specified - skip this constraint
    st.warning(f"⚠️ No allocation amount specified...")
    continue  # <-- Exclusion rows skipped here!
```

### Issue 2: Exclusions not collected before processing

The code attempted to look up exclusions from other constraint rows, but only during allocation processing. Since exclusion-only rows were skipped BEFORE this lookup, the exclusions were never found.

### Issue 3: Existing carrier assignments not cleared

Even when exclusions were found, the code only warned about violations in existing data. It didn't actually clear the carrier assignment for containers at excluded facilities.

## Solution Implemented

### 1. Pre-collect ALL exclusions before processing constraints

Added a new section that scans ALL constraint rows for Excluded FC values BEFORE processing:

```python
# ========== PRE-COLLECT ALL CARRIER+FACILITY EXCLUSIONS ==========
carrier_facility_exclusions = {}

for _, row in constraints_df.iterrows():
    carrier = row.get('Carrier')
    excluded_fc = row.get('Excluded FC')

    if carrier and excluded_fc:
        # Collect exclusion for this carrier
        carrier_facility_exclusions[carrier].add(normalized_fc)
```

### 2. Apply exclusions to existing carrier assignments

Added logic to clear carrier assignments that violate facility exclusions:

```python
# ========== APPLY EXCLUSIONS TO REMAINING DATA ==========
for carrier, excluded_facilities in carrier_facility_exclusions.items():
    violation_mask = (carrier_col == carrier) & (facility in excluded_facilities)

    if violation_mask.any():
        # Clear the carrier assignment - set to empty
        remaining_data.loc[violation_mask, carrier_col] = ''
```

This allows optimization to reassign these containers to other carriers.

### 3. Improved exclusion lookup for allocation constraints

Enhanced the lookup to properly find exclusions from exclusion-only rows:

```python
# Build mask for finding exclusions - check for carrier match
carrier_mask = constraints_df['Carrier'] == target_carrier

# Check for non-empty Excluded FC values
has_excluded_fc = excluded_fc_values.notna() & (excluded_fc_values.astype(str).str.strip() != '')

# Also respect Port and Week Number scope
scope_mask = carrier_mask & has_excluded_fc
```

### 4. New return value for carrier_facility_exclusions

The function now returns `carrier_facility_exclusions` dict for use in downstream processing:

```python
return constrained_data, remaining_data, constraint_summary, max_constrained_carriers, carrier_facility_exclusions
```

## How It Works Now

1. **Pre-scan phase**: Before any constraint is processed, all `Carrier + Excluded FC` pairs are collected
2. **Clear violations**: Any existing container assignments that violate exclusions are cleared
3. **Allocation phase**: When allocating to a carrier, exclusions from all rows (including exclusion-only rows) are respected
4. **Containers reassigned**: Cleared containers go to the unconstrained pool for optimization to reassign

## Example Flow

Given constraints:

- BAL/XPDR/20%/Week 48 (allocation)
- BAL/XPDR/HGR6 (exclusion)

Before fix:

1. Exclusion row skipped (no allocation amount)
2. XPDR 20% allocation ignores HGR6 exclusion
3. Container TGBU8890143 at HGR6 stays with XPDR ❌

After fix:

1. Pre-scan finds: XPDR cannot receive at HGR6
2. Clear existing XPDR assignment at HGR6 (TGBU8890143)
3. XPDR 20% allocation excludes HGR6
4. Container TGBU8890143 available for other carriers ✅

## Files Modified

1. `components/constraints_processor.py`:

   - Added `carrier_facility_exclusions` dict tracking
   - Added pre-collection of exclusions from all constraint rows
   - Added clearing of existing carrier assignments at excluded facilities
   - Enhanced exclusion lookup to find exclusions from exclusion-only rows
   - Updated return value to include `carrier_facility_exclusions`

2. `dashboard.py`:
   - Updated call to `apply_constraints_to_data` to handle new return value

## Testing

To verify the fix works:

1. Upload constraints with exclusion-only rows (Carrier + Excluded FC, no allocation)
2. Check that pre-collection message shows all exclusions found
3. Verify containers at excluded facilities have carrier assignment cleared
4. Confirm allocation constraints respect exclusions from other rows
