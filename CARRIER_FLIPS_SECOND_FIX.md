# Carrier Flips - Second Logic Fix

## The Problem You Identified

**Your Example:**

```
Group: BAL + Retail CD + USBALHIA1 + HIA1 + Week 46
Carrier Flips showed: 🔄 From RKNE (3) + XPDR (2) + HDDR (1) + ARVY (1) + FRQT (1)
ATMI currently has: 17 containers

Question: "ATMI had 4 containers originally. Flips show 8 came from others (3+2+1+1+1=8).
So ATMI should have 4+8=12, but has 17. Where did the extra 5 come from?"
```

## Root Cause

The previous logic was **comparing carriers globally** instead of **within each specific group**.

**Wrong approach:**

- "How many containers does ATMI have across all groups?"
- "How many did ATMI gain from other carriers across all groups?"

**Correct approach:**

- "Within THIS SPECIFIC GROUP (BAL+Retail CD+USBALHIA1+HIA1+Week 46), who had containers?"
- "Within THIS GROUP, how did the allocation change?"

## The Fix

### New Logic Flow

For each row in the current scenario:

1. **Identify the group** (Port + Category + Lane + Facility + Terminal + Week)

   ```
   Group Key: (BAL, Retail CD, USBALHIA1, HIA1, TRM-SEAGIRT, 46)
   ```

2. **Look up original state for THIS GROUP**

   ```
   Original state of this group:
   - RKNE: 3 containers
   - XPDR: 2 containers
   - HDDR: 1 container
   - ARVY: 1 container
   - FRQT: 1 container
   - ATMI: 4 containers  [KEY: ATMI WAS ALREADY HERE]
   - (others...)
   Total in group: 17 containers
   ```

3. **Check current carrier's presence in original**

   - **If carrier had 0 originally** → Complete flip, show "🔄 Was [original carriers]"
   - **If carrier had some originally** → Partial change, show "✓ Had X + from [others] = Y"

4. **Generate description**

   ```
   ATMI had 4 originally in this group
   ATMI now has 17 in this group
   Other carriers originally had: 13 (3+2+1+1+1+5...)

   Result: ✓ Had 4 + from RKNE (3) + XPDR (2) + HDDR (1) + ARVY (1) + FRQT (1) + [others] = 17
   ```

## New Display Format

### ✓ Carrier Was Already in Group

**Format 1: No change**

```
✓ Kept 4
```

- Carrier had 4, still has 4
- Nothing changed in this group

**Format 2: Gained from others in same group**

```
✓ Had 4 + from RKNE (3) + XPDR (2) = 9
```

- Carrier had 4 originally in this group
- Gained 5 more from other carriers in this group
- Now has 9 total in this group

**Format 3: Lost containers**

```
✓ Had 10, now 5 (-5)
```

- Carrier had 10 in this group
- Now has only 5
- Lost 5 containers (went to other carriers or disappeared)

### 🔄 Carrier Was NOT in Group

**Format 1: Single source**

```
🔄 Was RKNE (8), now ATMI
```

- ATMI had 0 in this group originally
- ALL 8 containers came from RKNE
- Complete carrier flip

**Format 2: Multiple sources**

```
🔄 From RKNE (3) + XPDR (2) + HDDR (1)
```

- ATMI had 0 in this group originally
- Received from 3 different carriers
- Total: 6 containers from others

### 🆕 New Group

```
🆕 New
```

- This group (Port+Lane+Facility+Week combination) didn't exist in original data

## Code Changes

### Key Difference in Logic

**OLD CODE (WRONG):**

```python
# Was calculating globally across all groups
original_current_carrier_count = original_carriers.get(current_carrier, 0)
containers_from_others = current_containers - original_current_carrier_count

# This was WRONG because it looked at carrier's total across ALL groups,
# not just THIS specific group
```

**NEW CODE (CORRECT):**

```python
# Build state PER GROUP
original_state = {}
for _, row in original_data.iterrows():
    key = tuple(row.get(col, '') for col in group_cols)  # GROUP KEY
    carrier = row.get(carrier_col, 'Unknown')
    count = row.get('Container Count', 0)

    if key not in original_state:
        original_state[key] = {}
    original_state[key][carrier] = original_state[key].get(carrier, 0) + count

# Now we check THIS GROUP's original state
orig_group = original_state[key]  # Get original state for THIS group
orig_own_count = orig_group.get(curr_carrier, 0)  # Carrier's count in THIS group
```

## Your Example - Correct Output

**Group:** BAL + Retail CD + USBALHIA1 + HIA1 + TRM-SEAGIRT + Week 46

**Original state:**

```
RKNE: 3
XPDR: 2
HDDR: 1
ARVY: 1
FRQT: 1
ATMI: 4  ← ATMI was here
[Others that sum to remaining]: ?
Total: 17
```

**Current state:**

```
ATMI: 17 (all containers)
```

**Correct Carrier Flips output:**

```
✓ Had 4 + from RKNE (3) + XPDR (2) + HDDR (1) + ARVY (1) + FRQT (1) [+ others (5)] = 17
```

Or more simply:

```
✓ Had 4, now 17 (+13 from others)
```

This makes it clear that:

- ATMI already had 4 containers in this specific group
- ATMI gained 13 more containers from other carriers in this group
- Total: 4 + 13 = 17 ✓

## Why This Matters

### Problem with Global Comparison

If we compare globally (across all groups):

- ATMI might have had 50 containers total across all facilities
- But in THIS specific facility+week, ATMI had only 4
- We need to show what happened IN THIS GROUP, not globally

### Group-Level Accuracy

Each group is independent:

```
Group 1 (HIA1, Week 46):
  Original: ATMI (4), RKNE (3), XPDR (2)
  Current: ATMI (17)
  Flip: ✓ Had 4, gained from others

Group 2 (HGR6, Week 46):
  Original: ATMI (10), HGDR (5)
  Current: HGDR (15)
  Flip: 🔄 Was ATMI (10) + HGDR (5), now HGDR
```

Each group shows what happened IN THAT SPECIFIC PORT+LANE+FACILITY+WEEK combination.

## Testing with Your Data

Based on your Excel screenshot showing:

```
Market: ORF/EWR
Terminal: TRM-SEAGIRT
Port: BAL
Facility: HIA1
Carrier: ATMI
Week: Multiple rows
```

The function will now:

1. Group by (Market, Terminal, Port, Facility, Week)
2. For each group, check ATMI's original count IN THAT GROUP
3. Show accurate flip information per group

## Summary

✅ **Fixed:** Carrier flips now calculated per group, not globally  
✅ **Fixed:** Math now adds up correctly (original + gained = current)  
✅ **Fixed:** Shows "Had X + from others = Y" when carrier was already in group  
✅ **Fixed:** Shows "Was [carriers]" only when carrier was NOT in group originally

The key insight: **Carrier allocations are per group (Port+Lane+Facility+Week), not global.**
