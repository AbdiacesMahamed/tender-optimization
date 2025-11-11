# Growth Limit Display in Allocation Notes

## Change
Modified the allocation notes to always show the growth limit percentage instead of just the "(cascaded)" keyword. This provides better transparency about the growth constraints being applied.

## Previous Behavior

**Carriers with historical data (at cap):**
```
Rank #2 | Historical: 35.0% → New: 45.5% | Change: +10.5% (+10 containers) (capped at 30% growth)
```

**New carriers (cascaded):**
```
Rank #3 | Historical: 0% (new carrier) → New: 15.0% | Allocated: 15 containers (cascaded)
```

## New Behavior

**Carriers with historical data (at cap):**
```
Rank #2 | Historical: 35.0% → New: 45.5% | Change: +10.5% (+10 containers) (capped at 30% growth)
```
*No change - already showed growth limit*

**New carriers (at growth limit):**
```
Rank #3 | Historical: 0% (new carrier) → New: 30.0% | Allocated: 30 containers (at 30% growth limit)
```

**New carriers (cascaded, not at limit):**
```
Rank #3 | Historical: 0% (new carrier) → New: 15.0% | Allocated: 15 containers (cascaded, limit 30%)
```

**New carriers (first pass, not at limit):**
```
Rank #3 | Historical: 0% (new carrier) → New: 10.0% | Allocated: 10 containers (limit 30%)
```

## Changes Made

### 1. First Pass - New Carriers
**Before:**
- Showed: "Allocated: X containers"
- No growth limit information

**After:**
- If at limit: "Allocated: X containers (at 30% growth limit)"
- If below limit: "Allocated: X containers (limit 30%)"

### 2. Second Pass - Cascaded Volume to New Carriers
**Before:**
- Showed: "Allocated: X containers (cascaded)"
- No growth limit information

**After:**
- If at limit: "Allocated: X containers (at 30% growth limit)"
- If below limit: "Allocated: X containers (cascaded, limit 30%)"

### 3. Carriers with Historical Data
**No change** - Already showed growth limit when capped:
- "Change: +X% (Y containers) (capped at 30% growth)"

## Benefits

### Transparency
✅ Users always see the growth constraint in effect  
✅ Clear indication of whether carrier hit the limit  
✅ Consistent messaging across all allocation scenarios  

### Better Decision Making
✅ Users can quickly see which carriers are maxed out  
✅ Easy to identify if growth limits should be adjusted  
✅ Clear understanding of allocation constraints  

### Examples

#### Example 1: New Carrier at Growth Limit
```
Growth Limit: 30%
Total Containers: 100
New Carrier Allocation: 30 containers (30%)

Note: "Rank #1 | Historical: 0% (new carrier) → New: 30.0% | Allocated: 30 containers (at 30% growth limit)"
```

#### Example 2: New Carrier Below Growth Limit
```
Growth Limit: 30%
Total Containers: 100
New Carrier Allocation: 10 containers (10%)

Note: "Rank #2 | Historical: 0% (new carrier) → New: 10.0% | Allocated: 10 containers (limit 30%)"
```

#### Example 3: Cascaded to New Carrier
```
Growth Limit: 30%
Total Containers: 100
New Carrier gets 15 cascaded containers (15%)

Note: "Rank #3 | Historical: 0% (new carrier) → New: 15.0% | Allocated: 15 containers (cascaded, limit 30%)"
```

#### Example 4: Existing Carrier at Cap
```
Growth Limit: 30%
Historical: 40%
New Allocation: 52% (40% × 1.30)

Note: "Rank #1 | Historical: 40.0% → New: 52.0% | Change: +12.0% (+12 containers) (capped at 30% growth)"
```

## Growth Limit Types

The growth limit is applied differently based on carrier type:

### Existing Carriers (Has Historical Data)
- **Limit**: `historical_pct × (1 + max_growth_pct)`
- **Example**: If historical = 40% and growth = 30%, max = 52%
- **Note**: Shows "capped at X% growth" when at limit

### New Carriers (No Historical Data)
- **Limit**: `max_growth_pct × 100`
- **Example**: If growth = 30%, max = 30% of total
- **Note**: Shows "at X% growth limit" or "limit X%" depending on context

## Code Changes

### Location
`optimization/cascading_logic.py` - `_cascade_allocate_volume()` function

### Modified Sections
1. First pass allocation notes for new carriers
2. Second pass cascaded allocation notes for new carriers

## Date Applied
November 10, 2025

## Related Documentation
- `OVERFLOW_ALLOCATION_TO_RANK1.md` - Overflow allocation logic
- `HISTORICAL_PCT_VERIFICATION.md` - Historical percentage calculation
