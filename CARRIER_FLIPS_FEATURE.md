# Carrier Flips Feature

## Overview

Added a new "Carrier Flips" column to all data tables that shows who the original carrier was and how many containers they had, making it easy to track carrier allocation changes across different scenarios.

## What is "Carrier Flips"?

The **Carrier Flips** column displays:

- **Original carrier** who had the containers in "Current Selection" scenario
- **Number of containers** the original carrier had
- **Current carrier** after the scenario transformation
- **Visual indicators** for different types of changes

## Display Format

### 🔄 Carrier Flip - Single Source

```
🔄 From ATMI (50)
```

- Current carrier received 50 containers from ATMI
- Shows actual amount that flipped (not more than what ATMI had)

### 🔄 Carrier Flip - Multiple Sources

```
🔄 From HGDR (30) + ATMI (20)
```

- Current carrier received containers from multiple sources
- HGDR contributed 30 containers
- ATMI contributed 20 containers
- Total received: 50 containers

### ✓ Same Carrier, Volume Changed

```
✓ ATMI (50 → 75)
```

- Carrier: ATMI (same)
- Original volume: 50 containers
- New volume: 75 containers
- Volume increased but no flip occurred (carrier kept their containers and may have gained from others)

### ✓ No Change

```
✓ ATMI (unchanged)
```

- Carrier: ATMI (same)
- Volume: unchanged
- Completely identical allocation

### 🆕 New Allocation

```
🆕 New allocation
```

- New group that didn't exist in baseline
- First-time carrier assignment to this lane/facility/week combination

## Where It Appears

The Carrier Flips column appears in:

- ✅ **Current Selection** scenario table
- ✅ **Performance** scenario table
- ✅ **Optimized** scenario table
- ✅ **Constrained Data** table (if applicable)
- ✅ **Unconstrained Data** table

## Column Position

Carrier Flips appears after Container Numbers:

```
... | Container Numbers | Carrier Flips | Container Count | Base Rate | ...
```

## How It Works

### 1. Baseline Capture

When you load data, the system captures the "Current Selection" as the baseline:

```python
baseline_data = display_data_with_rates.copy()
```

### 2. Grouping Logic

Carrier allocations are compared at the group level:

- **Discharged Port** (e.g., BAL, LAX)
- **Category** (if present)
- **Lane** (e.g., USBALBJR1)
- **Facility** (e.g., BJR1)
- **Terminal** (if present)
- **Week Number** (e.g., 47)

### 3. Comparison

For each group in the current scenario, the system:

1. Looks up the original carrier allocation(s)
2. Identifies the primary original carrier (most containers)
3. Compares with current carrier
4. Generates the flip description

## Use Cases

### 📊 Scenario Analysis

**Question:** "Which carriers are being replaced in the Optimized scenario?"

**Answer:** Look for 🔄 indicators in Carrier Flips column:

```
🔄 From ATMI (150)           ← RTSC row: received 150 containers from ATMI
🔄 From HGDR (80)            ← RTSC row: received 80 containers from HGDR
🔄 From HGDR (30) + ATMI (20) ← XPOL row: received from 2 carriers
```

### 📈 Volume Growth Tracking

**Question:** "How did RTSC's volume change?"

**Answer:** Check entries for RTSC:

```
RTSC row shows:
🔄 From ATMI (100) + HGDR (80)  ← Gained 180 containers from others
Original: RTSC had 50 containers
New: RTSC has 230 containers (50 original + 180 gained)
```

### 🎯 Constraint Impact

**Question:** "What happened to carriers with Maximum constraints?"

**Answer:** Look at rows where max-constrained carriers previously had volume:

```
RTSC row: 🔄 From ATMI (100)     ← ATMI hit max, 100 containers moved to RTSC
HGDR row: 🔄 From ATMI (50)      ← ATMI hit max, 50 more containers moved to HGDR
```

### 🔍 Facility-Specific Changes

**Question:** "Which carrier changes happened at facility HGR6?"

**Answer:** Filter by Facility = HGR6, check Carrier Flips:

```
RTSC row: 🔄 From ATMI (25) + XPOL (15)  ← At HGR6, RTSC gained from 2 carriers
HGDR row: ✓ HGDR (unchanged)             ← At HGR6, no change
```

## Technical Implementation

### Files Modified

- **`components/metrics.py`**
  - Added `add_carrier_flips_column()` helper function
  - Added baseline_data capture
  - Integrated Carrier Flips column in display logic

### Key Functions

#### `add_carrier_flips_column(current_data, original_data, carrier_col)`

```python
def add_carrier_flips_column(current_data, original_data, carrier_col='Dray SCAC(FL)'):
    """
    Add 'Carrier Flips' column showing original carrier allocation changes.

    Parameters:
    -----------
    current_data : pd.DataFrame
        Current scenario data with potentially reallocated carriers
    original_data : pd.DataFrame
        Original "Current Selection" data before any scenario changes
    carrier_col : str
        Column name for carrier identification

    Returns:
    --------
    pd.DataFrame
        Data with added 'Carrier Flips' column
    """
```

**Logic:**

1. Determines grouping columns (port, lane, facility, week, category, terminal)
2. Creates original carrier map: `{group_key: [{'carrier': X, 'containers': Y}, ...]}`
3. For each row in current data:
   - Gets group key
   - Looks up original carrier(s)
   - Finds primary original carrier (most containers)
   - Compares with current carrier
   - Generates flip description with appropriate icon

### Performance Considerations

- ✅ Efficient dictionary lookup: O(1) per row
- ✅ Single pass through data
- ✅ No expensive joins or merges
- ✅ Minimal memory overhead

## Examples by Scenario

### Current Selection Scenario

All rows show "unchanged" since no transformation occurred:

```
✓ ATMI (unchanged)
✓ RTSC (unchanged)
✓ HGDR (unchanged)
```

### Performance Scenario

Shows carriers replaced by highest-performing carriers:

```
🔄 HGDR (100) → ATMI     ← ATMI has better performance
🔄 XPOL (50) → ATMI      ← ATMI has better performance
✓ ATMI (75 → 225)        ← ATMI gained volume
```

### Optimized Scenario

Shows LP optimization and cascading logic results:

```
🔄 ATMI (150) → RTSC     ← RTSC ranked #1 by LP
🔄 HGDR (80) → RTSC      ← RTSC ranked #1 by LP
✓ RTSC (100 → 330)       ← RTSC gained from optimization
✓ XPOL (growth constrained) ← XPOL hit 30% growth limit
```

## Filtering and Sorting Tips

### Find All Carrier Flips

**Filter:** Carrier Flips contains "🔄"
**Result:** Only rows where carrier changed

### Find Volume Changes (Same Carrier)

**Filter:** Carrier Flips contains "→" and not "🔄"  
**Result:** Only rows where volume changed but carrier stayed same

### Find Largest Flips

**Sort:** Extract container count from Carrier Flips, sort descending
**Example:**

```
🔄 ATMI (250) → RTSC    ← Largest flip
🔄 HGDR (150) → RTSC
🔄 XPOL (100) → ATMI
```

### Group by Gaining Carrier

**Group by:** Extract carrier after "→" symbol
**Example:** "Which carriers gained the most containers?"

```
RTSC: Gained from ATMI (250), HGDR (150) = 400 total
ATMI: Gained from XPOL (100) = 100 total
```

## Benefits

### 🎯 Transparency

- See exactly which carriers were replaced
- Understand the magnitude of each change
- Track container flows between carriers

### 📊 Decision Support

- Quickly identify major carrier shifts
- Assess impact of optimization strategies
- Validate constraint effects

### 🔍 Audit Trail

- Document why carrier allocations changed
- Explain scenario differences to stakeholders
- Support carrier negotiations with data

### 📈 Performance Tracking

- Monitor carrier volume trends
- Identify winners and losers in each scenario
- Analyze market share shifts

## Future Enhancements

Potential additions to Carrier Flips functionality:

1. **Flip Summary Statistics**

   - Total containers flipped
   - Number of unique carriers affected
   - Average flip size

2. **Flip Reasons**

   - "Flipped due to: Better Performance"
   - "Flipped due to: Lower Cost"
   - "Flipped due to: Carrier Constraint"

3. **Multi-Scenario Comparison**

   - Compare flips across Performance vs Optimized
   - Show flip patterns over time

4. **Flip Cost Impact**

   - "Cost saved by flip: $X,XXX"
   - "Performance gained: +X%"

5. **Export Flip Report**
   - Dedicated flip analysis CSV
   - Summary by carrier/lane/facility

## Troubleshooting

### "No baseline data" appears

**Cause:** Baseline data not captured properly  
**Solution:** Ensure data loads completely before switching scenarios

### "Unable to group" appears

**Cause:** Missing required grouping columns  
**Solution:** Check that Port, Lane, Facility, Week Number exist in data

### Flips show incorrect carriers

**Cause:** Grouping mismatch between baseline and scenario  
**Solution:** Verify all grouping columns match between datasets

### Performance impact with large datasets

**Cause:** add_carrier_flips_column processing time  
**Solution:** Function is optimized; if issues persist, consider caching baseline_data

## Summary

The **Carrier Flips** column provides crucial visibility into carrier allocation changes across scenarios, making it easy to:

- ✅ Track which carriers won/lost volume
- ✅ Understand the magnitude of changes
- ✅ Validate scenario results
- ✅ Support data-driven carrier negotiations

The feature works seamlessly across all scenarios and requires no additional user configuration.
