# Updated Carrier Flips Column - Format Examples

## New Single Column Format

The "Carrier Flips" column now **always shows**:

1. **What carrier started with** (original count)
2. **What changed** (gains from which carriers, losses)
3. **What carrier has now** (current count)

## Format Pattern

```
Had X → [Changes] → Now Y
```

## Real Examples

### Example 1: Carrier Gained from Multiple Sources

```
Had 4 → From RKNE (+8) + XPDR (+3) + HDDR (+2) → Now 17
```

**Meaning:**

- Started with: 4 containers
- Gained 8 from RKNE
- Gained 3 from XPDR
- Gained 2 from HDDR
- Current total: 17 containers
- **Math check: 4 + 8 + 3 + 2 = 17 ✓**

### Example 2: Carrier Lost Containers

```
Had 12 → Lost 8 → Now 4
```

**Meaning:**

- Started with: 12 containers
- Lost 8 containers (went to other carriers)
- Current total: 4 containers
- **Math check: 12 - 8 = 4 ✓**

### Example 3: Carrier Lost Some, Gained Some

```
Had 12 → From XPDR (+3), Lost 5 → Now 10
```

**Meaning:**

- Started with: 12 containers
- Gained 3 from XPDR
- Lost 5 to other carriers
- Current total: 10 containers
- **Math check: 12 + 3 - 5 = 10 ✓**

### Example 4: No Change

```
Had 10 (kept all) → Now 10
```

**Meaning:**

- Started with: 10 containers
- Kept all of them
- No gains or losses
- Current total: 10 containers

### Example 5: New Carrier to Group

```
Had 0 → From RKNE (+12) + XPDR (+10) → Now 22
```

**Meaning:**

- Started with: 0 containers (wasn't in this group originally)
- Gained 12 from RKNE
- Gained 10 from XPDR
- Current total: 22 containers
- **Math check: 0 + 12 + 10 = 22 ✓**

### Example 6: Gained from Single Source

```
Had 5 → From ATMI (+3) → Now 8
```

**Meaning:**

- Started with: 5 containers
- Gained 3 from ATMI
- Current total: 8 containers
- **Math check: 5 + 3 = 8 ✓**

### Example 7: Many Sources (Abbreviated)

```
Had 2 → From RKNE (+8) + XPDR (+5) + HDDR (+4) + ARVY (+3) + FROT (+2) + 3 others (+6) → Now 30
```

**Meaning:**

- Started with: 2 containers
- Gained from 8 different carriers (top 5 shown + "3 others")
- Current total: 30 containers
- **Math check: 2 + 8 + 5 + 4 + 3 + 2 + 6 = 30 ✓**

## Comparison: Old vs New

### OLD FORMAT (Two Columns)

| Carrier Flips         | Carrier Flips (Detailed)                         |
| --------------------- | ------------------------------------------------ |
| ✓ Had 4, now 17 (+13) | ✓ Kept 4, 🔄 From RKNE (8) + XPDR (3) + HDDR (2) |

**Issues:**

- Two columns cluttered the display
- Original count only in first column
- Detailed column didn't show original count

### NEW FORMAT (One Column)

| Carrier Flips                                           |
| ------------------------------------------------------- |
| Had 4 → From RKNE (+8) + XPDR (+3) + HDDR (+2) → Now 17 |

**Benefits:**

- ✅ Single, clean column
- ✅ **Always** shows what carrier started with
- ✅ Shows exact sources and amounts
- ✅ Shows final total
- ✅ Math is clear and verifiable

## Your Data Example

Based on the screenshot you shared, here's what you'll see:

**BAL, Retail CD, Week 46, HIA1, TRM-SEAGIRT:**

| Carrier | Container Count | Carrier Flips                               |
| ------- | --------------- | ------------------------------------------- |
| ARVY    | 11              | Had 8 → From ATMI (+2) + XPDR (+1) → Now 11 |
| HDDR    | 12              | Had 4 → From RKNE (+8) → Now 12             |
| FROT    | 10              | Had 5 → From HDDR (+5) → Now 10             |
| ATMI    | 5               | Had 4 → From FROT (+3), Lost 2 → Now 5      |
| RKNE    | 13              | Had 4 → From XPDR (+9) → Now 13             |

**Now you can see:**

- ARVY started with 8, gained from ATMI and XPDR
- HDDR started with 4, gained 8 from RKNE
- FROT started with 5, gained 5 from HDDR
- ATMI started with 4, gained 3 from FROT but lost 2 to others
- RKNE started with 4, gained 9 from XPDR

**Every row clearly shows the starting point and what changed!**

## Key Advantages

1. **Complete Story in One Column**

   - No need to look at multiple columns
   - All information in one place

2. **Always Shows Original Count**

   - "Had X" appears in every row
   - You always know the baseline

3. **Clear Change Attribution**

   - "+8" means gained 8
   - "Lost 5" means lost 5
   - "From RKNE (+3)" means gained 3 from RKNE

4. **Math Always Verifiable**

   - Start + Gains - Losses = Current
   - You can verify every row

5. **Cleaner Export**
   - One column to export
   - Easier to work with in Excel
   - More readable in reports

## Implementation

This is now active in your dashboard:

- Single "Carrier Flips" column
- Shows original count, changes, and current total
- Applies to all scenarios (Performance, Optimized, Cascading)
- Automatically calculated from Container Numbers column

Ready to use! 🎯
