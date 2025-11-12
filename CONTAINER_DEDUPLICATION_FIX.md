# Container Deduplication Fix

## Problem
Constrained data shows duplicate containers appearing across multiple carriers for the same week. This violates the business rule that only ONE carrier can have a specific container for a given week.

### Example from Screenshot
Week 47 BAL data shows the same containers (APHU6682645, BEAU5971095, CMAU4993184, etc.) appearing in multiple rows assigned to different carriers (XPOR, HDDR, FRQT).

## Root Cause
The constraint processor operates at the row level, tracking `Container Count` but not tracking which specific container IDs have been allocated. When multiple constraints match the same data (different rows with overlapping containers), the same physical container IDs can be allocated multiple times.

### Current Logic Flow
1. Constraint 1: Takes 10 containers from Row A (which has containers: ABC, DEF, GHI, JKL, MNO, PQR, STU, VWX, YZ1, YZ2)
2. Constraint 2: Takes 5 containers from Row B (which might have overlapping containers: ABC, DEF, GHI, JKL, MNO)
3. Result: Containers ABC, DEF, GHI, JKL, MNO appear in BOTH constrained allocations

## Solution Required
Implement container-level tracking:

1. **Parse Container Numbers**: Split comma-separated container IDs into individual containers
2. **Track Allocated Containers**: Maintain a set of allocated container IDs
3. **Remove Allocated Containers**: When allocating, remove specific container IDs from the source row
4. **Update Counts**: Recalculate Container Count based on remaining Container Numbers
5. **Prevent Duplicates**: Skip containers that have already been allocated

### Implementation Steps

```python
def split_container_numbers(container_str):
    """Split container numbers string into list of container IDs"""
    if pd.isna(container_str) or not str(container_str).strip():
        return []
    return [c.strip() for c in str(container_str).split(',') if c.strip()]

def allocate_specific_containers(row, num_containers, allocated_tracker, target_carrier, week):
    """
    Allocate specific container IDs from a row
    Returns: (allocated_ids, remaining_ids)
    """
    container_ids = split_container_numbers(row.get('Container Numbers', ''))
    
    # Filter out already-allocated containers
    available_ids = [cid for cid in container_ids if cid not in allocated_tracker]
    
    # Take up to num_containers
    allocated_ids = available_ids[:num_containers]
    remaining_ids = available_ids[num_containers:]
    
    # Mark as allocated
    for cid in allocated_ids:
        allocated_tracker[cid] = {'carrier': target_carrier, 'week': week}
    
    return allocated_ids, remaining_ids
```

### Key Changes Needed

1. **constraints_processor.py Line 181**: Replace `constrained_indices` set with `allocated_containers_tracker` dict
2. **Container Allocation Loop (Lines 305-344)**: 
   - Parse Container Numbers to get individual IDs
   - Check if container IDs are already allocated
   - Allocate specific container IDs (not just counts)
   - Update both Container Numbers and Container Count
3. **Remaining Data Update**: Remove allocated container IDs from remaining data rows

## Testing
After fix, verify:
- [ ] No duplicate container IDs appear across constrained records for the same week
- [ ] Container Count matches the number of container IDs in Container Numbers column
- [ ] Total containers (constrained + unconstrained) equals original total
- [ ] Each constraint allocates unique containers

## Files to Modify
- `components/constraints_processor.py`: Main constraint application logic
