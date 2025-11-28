"""
Analyze exported CSV to understand duplication source
"""
import pandas as pd
from collections import Counter

# Load the export file
export_path = r"C:\Users\maabdiac\Downloads\2025-11-26T15-32_export.csv"
df = pd.read_csv(export_path)

print("="*80)
print("ANALYZING EXPORTED DATA")
print("="*80)

# The 5 duplicate containers
target_containers = ['CAAU5277492', 'MEDU4597833', 'MSDU6022753', 'MSKU1591053', 'TCKU6034375']

print(f"\nTotal rows in export: {len(df)}")
print(f"Columns: {df.columns.tolist()}")

# Find rows containing these containers
print("\n" + "="*80)
print("ROWS CONTAINING DUPLICATE CONTAINERS")
print("="*80)

for tc in target_containers:
    mask = df['Container Numbers'].str.contains(tc, na=False)
    matches = df[mask]
    
    if len(matches) > 1:
        print(f"\n{tc} appears in {len(matches)} rows:")
        for idx, row in matches.iterrows():
            print(f"  Row {idx}: Carrier={row.get('Carrier', 'N/A')}, Lane={row.get('Lane', 'N/A')}, Week={row.get('Week Number', 'N/A')}, Category={row.get('Category', 'N/A')}")

# Check: Are these rows actually different groups, or the SAME group?
print("\n" + "="*80)
print("GROUP ANALYSIS - Are duplicates in SAME or DIFFERENT groups?")
print("="*80)

# Get rows 23 and 91 (mentioned in original issue)
if len(df) > 91:
    row23 = df.iloc[23]
    row91 = df.iloc[91]
    
    print("\nRow 23:")
    print(f"  Carrier: {row23.get('Carrier')}")
    print(f"  Lane: {row23.get('Lane')}")
    print(f"  Week Number: {row23.get('Week Number')}")
    print(f"  Category: {row23.get('Category')}")
    print(f"  Facility: {row23.get('Facility')}")
    print(f"  Terminal: {row23.get('Terminal')}")
    print(f"  Container Count: {row23.get('Container Count')}")
    
    print("\nRow 91:")
    print(f"  Carrier: {row91.get('Carrier')}")
    print(f"  Lane: {row91.get('Lane')}")
    print(f"  Week Number: {row91.get('Week Number')}")
    print(f"  Category: {row91.get('Category')}")
    print(f"  Facility: {row91.get('Facility')}")
    print(f"  Terminal: {row91.get('Terminal')}")
    print(f"  Container Count: {row91.get('Container Count')}")
    
    # Check if they are in the same group (same Lane, Week, Category, Facility, Terminal)
    same_group = (
        row23.get('Lane') == row91.get('Lane') and
        row23.get('Week Number') == row91.get('Week Number') and
        row23.get('Category') == row91.get('Category') and
        row23.get('Facility') == row91.get('Facility') and
        row23.get('Terminal') == row91.get('Terminal')
    )
    
    print(f"\nSame Group? {same_group}")
    
    if same_group:
        print("\n*** THE ISSUE: Two different carriers in the SAME group have overlapping containers! ***")
        print("This should NOT happen - containers should only appear once per group.")
        
        # Check container overlap
        containers_23 = set([c.strip() for c in str(row23.get('Container Numbers', '')).split(',') if c.strip()])
        containers_91 = set([c.strip() for c in str(row91.get('Container Numbers', '')).split(',') if c.strip()])
        
        overlap = containers_23 & containers_91
        print(f"\nContainer overlap between Row 23 (RKNE) and Row 91 (FRQT):")
        print(f"  Row 23 containers: {len(containers_23)}")
        print(f"  Row 91 containers: {len(containers_91)}")
        print(f"  Overlapping containers: {len(overlap)}")
        print(f"  Overlapping IDs: {sorted(overlap)}")
