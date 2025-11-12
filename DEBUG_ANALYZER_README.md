# GVT Data Debug Analyzer

## Purpose

This standalone script reads your GVT Excel file directly and analyzes BAL Week 47 container data to verify what's actually in the file.

## Key Features

✅ **Week Number Calculation**: Uses Ocean ETA column to calculate week numbers (ISO week standard)
✅ **Container Analysis**: Counts actual container IDs from Container Numbers column
✅ **Duplicate Detection**: Identifies if container IDs appear multiple times
✅ **Grouping Preview**: Shows what happens when data is grouped (simulates the dashboard's groupby operation)
✅ **Row-by-Row Breakdown**: Detailed view of each row with Lane, Carrier, Facility, and container counts
✅ **Export**: Saves BAL Week 47 data to CSV and creates a summary text file

## How to Run

### Option 1: Command Line with File Path

```powershell
cd "c:\Users\maabdiac\Downloads\Python Excel Scripts\Tender Optimization"
python debug_gvt_analyzer.py "C:\path\to\your\GVT.xlsx"
```

### Option 2: Using Default Path

The script has a default path configured. If your GVT file is at:

```
C:\Users\maabdiac\Downloads\Python Excel Scripts\Tender Optimization\data\GVT.xlsx
```

Just run:

```powershell
python debug_gvt_analyzer.py
```

### Option 3: Drag and Drop

1. Open PowerShell in the Tender Optimization folder
2. Type: `python debug_gvt_analyzer.py ` (with a space at the end)
3. Drag your GVT Excel file onto the PowerShell window
4. Press Enter

## What It Shows

### 1. File Loading

```
📂 Reading Excel file: C:\path\to\GVT.xlsx
✅ Successfully loaded 1234 rows
```

### 2. Available Columns

Lists all columns found in the Excel file

### 3. Ocean ETA Analysis

```
✅ Found Ocean ETA column: 'Ocean ETA'
🔍 Calculating Week Number from 'Ocean ETA'...
✅ Week numbers calculated
   Unique weeks in data: [40, 41, 42, 43, 44, 45, 46, 47, 48, 49]
```

### 4. Week 47 Lanes

```
🚢 Unique Lanes in Week 47:
   - BAL-CHI4: 5 rows
   - BAL-IND1: 3 rows
   - LAX-CHI4: 10 rows
   ...
```

### 5. BAL Week 47 Summary

```
📊 SUMMARY:
   Total rows: 12
   Total container IDs: 49
   Unique container IDs: 49
   Duplicate container IDs: 0
```

### 6. Row-by-Row Breakdown

Shows each row with Lane, Port, Carrier, Facility, and container count

### 7. All Container IDs

Lists every unique container ID found

### 8. Grouping Analysis

Shows what happens when rows are grouped (simulates dashboard groupby):

```
Group: BAL-CHI4 | ATMI | CHI4
   Rows in group: 3
   Total containers: 15
   Unique containers: 15
   Container IDs: CONT001, CONT002, CONT003, ...
```

## Output Files

The script creates two files in the same directory as your GVT file:

1. **`bal_week_47_debug_export.csv`**

   - Complete BAL Week 47 data exported to CSV
   - Can be opened in Excel for further analysis

2. **`bal_week_47_summary.txt`**
   - Text summary with all unique container IDs
   - Easy to compare with expected list

## What to Look For

### ✅ Expected Result (49 containers)

```
Total container IDs: 49
Unique container IDs: 49
Duplicate container IDs: 0
```

### ⚠️ Problem: Only 24 containers in Excel

```
Total container IDs: 24
Unique container IDs: 24
Duplicate container IDs: 0
```

**Cause**: Excel file only has 24 containers, not 49

### ⚠️ Problem: Duplicates reducing count

```
Total container IDs: 49
Unique container IDs: 24
Duplicate container IDs: 25
```

**Cause**: Same containers appearing multiple times in different rows

### ⚠️ Problem: Grouping combines rows

```
Grouping Analysis:
   Number of groups: 4

Group: BAL-CHI4 | ATMI | CHI4
   Rows in group: 3  ← Multiple rows
   Total containers: 15
```

**Cause**: Multiple Excel rows with same Lane/Carrier/Facility are being grouped together

## Troubleshooting

### Issue: "No Ocean ETA column found"

- Script will look for any date-related columns
- Check the output for "Date-related columns found"
- Verify your Excel has a date column

### Issue: "No data found for Week 47"

- Check the week calculation is correct
- Verify Ocean ETA dates fall in Week 47
- May need to use a different week column

### Issue: "No BAL data found for Week 47"

- Check Lane column format
- Ensure lanes start with "BAL"
- Look at "Unique Lanes in Week 47" output

## Next Steps

After running this script:

1. **Verify Container Count**: Does it show 49 containers as expected?
2. **Check for Duplicates**: Are there duplicate container IDs?
3. **Review Grouping**: How many groups are created? Do they match dashboard?
4. **Compare Output**: Use the summary.txt file to compare with your expected list

Share the output with the developer to help identify where containers are being lost.

## Requirements

- Python 3.x
- pandas
- openpyxl (for reading Excel files)

Install if needed:

```powershell
pip install pandas openpyxl
```
