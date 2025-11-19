# Excluded FC Facility Code Normalization Fix

## Problem Identified

User specified "HGR6" in the Excluded FC constraint, but the system still allocated containers to ATMI at facilities "HGR6-5" and "HGR5-5".

**Root Cause**: The facility comparison was using exact string matching:

```python
# OLD (BROKEN):
excluded_facility_mask = remaining_data['Facility'] == excluded_facility
# "HGR6" != "HGR6-5" ❌ No match
```

## Solution Implemented

Added facility code normalization to compare only the first 4 characters of facility codes, matching the industry standard facility naming convention.

### 1. New Helper Function

```python
def normalize_facility_code(facility_str):
    """
    Normalize facility code to first 4 characters for comparison
    Examples: 'HGR6-5' -> 'HGR6', 'IUSF' -> 'IUSF', 'GBPT-3' -> 'GBPT'
    """
    if pd.isna(facility_str) or not str(facility_str).strip():
        return ''
    # Convert to string and strip whitespace
    fc = str(facility_str).strip().upper()
    # Take first 4 characters
    return fc[:4] if len(fc) >= 4 else fc
```

### 2. Updated Filtering Logic (Step 1)

```python
# NEW (FIXED):
if excluded_facility and 'Facility' in remaining_data.columns:
    # Normalize the excluded facility to first 4 characters
    normalized_excluded_fc = normalize_facility_code(excluded_facility)

    # Find rows at the excluded facility (comparing normalized codes)
    excluded_facility_mask = remaining_data['Facility'].apply(normalize_facility_code) == normalized_excluded_fc

    # Remove those rows from eligible data
    mask &= ~excluded_facility_mask
```

**How it works now**:

- User specifies: "HGR6"
- System normalizes to: "HGR6"
- Data facility "HGR6-5" normalizes to: "HGR6"
- Match found! ✅ Row excluded

### 3. Updated Constrained Table Check (Step 2)

```python
# Normalize the excluded facility for comparison
normalized_excluded_fc = normalize_facility_code(excluded_facility)

for record in constrained_records:
    if (record.get('Carrier') == target_carrier or record.get('Dray SCAC(FL)') == target_carrier):
        # Compare normalized facility codes
        record_facility_normalized = normalize_facility_code(record.get('Facility', ''))
        if record_facility_normalized == normalized_excluded_fc:
            facility_violation_in_constrained = True
            st.error(f"   ❌ Violation found: {record.get('Facility')} matches excluded {excluded_facility}")
            break
```

### 4. Updated Unconstrained Table Check (Step 3)

```python
excluded_mask = pd.Series([False] * len(remaining_data), index=remaining_data.index)
for col in carrier_cols:
    # Use normalized facility code comparison
    excluded_mask |= (
        (remaining_data[col] == target_carrier) &
        (remaining_data['Facility'].apply(normalize_facility_code) == normalized_excluded_fc)
    )
```

## Examples

### Example 1: HGR6 Exclusion

**Constraint**:

```excel
Carrier: ATMI
Excluded FC: HGR6
Maximum: 5
```

**Data Facilities**:

- HGR5-5
- HGR6-5
- IUSF

**Before Fix**:

- HGR6-5 NOT excluded (exact match failed) ❌
- ATMI got containers from HGR6-5 ❌

**After Fix**:

- HGR6-5 normalized to HGR6 ✅
- HGR6-5 excluded (match found) ✅
- ATMI cannot get containers from HGR6-5 ✅

### Example 2: Multiple Facilities with Same Base

**Constraint**:

```excel
Carrier: FRGT
Excluded FC: GBPT
Maximum: 100
```

**Data Facilities**:

- GBPT (exact match)
- GBPT-1
- GBPT-2
- GBPT-3

**Result**:

- All variants (GBPT, GBPT-1, GBPT-2, GBPT-3) excluded ✅
- FRGT cannot get containers from any GBPT facility ✅

### Example 3: Exact 4-Character Codes

**Constraint**:

```excel
Carrier: ATMI
Excluded FC: IUSF
Maximum: 50
```

**Data Facilities**:

- IUSF (4 characters, no suffix)
- LAXW
- HGR6-5

**Result**:

- IUSF normalized to IUSF ✅
- IUSF excluded ✅
- Works same as before (backward compatible) ✅

## Enhanced Logging

The system now shows normalized facility codes in logs:

### Successful Exclusion

```
🔍 Applying 1 constraint(s)...

Priority 2: Week=47, Excluding Facility=HGR6 → Assign to ATMI
   🚫 Excluding 1 rows at facility HGR6 (normalized: HGR6) for ATMI
   ✅ Allocated 5 containers to ATMI

Status: Applied
Containers: 5 / 5
```

### No Rows Found (Good)

```
Priority 2: Week=47, Excluding Facility=HGR6 → Assign to ATMI
   ℹ️ No rows found at facility HGR6 (normalized: HGR6)
   ✅ Allocated 5 containers to ATMI
```

### Violation Detected (Error)

```
Priority 2: Week=47, Excluding Facility=HGR6 → Assign to ATMI
   🚫 Excluding 1 rows at facility HGR6 (normalized: HGR6) for ATMI
   ❌ Violation found: HGR6-5 matches excluded HGR6
   ❌ CONSTRAINT FAILED: Cannot allocate ATMI containers to excluded facility HGR6
```

### Warning in Unconstrained

```
⚠️ Found 4 containers for ATMI at excluded facility HGR6 (normalized: HGR6)
   These containers must be reallocated to other carriers or constraint will fail
```

## Benefits

1. ✅ **Industry Standard**: Follows facility naming convention (4-char base + optional suffix)
2. ✅ **User-Friendly**: Users can specify just "HGR6" instead of all variants
3. ✅ **Comprehensive**: Catches all facility variants (HGR6, HGR6-1, HGR6-5, etc.)
4. ✅ **Backward Compatible**: Still works with exact 4-character codes (IUSF, GBPT, LAXW)
5. ✅ **Clear Logging**: Shows both original and normalized codes
6. ✅ **Consistent**: Applied to all three check points (filtering, constrained, unconstrained)

## Testing Scenarios

### Scenario 1: Suffix Variants

```
Constraint: Excluded FC = HGR6
Data: HGR6-1, HGR6-2, HGR6-5
Result: All excluded ✅
```

### Scenario 2: Exact Match

```
Constraint: Excluded FC = IUSF
Data: IUSF
Result: Excluded ✅
```

### Scenario 3: Case Insensitive

```
Constraint: Excluded FC = hgr6
Data: HGR6-5
Result: Excluded (normalized to uppercase) ✅
```

### Scenario 4: Different Base Codes

```
Constraint: Excluded FC = HGR6
Data: HGR5-5, HGR7-1
Result: NOT excluded (different base) ✅
```

### Scenario 5: Short Codes (< 4 chars)

```
Constraint: Excluded FC = LAX
Data: LAX, LAXW
Result: Only LAX excluded (not LAXW) ✅
```

## Code Changes Summary

### Files Modified

- `components/constraints_processor.py`

### Functions Added

- `normalize_facility_code()`: Helper function for facility code normalization

### Functions Updated

- `apply_constraints_to_data()`: Updated three locations:
  1. Excluded FC filtering logic (line ~375)
  2. Constrained table verification (line ~590)
  3. Unconstrained table check (line ~620)

### Lines Changed

- Added: ~15 lines (new function)
- Modified: ~30 lines (comparison logic updates)
- Enhanced: ~10 lines (logging messages)

## Impact

**User's Issue**:

- Before: "HGR6" in Excluded FC didn't match "HGR6-5" in data
- After: "HGR6" correctly matches all HGR6 variants (HGR6-5, HGR6-1, etc.)

**System Behavior**:

- ✅ Constraints now work as expected
- ✅ No breaking changes (backward compatible)
- ✅ Better logging for troubleshooting
- ✅ Follows industry naming conventions

## Validation

The next time you run with:

```excel
Carrier: ATMI
Excluded FC: HGR6
Maximum: 5
```

You should see:

1. ✅ Log showing "Excluding X rows at facility HGR6 (normalized: HGR6)"
2. ✅ NO containers allocated to ATMI at HGR6-5, HGR6-1, or any HGR6 variant
3. ✅ Containers only allocated from non-HGR6 facilities (like HGR5-5, IUSF, etc.)
4. ✅ If violation detected, clear error message with facility names

The fix is complete and ready to use! 🎯
