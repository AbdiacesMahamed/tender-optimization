# Container Movement Flow Example

## Scenario: BAL Port, Week 46, USBALHIA1 Lane, HIA1 Facility, Retail CD

### BEFORE (Original Allocation)

```
┌─────────────────────────────────────────────────────────┐
│  Group: BAL + Week 46 + USBALHIA1 + HIA1 + Retail CD   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ATMI: [MSDU123, MSDU234, MSDU345, MSDU456]            │
│        4 containers                                      │
│                                                          │
│  RKNE: [TCKU111, TCKU222, TCKU333, TCKU444,            │
│         TCKU555, TCKU666, TCKU777, TCKU888,            │
│         TCKU999, TCKU000, TCKU101, TCKU202]            │
│        12 containers                                     │
│                                                          │
│  XPDR: [XPDR001, XPDR002, XPDR003, XPDR004,            │
│         XPDR005, XPDR006, XPDR007, XPDR008,            │
│         XPDR009, XPDR010]                               │
│        10 containers                                     │
│                                                          │
│  HDDR: [HDDR100, HDDR200, HDDR300, HDDR400,            │
│         HDDR500, HDDR600, HDDR700, HDDR800,            │
│         HDDR900]                                        │
│        9 containers                                      │
│                                                          │
│  TOTAL: 35 containers                                    │
└─────────────────────────────────────────────────────────┘
```

### AFTER (Optimized Scenario)

```
┌─────────────────────────────────────────────────────────┐
│  Group: BAL + Week 46 + USBALHIA1 + HIA1 + Retail CD   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ATMI: 17 containers                                     │
│  ├─ Kept:    [MSDU123, MSDU234, MSDU345, MSDU456]      │
│  │           4 containers (from ATMI)                    │
│  ├─ From RKNE: [TCKU111, TCKU222, TCKU333, TCKU444,    │
│  │              TCKU555, TCKU666, TCKU777, TCKU888]    │
│  │              8 containers                             │
│  ├─ From XPDR: [XPDR001, XPDR002, XPDR003]             │
│  │              3 containers                             │
│  └─ From HDDR: [HDDR100, HDDR200]                       │
│                 2 containers                             │
│                                                          │
│  Display: "✓ Kept 4, 🔄 From RKNE (8) + XPDR (3) +     │
│             HDDR (2)"                                    │
│                                                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  RKNE: 4 containers                                      │
│  └─ Kept:    [TCKU999, TCKU000, TCKU101, TCKU202]      │
│              4 containers (from RKNE)                    │
│                                                          │
│  Display: "✓ Had 12, now 4 (-8)"                        │
│                                                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  XPDR: 7 containers                                      │
│  └─ Kept:    [XPDR004, XPDR005, XPDR006, XPDR007,      │
│               XPDR008, XPDR009, XPDR010]                │
│              7 containers (from XPDR)                    │
│                                                          │
│  Display: "✓ Had 10, now 7 (-3)"                        │
│                                                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  HDDR: 7 containers                                      │
│  └─ Kept:    [HDDR300, HDDR400, HDDR500, HDDR600,      │
│               HDDR700, HDDR800, HDDR900]                │
│              7 containers (from HDDR)                    │
│                                                          │
│  Display: "✓ Had 9, now 7 (-2)"                         │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  TOTAL: 35 containers (conserved) ✓                      │
└─────────────────────────────────────────────────────────┘
```

### CONTAINER FLOWS

```
        BEFORE                    AFTER
        ======                    =====

        ATMI                      ATMI
         4 ────────────────────► 4 (kept)
                                   ↑
        RKNE                       │
        12 ────────────────────► 4 │
                   └────────────► 8 (to ATMI)
                                   ↑
        XPDR                       │
        10 ────────────────────► 7 │
                   └────────────► 3 (to ATMI)
                                   ↑
        HDDR                       │
         9 ────────────────────► 7 │
                   └────────────► 2 (to ATMI)

        35 total                  17 (ATMI total)
```

### VERIFICATION TABLE

| Carrier | Original | Kept   | From Others | Lost    | Final  | Balance |
| ------- | -------- | ------ | ----------- | ------- | ------ | ------- |
| ATMI    | 4        | 4      | +13         | 0       | 17     | +13     |
| RKNE    | 12       | 4      | 0           | -8      | 4      | -8      |
| XPDR    | 10       | 7      | 0           | -3      | 7      | -3      |
| HDDR    | 9        | 7      | 0           | -2      | 7      | -2      |
| **SUM** | **35**   | **22** | **+13**     | **-13** | **35** | **0**   |

✅ Total containers conserved (35 = 35)  
✅ Gains equal losses (+13 = -13)  
✅ All container movements accounted for

### HOW THE SYSTEM TRACKS THIS

1. **Origin Map Built (from GVT data):**

   ```python
   {
       'MSDU123': {'original_carrier': 'ATMI', 'week': 46, ...},
       'TCKU111': {'original_carrier': 'RKNE', 'week': 46, ...},
       'XPDR001': {'original_carrier': 'XPDR', 'week': 46, ...},
       ...
   }
   ```

2. **Current Allocation (from Optimized scenario):**

   ```
   ATMI: [MSDU123, MSDU234, MSDU345, MSDU456,
          TCKU111, TCKU222, TCKU333, TCKU444,
          TCKU555, TCKU666, TCKU777, TCKU888,
          XPDR001, XPDR002, XPDR003,
          HDDR100, HDDR200]
   ```

3. **For Each Container in ATMI:**

   - MSDU123 → origin: ATMI → **Kept**
   - MSDU234 → origin: ATMI → **Kept**
   - MSDU345 → origin: ATMI → **Kept**
   - MSDU456 → origin: ATMI → **Kept**
   - TCKU111 → origin: RKNE → **Flipped from RKNE**
   - TCKU222 → origin: RKNE → **Flipped from RKNE**
   - ... (6 more from RKNE)
   - XPDR001 → origin: XPDR → **Flipped from XPDR**
   - ... (2 more from XPDR)
   - HDDR100 → origin: HDDR → **Flipped from HDDR**
   - HDDR200 → origin: HDDR → **Flipped from HDDR**

4. **Aggregate:**

   - Kept: 4 (MSDU123, MSDU234, MSDU345, MSDU456)
   - From RKNE: 8 (TCKU111-TCKU888)
   - From XPDR: 3 (XPDR001-XPDR003)
   - From HDDR: 2 (HDDR100, HDDR200)

5. **Display:**
   ```
   ✓ Kept 4, 🔄 From RKNE (8) + XPDR (3) + HDDR (2)
   ```

### KEY INSIGHT

Every single container is traced individually from its original carrier to its current carrier. The system knows:

- **Which** container (MSDU123)
- **Original** carrier (ATMI)
- **Current** carrier (ATMI or other)
- **Week** number (46)
- **Full context** (Port, Lane, Facility, Terminal, Category)

This enables **100% accurate** tracking of container movements with full verification and traceability!
