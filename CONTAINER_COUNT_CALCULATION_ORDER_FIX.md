# Container Count Calculation Order - Comprehensive Fix

## Issue Reported

User noticed container count mismatches in scenario tables:

- **TIW, FBA FCL, HDDR, Week 43**: Container Count shows 1, but Container Numbers has 3 IDs (EMCU1720635, TGBU4347971, TXGU6074267)
- **HOU, FBA LCL, ATMI, Week 38**: Container Count shows 0, but Container Numbers has 1 ID (SEGU2123678)

## Root Cause Analysis

Container Count was being calculated/set at different stages, but not always being recalculated after Container Numbers was modified. This led to mismatches where Container Count didn't reflect the actual number of IDs in Container Numbers.

## Design Principle

**Container Numbers is the source of truth. Container Count must ALWAYS be calculated FROM Container Numbers, especially after ANY operation that modifies Container Numbers.**

## Files Fixed

### 1. ✅ `optimization/linear_programming.py`

**Problem**: After proportionally distributing Container Numbers to carriers, Container Count was not recalculated from the assigned Container Numbers string.

**Fix Applied** (lines 361-376):

```python
result = pd.DataFrame(result_rows)

# CRITICAL: Recalculate Container Count from Container Numbers after assignment
# This ensures Container Count always matches the actual number of IDs in Container Numbers
if container_numbers_column in result.columns:
    def count_containers_in_string(container_str):
        """Count actual container IDs in a comma-separated string"""
        if pd.isna(container_str) or not str(container_str).strip():
            return 0
        containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
        return len(containers)

    result[container_column] = result[container_numbers_column].apply(count_containers_in_string)

return result
```

**When This Runs**: After Linear Programming optimization assigns containers to carriers and distributes Container Numbers proportionally.

### 2. ✅ `optimization/cascading_logic.py`

**Problem**: Cascading logic didn't handle Container Numbers column AT ALL. It only manipulated Container Count without tracking which container IDs were assigned to which carrier.

**Fixes Applied**:

#### A. Collect all Container Numbers for the group (lines 170-177):

```python
# Collect all Container Numbers for this group if the column exists
all_container_numbers = []
container_numbers_column = "Container Numbers"
if container_numbers_column in group_data.columns:
    for containers_str in group_data[container_numbers_column]:
        if pd.notna(containers_str) and str(containers_str).strip():
            all_container_numbers.extend([c.strip() for c in str(containers_str).split(',') if c.strip()])
```

#### B. Distribute Container Numbers proportionally (lines 226-244):

```python
# Track remaining container numbers for proportional distribution
remaining_container_numbers = all_container_numbers.copy() if all_container_numbers else []

for carrier, allocated_count in allocations.items():
    if allocated_count == 0:
        continue

    row = carrier_data[carrier].copy()
    row[container_column] = allocated_count

    # Assign Container Numbers proportionally if available
    if remaining_container_numbers:
        proportion = allocated_count / total_containers
        num_to_assign = max(1, round(len(all_container_numbers) * proportion))
        assigned_containers = remaining_container_numbers[:num_to_assign]
        remaining_container_numbers = remaining_container_numbers[num_to_assign:]
        row[container_numbers_column] = ", ".join(assigned_containers)
```

#### C. Handle remaining container numbers (lines 279-285):

```python
# Assign any remaining container numbers due to rounding
if remaining_container_numbers and result_rows:
    first_row_containers = result_rows[0].get(container_numbers_column, "")
    if first_row_containers:
        result_rows[0][container_numbers_column] = first_row_containers + ", " + ", ".join(remaining_container_numbers)
    else:
        result_rows[0][container_numbers_column] = ", ".join(remaining_container_numbers)
```

#### D. Recalculate Container Count from Container Numbers (lines 290-302):

```python
result = pd.DataFrame(result_rows)

# CRITICAL: Recalculate Container Count from Container Numbers after assignment
# This ensures Container Count always matches the actual number of IDs in Container Numbers
if container_numbers_column in result.columns:
    def count_containers_in_string(container_str):
        """Count actual container IDs in a comma-separated string"""
        if pd.isna(container_str) or not str(container_str).strip():
            return 0
        containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
        return len(containers)

    result[container_column] = result[container_numbers_column].apply(count_containers_in_string)
```

**When This Runs**: In the Optimized scenario when using cascading allocation with historical constraints.

### 3. ✅ `components/metrics.py` (Already Fixed Previously)

All three scenarios that manipulate data already had fixes:

#### Performance Scenario (lines 690-704):

```python
# CRITICAL FIX: Recalculate Container Count from Container Numbers to fix input data mismatches
if 'Container Numbers' in performance_source.columns:
    def count_containers_from_string(container_str):
        """Count actual container IDs in a comma-separated string"""
        if pd.isna(container_str) or not str(container_str).strip():
            return 0
        return len([c.strip() for c in str(container_str).split(',') if c.strip()])

    # Store original count for comparison
    performance_source['_original_count'] = performance_source['Container Count'].copy()
    # Recalculate based on actual container IDs
    performance_source['Container Count'] = performance_source['Container Numbers'].apply(count_containers_from_string)
```

#### Optimized Scenario (lines 625-639):

```python
# CRITICAL FIX: Recalculate Container Count from Container Numbers to fix input data mismatches
if 'Container Numbers' in optimization_source.columns:
    def count_containers_from_string(container_str):
        """Count actual container IDs in a comma-separated string"""
        if pd.isna(container_str) or not str(container_str).strip():
            return 0
        return len([c.strip() for c in str(container_str).split(',') if c.strip()])

    # Store original count for comparison
    optimization_source['_original_count'] = optimization_source['Container Count'].copy()
    # Recalculate based on actual container IDs
    optimization_source['Container Count'] = optimization_source['Container Numbers'].apply(count_containers_from_string)
```

#### Cheapest Cost Scenario (lines 985-999, 1208):

```python
# CRITICAL FIX: Recalculate Container Count from Container Numbers to fix input data mismatches
if 'Container Numbers' in source_data.columns:
    def count_containers_from_string(container_str):
        """Count actual container IDs in a comma-separated string"""
        if pd.isna(container_str) or not str(container_str).strip():
            return 0
        return len([c.strip() for c in str(container_str).split(',') if c.strip()])

    # Store original count for comparison
    source_data['_original_count'] = source_data['Container Count'].copy()
    # Recalculate based on actual container IDs
    source_data['Container Count'] = source_data['Container Numbers'].apply(count_containers_from_string)

# ... later after concatenation (line 1208) ...
cheapest_per_group['Container Count'] = cheapest_per_group['_actual_container_count']
```

**When This Runs**: Before each scenario processes the data, ensuring input data is correct.

### 4. ✅ `components/data_loader.py` (Already Fixed Previously)

- `load_gvt_data()`: Properly counts containers when loading from Excel
- `create_comprehensive_data()`: Recalculates Container Count after aggregation

## Complete Data Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. LOAD DATA (data_loader.py)                          │
│    - Read Excel file                                    │
│    - Calculate Container Count FROM Container Numbers   │
│    - Result: Container Count = actual IDs in string    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 2. AGGREGATE DATA (data_loader.py)                     │
│    - Concatenate Container Numbers                      │
│    - Recalculate Container Count FROM concatenated     │
│    - Result: Container Count = actual IDs in string    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 3. SCENARIO PROCESSING (metrics.py)                    │
│    - BEFORE scenario runs: Fix input data              │
│    - Recalculate Container Count FROM Container Numbers│
│    - Result: Container Count = actual IDs in string    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 4A. PERFORMANCE SCENARIO (performance_logic.py)        │
│     - Concatenate Container Numbers per group           │
│     - Recalculate Container Count FROM concatenated    │
│     - Result: Container Count = actual IDs in string   │
└─────────────────────────────────────────────────────────┘
                          OR
┌─────────────────────────────────────────────────────────┐
│ 4B. CHEAPEST SCENARIO (cheapest_logic.py)              │
│     - Concatenate Container Numbers per group           │
│     - Recalculate Container Count FROM concatenated    │
│     - Result: Container Count = actual IDs in string   │
└─────────────────────────────────────────────────────────┘
                          OR
┌─────────────────────────────────────────────────────────┐
│ 4C. OPTIMIZED SCENARIO (cascading_logic.py + LP)       │
│     - Collect all Container Numbers for group          │
│     - Distribute proportionally to carriers            │
│     - Recalculate Container Count FROM assigned IDs    │
│     - Result: Container Count = actual IDs in string   │
└─────────────────────────────────────────────────────────┘
                          ↓
                    [Display Results]
              Container Count ✅ Container Numbers
```

## Key Principles Enforced

### 1. Container Numbers is the Source of Truth

Every Container Count value is derived from counting the actual container IDs in Container Numbers.

### 2. Calculate AFTER Container Numbers is Populated

Never set Container Count before Container Numbers exists or is modified.

### 3. Recalculate After Every Transformation

Whenever Container Numbers is:

- Loaded from file → Recalculate Container Count
- Concatenated → Recalculate Container Count
- Distributed → Recalculate Container Count
- Modified in any way → Recalculate Container Count

### 4. Consistent Counting Function

All places use the same robust counting logic:

```python
def count_containers_in_string(container_str):
    if pd.isna(container_str) or not str(container_str).strip():
        return 0
    containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
    return len(containers)
```

## Verification Points

Now every scenario ensures:

1. ✅ **Performance Scenario**: Input data fixed → performance_logic.py recalculates → Display
2. ✅ **Cheapest Cost Scenario**: Input data fixed → cheapest_logic.py recalculates → Display
3. ✅ **Optimized Scenario**: Input data fixed → cascading_logic.py + linear_programming.py recalculate → Display
4. ✅ **Current Selection**: Input data fixed → Display

## Testing Instructions

1. **Restart Streamlit app** to load the updated code
2. **Check the specific cases**:
   - TIW, FBA FCL, HDDR, Week 43: Should show **3 containers** (not 1)
   - HOU, FBA LCL, ATMI, Week 38: Should show **1 container** (not 0)
3. **Debug messages** should show "✅ Data is clean" or specific fixes applied
4. **All scenarios** should show matching Container Count and Container Numbers

## Date Applied

November 10, 2025

## Related Documents

- `CONTAINER_COUNT_LOGIC_FLOW.md` - Explains the overall logic flow
- `ROOT_CAUSE_FIXED.md` - Original root cause fix in data_loader.py
- `FIX_APPLIED.md` - Initial fixes applied
