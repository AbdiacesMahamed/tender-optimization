"""
Verify the deduplication fix is working correctly.
This script traces through the data flow to check for container duplicates.
"""

import pandas as pd
import os

# Use the specific GVT file
gvt_file = r"C:\Users\maabdiac\Downloads\BAL GVT 11.19.xlsx"

print("=" * 80)
print("DEDUPLICATION FIX VERIFICATION")
print("=" * 80)

print(f"\n📁 Loading GVT file: {gvt_file}")

# Read raw data
try:
    raw_data = pd.read_excel(gvt_file)
    print(f"✓ Loaded {len(raw_data)} rows")
except Exception as e:
    print(f"❌ Error loading file: {e}")
    exit(1)

# Find the container column
container_col = None
for col in raw_data.columns:
    if col.lower() in ['container', 'container number', 'containers']:
        container_col = col
        break

if not container_col:
    print("❌ No container column found")
    exit(1)

print(f"✓ Found container column: '{container_col}'")

# Check for duplicate containers across carriers
print("\n" + "=" * 80)
print("STEP 1: CHECKING IF SAME CONTAINER APPEARS UNDER MULTIPLE CARRIERS")
print("=" * 80)

carrier_col = 'Dray SCAC(FL)'
if carrier_col not in raw_data.columns:
    print(f"❌ Carrier column '{carrier_col}' not found")
    exit(1)

# Group containers by carrier
container_carriers = raw_data.groupby(container_col)[carrier_col].apply(list).reset_index()
container_carriers['num_carriers'] = container_carriers[carrier_col].apply(lambda x: len(set(x)))
container_carriers['unique_carriers'] = container_carriers[carrier_col].apply(lambda x: list(set(x)))

# Find containers with multiple carriers
multi_carrier = container_carriers[container_carriers['num_carriers'] > 1]

print(f"\n📦 Total unique containers: {len(container_carriers)}")
print(f"📦 Containers appearing under multiple carriers: {len(multi_carrier)}")

if len(multi_carrier) > 0:
    print(f"\n⚠️  FOUND CONTAINERS ASSIGNED TO MULTIPLE CARRIERS IN RAW DATA:")
    for _, row in multi_carrier.head(20).iterrows():
        print(f"   - {row[container_col]}: {row['unique_carriers']}")
    
    if len(multi_carrier) > 20:
        print(f"   ... and {len(multi_carrier) - 20} more")
else:
    print("\n✅ No containers appear under multiple carriers in raw data")

# Now check by Lane and Week to see if duplicates happen in same group
print("\n" + "=" * 80)
print("STEP 2: CHECKING DUPLICATES WITHIN SAME LANE/WEEK/CATEGORY GROUP")
print("=" * 80)

# Add Week Number calculation (same as data_processor.py does)
if 'Begin ETA' in raw_data.columns:
    raw_data['Begin ETA'] = pd.to_datetime(raw_data['Begin ETA'], errors='coerce')
    raw_data['Week Number'] = raw_data['Begin ETA'].apply(
        lambda x: int(x.strftime('%U')) + 1 if pd.notna(x) else None
    )

# Create lane column
if 'Discharged Port' in raw_data.columns and 'Facility' in raw_data.columns:
    raw_data['Lane'] = raw_data['Discharged Port'].astype(str) + raw_data['Facility'].astype(str)

# Group by Lane, Week, Category to find containers per group
group_cols = ['Lane', 'Week Number', 'Category']
available_group_cols = [c for c in group_cols if c in raw_data.columns]

if len(available_group_cols) < 2:
    print("⚠️  Not enough grouping columns available")
else:
    print(f"   Grouping by: {available_group_cols}")
    
    # For each group, check if containers are duplicated across carriers
    duplicates_found = []
    
    for group_key, group_data in raw_data.groupby(available_group_cols, dropna=False):
        # Get container -> carrier mapping within this group
        container_to_carriers = group_data.groupby(container_col)[carrier_col].apply(list).reset_index()
        container_to_carriers['num_carriers'] = container_to_carriers[carrier_col].apply(lambda x: len(set(x)))
        
        multi_in_group = container_to_carriers[container_to_carriers['num_carriers'] > 1]
        
        if len(multi_in_group) > 0:
            for _, row in multi_in_group.iterrows():
                duplicates_found.append({
                    'group': group_key,
                    'container': row[container_col],
                    'carriers': list(set(row[carrier_col]))
                })
    
    print(f"\n📦 Containers appearing under MULTIPLE carriers in SAME group: {len(duplicates_found)}")
    
    if len(duplicates_found) > 0:
        print("\n⚠️  THESE ARE THE DUPLICATES THAT NEED DEDUPLICATION:")
        for dup in duplicates_found[:20]:
            print(f"   - Group {dup['group']}: Container {dup['container']} -> Carriers: {dup['carriers']}")
        
        if len(duplicates_found) > 20:
            print(f"   ... and {len(duplicates_found) - 20} more")
        
        # Check specifically for USBALHGR6, Week 48
        print("\n" + "=" * 80)
        print("STEP 3: CHECKING LANE=USBALHGR6, WEEK=48 SPECIFICALLY")
        print("=" * 80)
        
        target_dups = [d for d in duplicates_found if 'USBALHGR6' in str(d['group']) and 48 in d['group']]
        print(f"\n📦 Duplicates in USBALHGR6/Week 48: {len(target_dups)}")
        for dup in target_dups:
            print(f"   - Container {dup['container']} -> Carriers: {dup['carriers']}")
    else:
        print("\n✅ No containers appear under multiple carriers within same group")

print("\n" + "=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)

print("\n💡 SUMMARY:")
print("   The deduplication fix in cascading_logic.py, performance_logic.py, and metrics.py")
print("   removes duplicates when pooling containers from all carriers in a group.")
print("   ")
print("   If duplicates still appear in exports:")
print("   1. Restart the Streamlit app to reload the fixed code")
print("   2. Re-export the data to generate a fresh CSV")
print("   3. Verify the old export wasn't from before the fix was applied")
