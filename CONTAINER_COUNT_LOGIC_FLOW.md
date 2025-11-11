# Container Count Logic Flow

## Design Philosophy

**Container Numbers** is the **source of truth**. Container Count is **always calculated from** Container Numbers, never stored independently.

## Flow in load_gvt_data()

```
1. Read Excel file
   ↓
2. Verify Container Numbers column exists
   ↓
3. Process other columns (Discharged Port, etc.)
   ↓
4. Calculate Container Count FROM Container Numbers
   ├─ Split by comma
   ├─ Strip whitespace from each ID
   ├─ Filter out empty values
   └─ Count the remaining IDs
   ↓
5. Return data with Container Numbers + Container Count
```

### Code Implementation:

```python
# Step 2: Verify Container Numbers exists
if 'Container Numbers' not in gvt_data.columns:
    st.error("Container Numbers column is required!")
    return None

# Step 3: Process other columns
gvt_data['Discharged Port'] = gvt_data['Lane'].str.split('-').str[0]

# Step 4: Calculate Container Count AFTER confirming Container Numbers exists
def count_containers_properly(container_str):
    if pd.isna(container_str) or not str(container_str).strip():
        return 0
    ids = [c.strip() for c in str(container_str).split(',') if c.strip()]
    return len(ids)

gvt_data['Container Count'] = gvt_data['Container Numbers'].apply(count_containers_properly)
```

## Flow in create_comprehensive_data()

```
1. Merge GVT data with Performance data
   ↓
2. Group by dimensions (Lane, Week, Carrier, etc.)
   ↓
3. Aggregate:
   ├─ Container Numbers: CONCATENATE (join with comma)
   ├─ Container Count: SUM (temporary, will be overwritten)
   ├─ Base Rate: FIRST
   ├─ Total Rate: SUM
   └─ Performance_Score: FIRST
   ↓
4. RECALCULATE Container Count FROM concatenated Container Numbers
   ├─ Split the concatenated string by comma
   ├─ Strip whitespace from each ID
   ├─ Filter out empty values
   └─ Count the remaining IDs
   ↓
5. Return data with Container Numbers + recalculated Container Count
```

### Code Implementation:

```python
# Step 3: Aggregate - Container Numbers is concatenated
agg_dict = {
    'Container Numbers': lambda x: ','.join(x),  # Source of truth
    'Container Count': 'sum',  # Temporary - will be replaced
    ...
}
comprehensive_data = comprehensive_data.groupby(group_cols).agg(agg_dict)

# Step 4: Recalculate Container Count AFTER Container Numbers are concatenated
def recount_containers(container_str):
    if pd.isna(container_str) or not str(container_str).strip():
        return 0
    ids = [c.strip() for c in str(container_str).split(',') if c.strip()]
    return len(ids)

# This line ensures Container Count is ALWAYS calculated FROM Container Numbers
comprehensive_data['Container Count'] = comprehensive_data['Container Numbers'].apply(recount_containers)
```

## Why This Order Matters

### ❌ Wrong Approach (old code):

```python
# Calculate Container Count independently
gvt_data['Container Count'] = gvt_data['Container Numbers'].str.split(',').apply(len)
# Problem: Doesn't handle whitespace, empty values, trailing commas

# Sum during aggregation
'Container Count': 'sum'
# Problem: Propagates errors from step 1
```

Result: Container Count (41) ≠ Container Numbers (39 IDs) ❌

### ✅ Correct Approach (new code):

```python
# Calculate Container Count from the actual data
ids = [c.strip() for c in container_str.split(',') if c.strip()]
return len(ids)
# Benefit: Handles whitespace, empty values, trailing commas

# Recalculate after aggregation
comprehensive_data['Container Count'] = comprehensive_data['Container Numbers'].apply(recount_containers)
# Benefit: Container Count always matches Container Numbers
```

Result: Container Count (39) = Container Numbers (39 IDs) ✅

## Key Principles

1. **Container Numbers is the Source of Truth**

   - All counts are derived from this column
   - Never trust Container Count without verifying against Container Numbers

2. **Calculate AFTER Data is Present**

   - Check that Container Numbers exists first
   - Only then calculate Container Count from it

3. **Recalculate After Transformation**

   - When Container Numbers is concatenated (aggregation)
   - When Container Numbers is modified (filtering, scenarios)
   - Always recalculate Container Count to ensure consistency

4. **Robust Counting Function**
   - Strip whitespace from each ID
   - Filter out empty strings
   - Handle NaN/None values
   - Count only actual container IDs

## Verification Points

At each stage, we verify consistency:

### Stage 1: After GVT Load

```python
✅ Container Numbers exists
✅ Container Count calculated from Container Numbers
✅ Every row: Container Count = len(Container Numbers.split(','))
```

### Stage 2: After Aggregation

```python
✅ Container Numbers concatenated
✅ Container Count recalculated from concatenated string
✅ Every row: Container Count = number of IDs in concatenated string
```

### Stage 3: After Filtering

```python
✅ Container Numbers unchanged (just filtered rows)
✅ Container Count matches Container Numbers
✅ Debug confirms: "Data is clean"
```

### Stage 4: In Scenarios

```python
✅ Container Numbers may be concatenated again
✅ Container Count recalculated again
✅ Debug confirms: "All Container Counts Match"
```

## Example Walkthrough

### Input Data (from Excel):

```
Container Numbers: "MRKU001, MRKU002, , MRKU003, "
Container Count: ??? (we'll calculate this)
```

### Step 1: Calculate from Raw Data

```python
container_str = "MRKU001, MRKU002, , MRKU003, "
ids = [c.strip() for c in container_str.split(',') if c.strip()]
# ids = ['MRKU001', 'MRKU002', 'MRKU003']
Container Count = 3 ✅
```

### Step 2: After Aggregation (if grouped)

```python
# Two rows concatenated:
Row 1: "MRKU001, MRKU002, MRKU003"
Row 2: "MRKU004, MRKU005"

# After concatenation:
Container Numbers: "MRKU001, MRKU002, MRKU003,MRKU004, MRKU005"

# Recalculate:
ids = [c.strip() for c in container_str.split(',') if c.strip()]
# ids = ['MRKU001', 'MRKU002', 'MRKU003', 'MRKU004', 'MRKU005']
Container Count = 5 ✅
```

## Summary

**The Logic**:

1. Container Numbers column is populated from source data
2. Container Count is calculated FROM Container Numbers
3. After any transformation, Container Count is recalculated
4. Container Numbers is always the source of truth

**The Result**: Container Count always matches the actual number of container IDs in Container Numbers!

**Date**: November 10, 2025
