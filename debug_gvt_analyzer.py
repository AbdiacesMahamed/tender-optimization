"""
Standalone GVT Data Analyzer
This script reads the GVT Excel file directly and analyzes container data
for BAL Week 47 based on Ocean ETA to verify data extraction
"""

import pandas as pd
import sys
from pathlib import Path

def analyze_gvt_data(gvt_file_path):
    """Analyze GVT data for BAL Week 47 containers"""
    
    print("=" * 80)
    print("GVT DATA ANALYZER - BAL WEEK 47")
    print("=" * 80)
    
    try:
        # Read the Excel file
        print(f"\n📂 Reading Excel file: {gvt_file_path}")
        gvt_data = pd.read_excel(gvt_file_path)
        print(f"✅ Successfully loaded {len(gvt_data)} rows")
        
        # Show available columns
        print(f"\n📋 Available columns in Excel file:")
        for i, col in enumerate(gvt_data.columns, 1):
            print(f"  {i}. {col}")
        
        # Check for Ocean ETA column
        ocean_eta_col = None
        for col in gvt_data.columns:
            if 'ocean' in col.lower() and 'eta' in col.lower():
                ocean_eta_col = col
                break
        
        if ocean_eta_col:
            print(f"\n✅ Found Ocean ETA column: '{ocean_eta_col}'")
        else:
            print(f"\n⚠️  No 'Ocean ETA' column found. Looking for date columns...")
            date_cols = [col for col in gvt_data.columns if 'date' in col.lower() or 'eta' in col.lower()]
            if date_cols:
                print(f"   Date-related columns found: {date_cols}")
                ocean_eta_col = date_cols[0]
                print(f"   Using: '{ocean_eta_col}'")
        
        # Calculate Week Number from Ocean ETA if available
        if ocean_eta_col and ocean_eta_col in gvt_data.columns:
            print(f"\n🔍 Calculating Week Number from '{ocean_eta_col}'...")
            gvt_data[ocean_eta_col] = pd.to_datetime(gvt_data[ocean_eta_col], errors='coerce')
            
            # Match Excel's WEEKNUM formula: weeks start on Sunday, first week contains Jan 1
            # Python strftime '%U' gives week number with Sunday as first day (0-indexed)
            # Add 1 to match Excel's 1-indexed week numbers
            gvt_data['Calculated_Week'] = gvt_data[ocean_eta_col].apply(
                lambda x: int(x.strftime('%U')) + 1 if pd.notna(x) else None
            )
            
            print(f"✅ Week numbers calculated (using Excel WEEKNUM logic: Sunday-Saturday weeks)")
            print(f"   Unique weeks in data: {sorted(gvt_data['Calculated_Week'].dropna().unique())}")
        
        # Check for existing Week Number column
        week_col = None
        # First check for exact "WK num" column
        if 'WK num' in gvt_data.columns:
            week_col = 'WK num'
        else:
            # Try variations
            for col in gvt_data.columns:
                if 'week' in col.lower() and ('number' in col.lower() or 'num' in col.lower()):
                    week_col = col
                    break
        
        if week_col:
            print(f"\n📊 Found existing Week Number column: '{week_col}'")
            print(f"   Unique weeks: {sorted(gvt_data[week_col].dropna().unique())}")
        
        # Determine which week column to use - PREFER the existing WK num column!
        analysis_week_col = week_col if week_col else ('Calculated_Week' if ocean_eta_col and 'Calculated_Week' in gvt_data.columns else None)
        
        if not analysis_week_col:
            print("\n❌ ERROR: No week column available for analysis")
            return
        
        print(f"\n🎯 Using '{analysis_week_col}' for Week 47 analysis")
        
        # Filter to Week 47
        wk47_data = gvt_data[gvt_data[analysis_week_col] == 47].copy()
        print(f"\n📦 Total Week 47 rows (all ports): {len(wk47_data)}")
        
        if len(wk47_data) == 0:
            print("⚠️  No data found for Week 47")
            return
        
        # Check for Discharged Port or Lane column to identify BAL
        bal_identifier = None
        if 'Discharged Port' in gvt_data.columns:
            bal_identifier = 'Discharged Port'
            bal_wk47 = wk47_data[wk47_data['Discharged Port'] == 'BAL'].copy()
        elif 'Lane' in gvt_data.columns:
            bal_identifier = 'Lane'
            bal_wk47 = wk47_data[wk47_data['Lane'].str.startswith('BAL', na=False)].copy()
        else:
            print("\n❌ ERROR: Cannot identify BAL port (no 'Discharged Port' or 'Lane' column)")
            return
        
        print(f"\n🎯 Using '{bal_identifier}' to identify BAL")
        print(f"📍 Total BAL Week 47 rows: {len(bal_wk47)}")
        
        if len(bal_wk47) == 0:
            print("⚠️  No BAL data found for Week 47")
            return
        
        # Check for Container column (priority order)
        container_col = None
        # Check exact match first
        if 'Container' in gvt_data.columns:
            container_col = 'Container'
        else:
            # Try variations
            for col in gvt_data.columns:
                if 'container' in col.lower():
                    container_col = col
                    break
        
        if not container_col:
            print("\n❌ ERROR: No container column found")
            print("   Available columns with 'container':", [c for c in gvt_data.columns if 'container' in c.lower()])
            return
        
        print(f"\n📦 Using container column: '{container_col}'")
        
        # Analyze containers
        print(f"\n" + "=" * 80)
        print(f"🎯 CONTAINER COUNT ANALYSIS - WHY NOT 49?")
        print("=" * 80)
        
        all_container_ids = []
        row_details = []
        
        print(f"\n📋 Parsing Container Numbers from each row:")
        print("-" * 80)
        
        for idx, row in bal_wk47.iterrows():
            container_str = row[container_col]
            
            if pd.notna(container_str) and str(container_str).strip():
                # Parse container IDs
                ids = [c.strip() for c in str(container_str).split(',') if c.strip()]
                all_container_ids.extend(ids)
                
                # Collect row details
                carrier = row.get('Dray SCAC(FL)', row.get('Carrier', 'N/A'))
                facility = row.get('Facility', 'N/A')
                
                # Show each row's containers
                print(f"Row {idx}: {carrier} | {facility} → {len(ids)} containers")
                if len(ids) <= 10:
                    print(f"         IDs: {', '.join(ids)}")
                else:
                    print(f"         IDs: {', '.join(ids[:10])}... (showing first 10)")
                
                row_details.append({
                    'Row': idx,
                    'Carrier': carrier,
                    'Facility': facility,
                    'Container_Count': len(ids),
                    'All_IDs': ids
                })
        
        # Summary statistics
        total_containers = len(all_container_ids)
        unique_containers = len(set(all_container_ids))
        duplicate_containers = total_containers - unique_containers
        
        print(f"\n" + "=" * 80)
        print(f"📊 FINAL COUNT:")
        print("=" * 80)
        print(f"   Excel says: 49 containers")
        print(f"   We counted: {total_containers} container IDs")
        print(f"   Unique IDs: {unique_containers}")
        print(f"   Duplicates: {duplicate_containers}")
        print()
        
        if total_containers == 49:
            print("✅ COUNT MATCHES! Excel has 49, we found 49")
        else:
            print(f"❌ MISMATCH! Excel says 49, but we found {total_containers}")
            print()
            if total_containers < 49:
                print(f"⚠️  MISSING {49 - total_containers} CONTAINERS")
                print("   Possible reasons:")
                print("   1. Some rows have empty Container Numbers")
                print("   2. Week calculation is different than Excel")
                print("   3. BAL identification is filtering out rows")
            elif total_containers > 49:
                print(f"⚠️  FOUND {total_containers - 49} EXTRA CONTAINERS")
                print("   Possible reasons:")
                print("   1. Duplicate container IDs across rows")
                print("   2. Week calculation includes extra rows")
        
        print()
        print("=" * 80)
        
        # Show duplicates if any
        if duplicate_containers > 0:
            print(f"\n⚠️  DUPLICATE CONTAINERS FOUND:")
            from collections import Counter
            container_counts = Counter(all_container_ids)
            duplicates = {cid: count for cid, count in container_counts.items() if count > 1}
            for cid, count in sorted(duplicates.items(), key=lambda x: x[1], reverse=True):
                print(f"   - {cid}: appears {count} times")
        
        # Show all unique container IDs
        print(f"\n� ALL CONTAINER IDS FOUND ({len(set(all_container_ids))} unique):")
        print("-" * 80)
        unique_ids = sorted(set(all_container_ids))
        for i in range(0, len(unique_ids), 5):
            batch = unique_ids[i:i+5]
            print("   " + ", ".join(batch))
        
        # Check if any rows have empty container numbers
        empty_rows = bal_wk47[bal_wk47[container_col].isna() | (bal_wk47[container_col].astype(str).str.strip() == '')]
        if len(empty_rows) > 0:
            print(f"\n⚠️  WARNING: {len(empty_rows)} BAL Week 47 rows have EMPTY Container Numbers!")
            print(f"   These rows are NOT being counted:")
            for idx, row in empty_rows.iterrows():
                carrier = row.get('Dray SCAC(FL)', row.get('Carrier', 'N/A'))
                facility = row.get('Facility', 'N/A')
                print(f"   Row {idx}: {carrier} | {facility} → NO CONTAINERS")
        
        # Group by Lane, Carrier, Facility
        print(f"\n" + "=" * 80)
        print(f"🔍 GROUPBY SIMULATION - What the dashboard does:")
        print("=" * 80)
        
        grouping_cols = []
        if 'Lane' in bal_wk47.columns:
            grouping_cols.append('Lane')
        if 'Dray SCAC(FL)' in bal_wk47.columns:
            grouping_cols.append('Dray SCAC(FL)')
        if 'Facility' in bal_wk47.columns:
            grouping_cols.append('Facility')
        
        if len(grouping_cols) > 0:
            grouped = bal_wk47.groupby(grouping_cols)
            
            print(f"\nGrouping by: {', '.join(grouping_cols)}")
            print(f"Number of groups created: {len(grouped)}")
            print()
            
            group_details = []
            
            for group_key, group_df in grouped:
                # Collect all containers in this group
                group_containers = []
                for cn in group_df[container_col]:
                    if pd.notna(cn) and str(cn).strip():
                        ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                        group_containers.extend(ids)
                
                rows_in_group = len(group_df)
                containers_in_group = len(group_containers)
                unique_in_group = len(set(group_containers))
                
                group_details.append({
                    'key': group_key if isinstance(group_key, tuple) else (group_key,),
                    'rows': rows_in_group,
                    'containers': containers_in_group,
                    'unique': unique_in_group
                })
                
                # Show group details
                if isinstance(group_key, tuple):
                    key_str = " | ".join(str(k) for k in group_key)
                else:
                    key_str = str(group_key)
                
                print(f"Group: {key_str}")
                print(f"   Excel rows in this group: {rows_in_group}")
                print(f"   Containers in group: {containers_in_group}")
                print(f"   Unique containers: {unique_in_group}")
                
                # Dashboard uses .size() which counts ROWS, not containers
                print(f"   ⚠️  Dashboard .size() would count: {rows_in_group} (WRONG!)")
                print(f"   ✅  Should count: {unique_in_group} (actual unique containers)")
                print()
            
            # Summary
            total_after_groupby = sum(d['rows'] for d in group_details)
            print("=" * 80)
            print("📊 GROUPBY IMPACT:")
            print(f"   Original Excel rows: {len(bal_wk47)}")
            print(f"   After groupby: {len(grouped)} groups")
            print(f"   Dashboard .size() sum: {total_after_groupby}")
            print(f"   Actual container count: {len(set(all_container_ids))}")
            print()
            if total_after_groupby != len(set(all_container_ids)):
                print(f"   ❌ MISMATCH: .size() gives {total_after_groupby}, but there are {len(set(all_container_ids))} unique containers")
                print(f"   🔧 FIX: Dashboard should count actual container IDs, not use .size()")
        else:
            print("\n⚠️  Cannot simulate groupby - missing grouping columns")
        
        # Export to CSV for further analysis
        output_file = Path(gvt_file_path).parent / "bal_week_47_debug_export.csv"
        bal_wk47.to_csv(output_file, index=False)
        print(f"\n💾 Exported BAL Week 47 data to: {output_file}")
        
        # Create summary report
        summary_file = Path(gvt_file_path).parent / "bal_week_47_summary.txt"
        with open(summary_file, 'w') as f:
            f.write("BAL WEEK 47 CONTAINER ANALYSIS SUMMARY\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Total rows: {len(bal_wk47)}\n")
            f.write(f"Total container IDs: {total_containers}\n")
            f.write(f"Unique container IDs: {unique_containers}\n")
            f.write(f"Duplicate container IDs: {duplicate_containers}\n\n")
            f.write("UNIQUE CONTAINER LIST:\n")
            f.write("-" * 80 + "\n")
            for cid in sorted(set(all_container_ids)):
                f.write(f"{cid}\n")
        
        print(f"💾 Saved summary to: {summary_file}")
        
        print("\n" + "=" * 80)
        print("✅ ANALYSIS COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Default file path - BAL GVT test file
    default_path = r"C:\Users\maabdiac\Downloads\BAL GVT 11.11.xlsx"
    
    # Allow command line argument for file path
    if len(sys.argv) > 1:
        gvt_file = sys.argv[1]
    else:
        print("Usage: python debug_gvt_analyzer.py <path_to_gvt_file>")
        print(f"\nNo file specified. Using default path:")
        print(f"  {default_path}")
        
        # Check if default file exists
        if Path(default_path).exists():
            gvt_file = default_path
        else:
            print(f"\n❌ Default file not found. Please provide file path:")
            print("   python debug_gvt_analyzer.py 'C:\\path\\to\\your\\GVT.xlsx'")
            sys.exit(1)
    
    analyze_gvt_data(gvt_file)
