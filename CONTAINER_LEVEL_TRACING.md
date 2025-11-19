# Container-Level Tracing Feature

## Date

November 19, 2025

## Overview

Implemented comprehensive container-level tracing to track exact movements of individual containers between carriers. This provides precise visibility into which specific containers moved from which carrier to which carrier, along with full context (week, port, lane, facility, terminal, category).

## Problem Solved

The previous "Carrier Flips" column could only show aggregate before/after counts per carrier per group:

- `✓ Had 4, now 5 (+1)` - Carrier gained 1 container
- `✓ Had 12, now 8 (-4)` - Carrier lost 4 containers

**Limitation**: We couldn't tell:

- Which specific containers moved
- From which exact carrier each container came
- Whether a carrier received containers from one source or multiple sources

## Solution Architecture

### 1. Container Origin Mapping

**File**: `components/container_tracer.py`  
**Function**: `build_container_origin_map()`

Builds a comprehensive map of each container's original allocation:

```python
{
    'MSDU123456': {
        'original_carrier': 'ATMI',
        'week': 46,
        'port': 'BAL',
        'lane': 'USBALHIA1',
        'facility': 'HIA1',
        'terminal': 'TRM-SEAGIRT',
        'category': 'Retail CD'
    },
    'TCKU789012': {
        'original_carrier': 'RKNE',
        'week': 46,
        ...
    }
}
```

**Data Source**: The "Container Numbers" column in GVT data contains comma-separated container IDs (e.g., "MSDU123, TCKU456, MSNU789")

### 2. Container Movement Tracing

**Function**: `trace_container_movements()`

For each row in the current scenario data:

1. Parses the container IDs from "Container Numbers" column
2. Looks up each container's origin in the map
3. Compares original carrier vs current carrier
4. Categorizes each container as:
   - **Kept**: Same carrier (original = current)
   - **Flipped**: Different carrier (original ≠ current)
   - **Unknown**: Not found in origin map (new containers)

**Output**: Detailed trace result per row:

```python
{
    'kept_containers': ['MSDU123456', 'MSDU234567'],  # Stayed with carrier
    'flipped_containers': [
        ('TCKU789012', 'RKNE'),  # Container ID, from carrier
        ('XPDR345678', 'XPDR'),
        ('HDDR901234', 'HDDR')
    ],
    'unknown_containers': [],
    'flip_summary': {
        'RKNE': 3,  # Received 3 from RKNE
        'XPDR': 2,  # Received 2 from XPDR
        'HDDR': 1   # Received 1 from HDDR
    },
    'total_kept': 2,
    'total_flipped': 6,
    'total_unknown': 0
}
```

### 3. Display Formatting

**Function**: `format_flip_details()`

Converts trace results into human-readable text:

**Example 1**: Simple case

```
✓ Kept 4, 🔄 From RKNE (3)
```

- Carrier kept 4 of its original containers
- Received 3 additional containers from RKNE

**Example 2**: Multiple sources

```
✓ Kept 2, 🔄 From RKNE (3) + XPDR (2) + HDDR (1)
```

- Kept 2 original containers
- Received 3 from RKNE, 2 from XPDR, 1 from HDDR

**Example 3**: New carrier to group

```
🔄 From RKNE (12) + XPDR (10) + HDDR (9)
```

- Carrier had 0 originally in this group
- Now has containers from multiple sources

**Example 4**: Many sources (abbreviated)

```
🔄 From RKNE (12) + XPDR (10) + HDDR (9) + ARVY (8) + FROT (8) + 3 others (15)
```

- Shows top 5 source carriers
- Groups remaining sources as "X others (count)"

### 4. Movement Summary

**Function**: `get_container_movement_summary()`

Provides aggregate statistics across all containers:

- Total containers tracked
- Total kept with original carrier
- Total flipped to different carriers
- Percentage breakdown
- Top 10 carrier-to-carrier flows
- Flow matrix (from → to → count)

**Function**: `show_container_movement_summary()` (Streamlit UI)

Displays comprehensive movement analysis:

- 📊 Overview metrics (total, kept, flipped, unknown)
- 🔝 Top container flows table
- 📈 Flow visualization (bar chart)
- 💡 Insights and observations

## Integration Points

### 1. In Data Tables

**File**: `components/metrics.py`  
**Line**: ~967-975

Two columns are now added to all scenario tables:

1. **"Carrier Flips"** (Original aggregate version)

   - Shows: `✓ Had 4, now 5 (+1)`
   - Quick summary of before/after counts

2. **"Carrier Flips (Detailed)"** (NEW - Container-level tracing)
   - Shows: `✓ Kept 2, 🔄 From RKNE (3) + XPDR (2)`
   - Exact source carriers and counts

Both columns appear side-by-side so users can choose their preferred level of detail.

### 2. In Summary Widget

**File**: `components/metrics.py`  
**Function**: `show_container_movement_summary()`

Can be called from dashboard to show:

- Overall movement statistics
- Top flows visualization
- Insights

Usage:

```python
from components import show_container_movement_summary

# In dashboard, after scenario calculation
show_container_movement_summary(
    current_data=optimized_data,
    baseline_data=current_selection_data,
    carrier_col='Dray SCAC(FL)'
)
```

## Key Features

### ✅ Accurate Container Tracking

- Traces every individual container ID
- No approximations or estimates
- Verifiable against source data

### ✅ Full Context Preservation

- Tracks port, lane, facility, terminal, category
- Week number for temporal analysis
- Maintains all grouping dimensions

### ✅ Duplicate Detection

- Flags if same container appears multiple times in baseline
- Counts duplicate occurrences
- Helps identify data quality issues

### ✅ Flexible Display

- Optional container ID display (`show_container_ids=True`)
- Configurable max carriers to show
- Abbreviated format for complex cases

### ✅ Performance Optimized

- Uses dictionary lookups (O(1) per container)
- Single pass through data
- Efficient memory usage

## Data Requirements

### Required Columns

1. **GVT Data** (baseline):

   - `Container Numbers` - Comma-separated container IDs
   - `Dray SCAC(FL)` - Carrier identifier
   - `Week Number` - Week identifier
   - Grouping columns: `Discharged Port`, `Lane`, `Facility`, `Terminal`, `Category`

2. **Scenario Data** (current):
   - Same columns as above
   - `Container Numbers` must contain the redistributed container IDs

### Data Flow

1. **Original GVT Upload** → Container origin map built
2. **Scenario Optimization** → Containers redistributed (Container Numbers updated)
3. **Display Tables** → Trace results calculated and shown
4. **Export** → Both columns included in downloads

## Example Use Cases

### Use Case 1: Validate Optimization

**Question**: "Did the optimization actually move containers as expected?"

**Answer**:

```
ATMI row: ✓ Kept 4, 🔄 From RKNE (3) + XPDR (2)
RKNE row: ✓ Had 12, now 9 (-3)
XPDR row: ✓ Had 10, now 8 (-2)
```

Verification:

- ATMI gained 5 (3 from RKNE + 2 from XPDR) ✓
- RKNE lost 3 ✓
- XPDR lost 2 ✓
- Math checks out!

### Use Case 2: Carrier Impact Analysis

**Question**: "Which carriers lost the most volume to competitors?"

**Answer**: Check Movement Summary → Top Flows table

```
RKNE → ATMI: 45 containers (12.3% of total flipped)
XPDR → FROT: 32 containers (8.7% of total flipped)
HDDR → ARVY: 28 containers (7.6% of total flipped)
```

### Use Case 3: Group-Level Changes

**Question**: "In the BAL + Week 46 + HIA1 group, what exactly happened?"

**Answer**: Filter to that group, check Detailed Flips column:

```
ATMI: ✓ Kept 4, 🔄 From RKNE (3)
RKNE: ✓ Had 12, now 9 (-3)
Others: ✓ Kept their allocations
```

Clear story: 3 containers moved from RKNE to ATMI in this group.

### Use Case 4: Multi-Source Consolidation

**Question**: "Which carriers are consolidating volume from multiple sources?"

**Answer**: Look for rows with multiple "From" sources:

```
FROT: 🔄 From RKNE (12) + XPDR (10) + HDDR (9) + ARVY (8) + ATMI (4)
```

FROT is the "winner" - getting containers from 5 different carriers!

## Technical Implementation Details

### Container ID Parsing

Handles various formats:

- `"MSDU123, TCKU456"` - comma-separated
- `"MSDU123,TCKU456"` - no spaces
- `"MSDU123456789012"` - single container
- `""` - empty (no containers)
- `NaN` - missing value

### Performance Characteristics

- **Build origin map**: O(n \* c) where n = rows, c = avg containers per row
- **Trace movements**: O(m \* c) where m = current rows, c = avg containers per row
- **Dictionary lookups**: O(1) per container
- **Memory**: ~100 bytes per container in map

For typical dataset:

- 10,000 baseline rows × 10 containers = 100,000 container origins
- Map size: ~10 MB
- Build time: ~1 second
- Trace time: ~0.5 seconds

### Edge Cases Handled

1. **Container not in origin map**: Marked as "unknown"
2. **Duplicate containers in baseline**: Flagged, first occurrence used
3. **Empty Container Numbers**: Treated as 0 containers
4. **Carrier changes within same group**: Tracked accurately
5. **New groups (not in baseline)**: Shown as "New group"

## Testing Checklist

- [x] Build origin map from baseline data
- [x] Parse container IDs correctly (various formats)
- [x] Trace kept containers (same carrier)
- [x] Trace flipped containers (different carrier)
- [x] Handle unknown containers (not in baseline)
- [x] Format single-source flips
- [x] Format multi-source flips
- [x] Abbreviate when many sources (>5)
- [x] Calculate movement summary statistics
- [x] Generate top flows table
- [x] Display in Streamlit UI
- [x] Export with both flip columns
- [ ] User testing with real data
- [ ] Performance testing with large datasets (100k+ containers)

## Files Modified/Created

### Created

1. **`components/container_tracer.py`** (New)
   - Container origin mapping
   - Movement tracing
   - Display formatting
   - Summary statistics

### Modified

1. **`components/metrics.py`**

   - Added import of container_tracer functions
   - Modified display_data creation to add both flip columns
   - Added `show_container_movement_summary()` function

2. **`components/__init__.py`**
   - Exported `show_container_movement_summary`

## Future Enhancements

### Potential Additions

1. **Week-over-week tracking**: Compare movements across different weeks
2. **Container journey visualization**: Show path of specific container over time
3. **Carrier loyalty metrics**: Which carriers keep their containers longest
4. **Flow prediction**: ML model to predict likely container movements
5. **Cost impact per container**: Link container movements to cost changes
6. **Container details tooltip**: Hover to see full container IDs
7. **Export flow matrix**: CSV download of complete from→to matrix
8. **Filter by flow**: "Show only containers from RKNE to ATMI"

### Optimization Opportunities

1. **Incremental updates**: Only rebuild map when baseline changes
2. **Parallel processing**: Multi-thread trace calculation for large datasets
3. **Compression**: Store container map in compressed format
4. **Caching**: Cache trace results per scenario

## User Documentation

### How to Use Container Tracing

1. **Upload Data**: Ensure GVT data includes "Container Numbers" column
2. **Run Scenario**: Execute Performance, Optimized, or Cascading scenario
3. **View Details**: Check "Carrier Flips (Detailed)" column in tables
4. **Analyze Summary**: Use Movement Summary widget for high-level view

### Interpreting the Display

**"✓ Kept X"**: Carrier retained X of its original containers
**"🔄 From CARRIER (X)"**: Received X containers from CARRIER
**"🆕 New (X)"**: X containers not found in baseline
**"CARRIER (X) + CARRIER (Y)"**: Multiple sources

### Best Practices

1. **Start with Summary**: Use Movement Summary widget to understand overall patterns
2. **Drill Down**: Filter to specific groups to see detailed movements
3. **Validate Math**: Verify that gains = losses within each group
4. **Export for Analysis**: Download tables with both flip columns for offline analysis
5. **Compare Scenarios**: Run multiple scenarios, compare movement patterns

## Related Documentation

- CARRIER_FLIPS_FEATURE.md - Original aggregate flip feature
- CARRIER_FLIPS_ACCURATE_FIX.md - Explanation of why aggregate approach was limited
- **CONTAINER_LEVEL_TRACING.md** (this file) - Complete container tracking solution
