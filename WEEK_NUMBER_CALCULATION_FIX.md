# Week Number Calculation Fix

## Issue
Dashboard was showing 24 containers for BAL Week 47, but Excel showed 49 containers.

## Root Cause
The dashboard was calculating week numbers using Python's `dt.isocalendar().week` (ISO 8601 standard with Monday as first day of week), while the Excel file used `=WEEKNUM()` formula (Sunday as first day of week).

This caused dates in mid-November to be assigned to different weeks:
- **11/16/2025** → Python: Week 46, Excel: Week 47
- **11/17/2025** → Python: Week 46, Excel: Week 47  
- **11/18/2025** → Python: Week 47, Excel: Week 47

Result: Python only counted containers with Ocean ETA = 11/18/2025 (24 containers), while Excel counted all three dates (49 containers).

## Solution
Updated `components/data_processor.py` to match Excel's WEEKNUM calculation:

1. **First Priority**: Use existing `WK num` column from Excel if available (already calculated with =WEEKNUM formula)
2. **Fallback**: Calculate week number using Sunday-Saturday weeks to match Excel:
   ```python
   # Excel WEEKNUM with return_type=1: weeks start on SUNDAY
   # Python equivalent: strftime('%U') + 1
   GVTdata['Week Number'] = GVTdata['Ocean ETA'].apply(
       lambda x: int(x.strftime('%U')) + 1 if pd.notna(x) else None
   )
   ```

## Files Modified
- `components/data_processor.py` - Updated `validate_and_process_gvt_data()` function
- `debug_gvt_analyzer.py` - Updated to use same calculation method

## Result
✅ Dashboard now correctly shows all 49 containers for BAL Week 47
✅ Week calculations match Excel exactly
✅ Standalone analyzer confirms: "COUNT MATCHES! Excel has 49, we found 49"

## Date
November 12, 2025
