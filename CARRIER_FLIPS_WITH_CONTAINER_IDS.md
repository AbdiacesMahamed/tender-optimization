# Carrier Flips with Container IDs - Final Format

## What Was Updated

The "Carrier Flips" column now includes **actual container IDs** inline with each number, making it easy to see exactly which containers are involved in each part of the transaction.

## New Format

```
Had X [container IDs] → From CARRIER (+Y) [container IDs], Lost Z [container IDs] → Now Total
```

## Real Examples

### Example 1: Carrier Gained from ATMI, Lost Some

```
Had 6 [DFSU6511932, MEDU8816098, DFSU6693185... (6 total)]
→ From ATMI (+2) [FFAU4219005, MSMU6552430], Lost 3 [DFSU6693185, MEDU8816098, FFEU7906145]
→ Now 5
```

**What this shows:**

- **Had 6**: Originally had 6 containers (first 3 IDs shown)
- **From ATMI (+2)**: Gained 2 containers from ATMI (both IDs shown: FFAU4219005, MSMU6552430)
- **Lost 3**: Lost 3 containers (all 3 IDs shown)
- **Now 5**: Currently has 5 containers total (6 + 2 - 3 = 5)

### Example 2: Carrier Gained from Multiple Sources

```
Had 67 [CAUU4652204, MEDU7794374, MEDU7914926... (67 total)]
→ From FROT (+2) [MSBU9026757, SEGU6238066] + XPDR (+3) [TLLU4477493, TLLU4576351...]
→ Now 72
```

**What this shows:**

- **Had 67**: Started with 67 containers
- **From FROT (+2)**: Gained 2 from FROT (both IDs shown)
- **From XPDR (+3)**: Gained 3 from XPDR (first 2 IDs shown, "..." indicates more)
- **Now 72**: Total is now 72 (67 + 2 + 3 = 72)

### Example 3: Kept All Containers

```
Had 3 [TLLU4477493, TLLU4576351, UESU5049608] (kept all) → Now 3
```

**What this shows:**

- **Had 3**: Started with 3 containers (all IDs shown)
- **(kept all)**: No changes occurred
- **Now 3**: Still has the same 3 containers

### Example 4: New Carrier to Group

```
Had 0 → From HDDR (+9) [CMAU5866142, CMAU6292840, CMAU7367158...] → Now 9
```

**What this shows:**

- **Had 0**: Carrier wasn't in this group originally
- **From HDDR (+9)**: Received 9 containers from HDDR (first 3 IDs shown)
- **Now 9**: Currently has 9 containers

## Container ID Display Rules

### For "Had X"

- Shows up to **3 container IDs**
- If more than 3: shows "... (X total)"
- Example: `Had 10 [MSDU123, TCKU456, XPDR789... (10 total)]`

### For "From CARRIER (+Y)"

- Shows up to **2 container IDs** per carrier
- If more than 2: shows "..."
- Example: `From RKNE (+5) [TCKU111, TCKU222...]`

### For "Lost Z"

- Shows up to **2 container IDs**
- If more than 2: shows "... (Z total)"
- Example: `Lost 8 [MSDU345, MSDU456... (8 total)]`

### For "Now X"

- **No container IDs shown** (as requested)
- Just shows the final count
- Example: `→ Now 17`

## Benefits

### ✅ Complete Transparency

You can see the actual container IDs involved in each part:

- Which containers were originally allocated
- Which specific containers came from which carrier
- Which containers were lost/moved away

### ✅ Easy Verification

- Click on a container ID to search for it
- Verify the container movements match your records
- Trace specific containers through the system

### ✅ Compact Display

- Container IDs are inline (not on separate lines)
- Only shows first few IDs to keep it readable
- Indicates total count when abbreviated

### ✅ Clear Attribution

Each gain shows exactly which carrier it came from:

```
From RKNE (+3) [TCKU111, TCKU222, TCKU333]
```

You know TCKU111, TCKU222, and TCKU333 all came from RKNE

## Comparison: Before vs After

### BEFORE (Without Container IDs)

```
Had 6 → From ATMI (+2), Lost 3 → Now 5
```

❌ You know the counts but not WHICH containers

### AFTER (With Container IDs)

```
Had 6 [DFSU6511932, MEDU8816098, DFSU6693185... (6 total)]
→ From ATMI (+2) [FFAU4219005, MSMU6552430], Lost 3 [DFSU6693185, MEDU8816098, FFEU7906145]
→ Now 5
```

✅ You can see EXACTLY which containers are involved

## Technical Details

### How It Works

1. **Original Container Tracking**: System stores which containers each carrier had originally in each group
2. **Movement Detection**: For each current row, compares current containers against original
3. **Source Attribution**: Looks up origin of each container to determine source carrier
4. **Loss Calculation**: Original containers NOT in current list = lost containers
5. **Inline Display**: Formats everything into one readable line

### Container Limit Logic

- Limits shown to keep column readable
- Full lists would make cells too large
- Abbreviated with "..." when exceeding limits
- Total count always shown for context

### Performance

- No performance impact (container IDs already loaded)
- All data comes from existing trace_result
- Formatting is string concatenation (very fast)

## Use Cases

### Use Case 1: Verify Specific Container Movement

**Question**: "Did container MSDU123456 move from ATMI to RKNE?"

**Answer**: Look at RKNE's row:

```
Had 10 [...] → From ATMI (+5) [MSDU123456, TCKU789...] → Now 15
```

✅ Yes! MSDU123456 is shown in the "From ATMI" section.

### Use Case 2: Track Lost Container

**Question**: "Where did container DFSU6693185 go?"

**Answer**: Look at the original carrier's row:

```
Had 6 [DFSU6511932, MEDU8816098, DFSU6693185...]
→ Lost 3 [DFSU6693185, MEDU8816098, FFEU7906145]
→ Now 3
```

✅ DFSU6693185 is in the "Lost" section - it went to another carrier.

Then search other rows for "DFSU6693185" to see who received it.

### Use Case 3: Audit Container Allocation

**Question**: "Show me all containers in this group and their movements."

**Answer**: Read through each carrier's flip column:

- Carrier A: Had [list] → From B [list], Lost [list] → Now X
- Carrier B: Had [list] → From C [list] → Now Y
- etc.

You can verify that all containers are accounted for and movements are logical.

## Tips for Reading

1. **Start with "Had"**: This shows the baseline
2. **Check gains**: "From CARRIER (+X)" shows what was received
3. **Check losses**: "Lost X" shows what was given away
4. **Verify math**: Had + Gains - Losses = Now
5. **Trace specific containers**: Search for container ID across rows

## Export Friendly

When you export to Excel:

- Container IDs are in the same cell (easy to copy)
- Can use Excel's Find function to search for specific containers
- Format is preserved in CSV/Excel exports
- Can parse with text functions if needed

## Summary

The updated "Carrier Flips" column now provides:

- ✅ Original count with container IDs
- ✅ Gains with source carrier and container IDs
- ✅ Losses with container IDs
- ✅ Final count (no IDs to keep it clean)
- ✅ Inline format (everything in one line)
- ✅ Abbreviated when needed (keeps cells readable)
- ✅ Complete traceability for every container

You can now see exactly which containers moved where! 🎯
