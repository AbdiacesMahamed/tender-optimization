# Container Tracing - Quick Reference

## What You Asked For

✅ **"trace carrier container and week number so we can know exactly which carrier the container came from"**  
✅ **"see the original carrier and what volume was given to the new carrier"**

## What You Got

### New Column: "Carrier Flips (Detailed)"

Shows **exact container sources** for each carrier in each row.

### Example Outputs

```
✓ Kept 4, 🔄 From RKNE (8) + XPDR (3) + HDDR (2)
```

**Meaning:**

- Carrier kept 4 of its own original containers
- Received 8 containers from RKNE
- Received 3 containers from XPDR
- Received 2 containers from HDDR
- **Total: 4 + 8 + 3 + 2 = 17 containers**

```
✓ Had 12, now 10 (-2)
```

**Meaning:**

- Carrier had 12 containers originally
- Now has 10 containers
- Lost 2 containers (went to other carriers)

```
🔄 From RKNE (12) + XPDR (10)
```

**Meaning:**

- Carrier had 0 containers originally in this group
- Now has 22 containers (12 from RKNE + 10 from XPDR)

## How to Use

1. **Run your Streamlit dashboard**
2. **Upload data** (must have "Container Numbers" column)
3. **Run any scenario** (Performance, Optimized, Cascading)
4. **Look at the new column** "Carrier Flips (Detailed)"

## What Makes This Different

### Before (Old "Carrier Flips")

```
✓ Had 4, now 5 (+1)
```

❌ You gain 1 container, but from who?

### After (New "Carrier Flips (Detailed)")

```
✓ Kept 4, 🔄 From RKNE (1)
```

✅ You kept your 4, and got 1 from RKNE!

## Reading the Symbols

| Symbol | Meaning                                  |
| ------ | ---------------------------------------- |
| ✓      | Carrier was in group originally          |
| 🔄     | Containers that flipped between carriers |
| 🆕     | New container or new group               |

## Math Verification

The numbers **always add up**:

```
ATMI: ✓ Kept 4, 🔄 From RKNE (8) = 4 + 8 = 12 total
RKNE: ✓ Had 12, now 4 (-8)
```

✅ ATMI gained 8 from RKNE  
✅ RKNE lost 8  
✅ Math checks out!

## Bonus: Movement Summary

Optional function `show_container_movement_summary()` shows:

- Total kept vs flipped percentages
- Top 10 carrier-to-carrier flows
- Visual bar chart
- Insights ("78% stayed with original carrier")

## Files

### Created

- `components/container_tracer.py` - Core tracing logic
- `CONTAINER_LEVEL_TRACING.md` - Full technical docs
- `CONTAINER_TRACING_SUMMARY.md` - Detailed user guide
- `test_tracer_simple.py` - Test suite (✅ all passed)

### Modified

- `components/metrics.py` - Added detailed flip column
- `components/__init__.py` - Exported new functions

## Ready to Use!

Everything is integrated and tested. Your dashboard now shows:

- **Original carrier** for each container
- **Exact volume** moved between carriers
- **Week number** context preserved
- **Full traceability** of every container movement

🎯 **You now have complete visibility into container movements!**
