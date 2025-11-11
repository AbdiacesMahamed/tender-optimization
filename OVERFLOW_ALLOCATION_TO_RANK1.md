# Overflow Container Allocation to Rank 1 Carrier

## Issue

When cascading allocation cannot distribute all containers due to growth constraints, remaining containers were left unallocated instead of being assigned to a carrier.

## Scenario

This happens when:

1. All carriers have historical allocations and have reached their max growth cap (e.g., 30% growth limit)
2. No new carriers are available to take cascaded volume
3. Remaining volume has nowhere to go

Example:

- Lane has 100 containers to allocate
- Carrier A (Rank 1): Historical 40% → Can take up to 52 containers (40 × 1.3)
- Carrier B (Rank 2): Historical 35% → Can take up to 45.5 containers (35 × 1.3)
- Carrier C (Rank 3): Historical 25% → Can take up to 32.5 containers (25 × 1.3)
- Total capacity: 130 containers (but only 100 to allocate)

BUT if the allocation logic tries to allocate 150 containers and all carriers are capped:

- Carrier A gets 52 (at cap)
- Carrier B gets 45.5 (at cap)
- Carrier C gets 32.5 (at cap)
- **20 containers remain unallocated**

## Solution

Added a **third pass** to the cascading allocation logic:

### Flow:

1. **First Pass**: Allocate to each carrier up to their historical + max_growth% cap
2. **Second Pass**: Try to cascade remaining volume to new carriers (no historical data)
3. **Third Pass (NEW)**: If volume still remains, assign it ALL to the **Rank 1 (best) carrier**

### Code Added:

```python
# Third pass: if volume still remains, assign to rank 1 (best) carrier
if remaining > 0.5 and sorted_carriers:  # Check for remaining (> 0.5 to handle rounding)
    best_carrier = sorted_carriers[0]  # Rank 1 carrier
    allocations[best_carrier] += remaining

    # Update notes to indicate overflow was assigned
    notes[best_carrier] = (
        f"Rank #{rank} | "
        f"Historical: {hist_pct:.1f}% → New: {new_pct:.1f}% | "
        f"Change: {change_pct:+.1f}% ({change_abs:+.0f} containers) | "
        f"⚠️ +{remaining:.0f} overflow containers assigned"
    )

    remaining = 0  # All volume now allocated
```

## Allocation Notes

The Rank 1 carrier's allocation notes will show:

**Format:**

```
Rank #1 | Historical: 40.0% → New: 65.0% | Change: +25.0% (+25 containers) | ⚠️ +20 overflow containers assigned
```

**Components:**

- Standard allocation info (rank, historical %, new %, change)
- **⚠️ Warning icon** to highlight overflow situation
- **Overflow count**: Shows how many additional containers were assigned beyond normal cascading

## Benefits

### Before:

❌ Containers could remain unallocated  
❌ Total allocation < total containers needed  
❌ No visibility into why allocation was incomplete

### After:

✅ All containers are always allocated  
✅ Best carrier (Rank 1) gets any overflow  
✅ Clear note indicates overflow assignment  
✅ User can see exactly how many overflow containers were assigned

## Why Rank 1 Carrier?

The Rank 1 carrier is chosen because:

1. **Best Performance**: Ranked #1 by LP optimization (best cost/performance balance)
2. **Most Reliable**: Typically the strongest carrier option
3. **Deterministic**: Always same carrier, no randomness
4. **Business Logic**: If we must exceed caps, best to do so with the best carrier

## Impact on Growth Constraints

- The Rank 1 carrier may exceed its max_growth% cap when overflow is assigned
- This is intentional - overflow must go somewhere, and Rank 1 is the best choice
- The warning icon ⚠️ clearly indicates this exceptional situation
- Users can see the overflow amount and decide if adjustment is needed

## Example Scenarios

### Scenario 1: All Carriers at Cap

```
Containers to allocate: 150
Carrier A (Rank 1): 52 + 20 overflow = 72 containers ⚠️
Carrier B (Rank 2): 45.5 containers (at cap)
Carrier C (Rank 3): 32.5 containers (at cap)
Total: 150 containers ✅
```

### Scenario 2: Normal Cascading (No Overflow)

```
Containers to allocate: 100
Carrier A (Rank 1): 52 containers (at cap)
Carrier B (Rank 2): 45.5 containers (at cap)
Carrier C (Rank 3): 2.5 containers (not at cap)
Total: 100 containers ✅ (no overflow needed)
```

## Files Modified

- `optimization/cascading_logic.py` - Added third pass for overflow allocation

## Date Applied

November 10, 2025

## Testing

After this change:

1. ✅ All containers are always allocated
2. ✅ Overflow goes to Rank 1 carrier
3. ✅ Allocation notes show overflow with ⚠️ warning
4. ✅ Overflow amount is clearly displayed
5. ✅ Container Count remains accurate
