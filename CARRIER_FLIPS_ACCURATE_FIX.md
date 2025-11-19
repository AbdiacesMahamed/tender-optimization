# Carrier Flips - Accurate Calculation Fix

## Date

November 19, 2025

## Problem Identified

The previous Carrier Flips calculation was showing misleading information. For example:

```
✓ Had 4 + from RKNE (12) + XPDR (10) + HDDR (9) + ARVY (8) + FROT (8) = 5
```

This display suggested:

- ATMI had 4 originally
- ATMI gained 12 from RKNE, 10 from XPDR, 9 from HDDR, etc.
- The total should be 4+12+10+9+8+8 = 51, but it shows 5

**The Fundamental Issue**: The numbers shown (12, 10, 9, 8, 8) were what those carriers HAD originally in the group, NOT how much ATMI gained from each of them.

## Root Cause Analysis

### What We Know

For each group (Port+Category+Lane+Facility+Terminal+Week), we know:

- **Original allocation**: Which carriers had how many containers
- **Current allocation**: Which carriers have how many containers now

Example for one group:

```
Original:
- RKNE: 12 containers
- XPDR: 10 containers
- HDDR: 9 containers
- ARVY: 8 containers
- FROT: 8 containers
- ATMI: 4 containers
Total: 51 containers

Current:
- ATMI: 5 containers
- Other carriers: 46 containers (distributed somehow)
Total: 51 containers
```

### What We DON'T Know

We **cannot trace which specific containers moved between which carriers**. The data doesn't include:

- Container-level tracking (Container ID → Old Carrier → New Carrier)
- Flow matrices (how many moved from Carrier A to Carrier B)
- Allocation decision logs

We only have aggregate before/after snapshots per carrier per group.

### Why the Previous Display Was Wrong

The code showed: "Had 4 + from RKNE (12) + XPDR (10)..."

This implies ATMI gained:

- 12 containers from RKNE
- 10 containers from XPDR
- etc.

But those numbers (12, 10) are what RKNE and XPDR HAD originally, not what ATMI gained from them!

**Reality**: ATMI went from 4 to 5 (gained 1 container total). That 1 container could have come from:

- All from RKNE (RKNE lost 1)
- All from XPDR (XPDR lost 1)
- Partial from multiple carriers
- We have NO WAY to know!

## The Accurate Solution

Show only what we **know for certain** - each carrier's before/after totals:

### Display Formats

1. **Carrier kept containers (no change)**

   ```
   ✓ Kept 12
   ```

2. **Carrier gained containers**

   ```
   ✓ Had 4, now 5 (+1)
   ```

   - We know: gained 1 container
   - We DON'T know: from which carrier(s)

3. **Carrier lost containers**

   ```
   ✓ Had 12, now 8 (-4)
   ```

   - We know: lost 4 containers
   - We DON'T know: to which carrier(s)

4. **Carrier is new to group**

   ```
   🔄 New: 5 (was RKNE, XPDR, HDDR)
   ```

   - Shows carrier wasn't in this group originally
   - Lists who WAS in the group (for context)
   - Doesn't claim to know how much came from each

5. **Entirely new group**
   ```
   🆕 New group
   ```

## Code Changes

### Before (Incorrect)

```python
# Showed what OTHER carriers had originally
other_carriers = [(c, cnt) for c, cnt in orig_group.items()
                 if c != curr_carrier and cnt > 0]
other_str = ' + '.join([f"{c} ({cnt:.0f})" for c, cnt in other_carriers])
flips.append(f"✓ Had {orig_own_count:.0f} + from {other_str} = {curr_count:.0f}")
```

This was misleading - those counts weren't what the current carrier gained!

### After (Accurate)

```python
# Show only before/after for THIS carrier
diff = curr_count - orig_own_count
if diff > 0:
    flips.append(f"✓ Had {orig_own_count:.0f}, now {curr_count:.0f} (+{diff:.0f})")
```

Simple, clear, accurate: shows only verifiable facts.

## User Benefit

The new display:

- ✅ **Accurate**: Only shows what we can prove from the data
- ✅ **Clear**: Easy to understand before/after changes
- ✅ **Honest**: Doesn't imply knowledge we don't have
- ✅ **Useful**: Shows gains/losses per carrier, which is what matters for analysis

Users can:

- See which carriers gained/lost containers in each group
- Quantify the magnitude of changes (+5, -3, etc.)
- Identify which carriers were newly assigned to groups
- Make informed decisions based on accurate information

## Example Comparison

### Before (Misleading)

```
ATMI: ✓ Had 4 + from RKNE (12) + XPDR (10) + HDDR (9) = 5
```

Problem: Implies ATMI gained 12+10+9=31 containers, but total is only 5!

### After (Accurate)

```
ATMI: ✓ Had 4, now 5 (+1)
```

Clear: ATMI had 4, now has 5, gained 1 container.

### Other Carriers in Same Group

```
RKNE: ✓ Had 12, now 10 (-2)
XPDR: ✓ Had 10, now 9 (-1)
HDDR: ✓ Had 9, now 9 (✓ Kept 9)
ARVY: ✓ Had 8, now 7 (-1)
FROT: ✓ Had 8, now 11 (+3)
```

Now users can see:

- Total gained: +1 (ATMI) + +3 (FROT) = +4
- Total lost: -2 (RKNE) - 1 (XPDR) - 1 (ARVY) = -4
- Net change: 0 ✓ (containers conserved within group)

This makes sense and is verifiable!

## Testing Checklist

- [ ] ATMI example: Should show "✓ Had 4, now 5 (+1)"
- [ ] Verify no carrier shows impossible math (gained > available)
- [ ] Check new carriers show "🔄 New: X (was [carriers])"
- [ ] Verify carriers that lost containers show negative changes
- [ ] Confirm group totals are conserved (gains = losses)
- [ ] Test edge cases: single carrier groups, new groups, empty groups

## Files Modified

- `components/metrics.py` - Rewrote `add_carrier_flips_column()` function (lines ~59-157)

## Related Documentation

- CARRIER_FLIPS_FEATURE.md - Initial feature implementation
- CARRIER_FLIPS_LOGIC_FIX.md - First bug fix (same-carrier flips, capacity limits)
- CARRIER_FLIPS_SECOND_FIX.md - Second fix (per-group comparison)
- **CARRIER_FLIPS_ACCURATE_FIX.md** (this file) - Final accurate calculation
