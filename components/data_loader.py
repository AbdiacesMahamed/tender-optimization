"""
Data loading and processing module for the Carrier Tender Optimization Dashboard
"""
import pandas as pd
import numpy as np
import streamlit as st
from .config_styling import section_header, info_box, success_box

def show_file_upload_section():
    """Display file upload interface"""
    section_header("📁 Upload Your Data")
    
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("**GVT Data**")
        gvt_file = st.file_uploader(
            "Upload GVT Data Excel file", 
            type=['xlsx', 'xls'],
            key="gvt_upload"
        )

    with col2:
        st.markdown("**Rate Data**")
        rate_file = st.file_uploader(
            "Upload Rate Data Excel file", 
            type=['xlsx', 'xls'],
            key="rate_upload"
        )

    with col3:
        st.markdown("**Performance Data**")
        performance_file = st.file_uploader(
            "Upload Performance Data Excel file", 
            type=['xlsx', 'xls'],
            key="performance_upload"
        )
    
    with col4:
        st.markdown("**Constraints Data**")
        constraints_file = st.file_uploader(
            "Upload Constraints Excel file", 
            type=['xlsx', 'xls'],
            key="constraints_upload"
        )
    
    return gvt_file, rate_file, performance_file, constraints_file

@st.cache_data(show_spinner=False)
def _load_excel_file(file_bytes, file_name):
    """Cache Excel file loading to avoid re-reading on every interaction"""
    import io
    return pd.read_excel(io.BytesIO(file_bytes))

def load_data_files(gvt_file, rate_file, performance_file):
    """Load data from uploaded files or use defaults"""
    if gvt_file is not None and rate_file is not None:
        # Use uploaded files - automatically detect sheets
        try:
            with st.spinner('📂 Loading GVT data...'):
                # Cache file reading using file bytes as key
                GVTdata = _load_excel_file(gvt_file.read(), gvt_file.name)
                gvt_file.seek(0)  # Reset file pointer for potential re-reads
                
        except Exception as e:
            st.error(f"❌ Error reading GVT file: {str(e)}")
            st.stop()
        
        try:
            with st.spinner('📂 Loading Rate data...'):
                # Cache file reading using file bytes as key
                Ratedata = _load_excel_file(rate_file.read(), rate_file.name)
                rate_file.seek(0)  # Reset file pointer
                
        except Exception as e:
            st.error(f"❌ Error reading Rate file: {str(e)}")
            st.stop()
        
        # Performance data is optional
        if performance_file is not None:
            try:
                with st.spinner('📂 Loading Performance data...'):
                    Performancedata = _load_excel_file(performance_file.read(), performance_file.name)
                    performance_file.seek(0)  # Reset file pointer
                    has_performance = True
                    
            except Exception as e:
                st.warning(f"⚠️ Error reading Performance file: {str(e)}. Continuing without performance data.")
                Performancedata = None
                has_performance = False
        else:
            has_performance = False
        
        return GVTdata, Ratedata, Performancedata if has_performance else None, has_performance
        
    elif gvt_file is not None or rate_file is not None:
        st.warning("⚠️ Please upload both GVT Data and Rate Data files to proceed. Performance Data is optional.")
        st.stop()
    else:
        # Show message that users need to upload files when deployed
        st.info("👋 Welcome! Please upload your Excel files above to get started.")
        st.info("📋 Required files: GVT Data and Rate Data. Performance Data is optional.")
        st.stop()

@st.cache_data(show_spinner=False)
def process_performance_data(Performancedata, has_performance):
    """Process performance data if available - ONLY handles raw data cleaning, NO business logic calculations"""
    if not has_performance or Performancedata is None:
        return None, False
    
    try:
        # Your data structure: Carrier, Metrics, WK27, WK28, WK29, WK30, etc.
        performance_clean = Performancedata.copy()
        
        # Clean up column names by removing trailing spaces
        performance_clean.columns = performance_clean.columns.str.strip()
        
        # Filter for 'Total Score %' metrics only (your data shows this in Metrics column)
        if 'Metrics' in performance_clean.columns:
            performance_clean = performance_clean[performance_clean['Metrics'] == 'Total Score %'].copy()
        
        # Find week columns (WK27, WK28, WK29, WK30, etc.)
        week_columns = []
        for col in performance_clean.columns:
            if col.upper().startswith('WK') and len(col) > 2:
                try:
                    # Extract week number (WK27 -> 27)
                    week_num = int(col[2:])
                    week_columns.append(col)
                except ValueError:
                    continue
        
        if not week_columns:
            st.warning("⚠️ No week columns (WK27, WK28, etc.) found in performance data.")
            return None, False
        
        # Create week mapping (WK27 -> 27, WK28 -> 28, etc.)
        week_mapping = {}
        for col in week_columns:
            week_num = int(col[2:])
            week_mapping[col] = week_num
        
        # Melt the performance data to long format
        performance_melted = performance_clean.melt(
            id_vars=['Carrier'],
            value_vars=week_columns,
            var_name='Week_Column',
            value_name='Performance_Score'
        )
        
        # Map week column names to week numbers
        performance_melted['Week Number'] = performance_melted['Week_Column'].map(week_mapping)
        
        # Clean up performance scores and convert to proper decimal format
        def clean_performance_score(value):
            """Convert performance score to decimal (0.80 for 80%)"""
            if pd.isna(value) or value == '':
                return None
            
            # Convert to string and clean
            str_value = str(value).strip().replace('%', '')
            
            if str_value == '' or str_value.lower() == 'nan':
                return None
            
            try:
                numeric_value = float(str_value)
                
                # If the value is already between 0 and 1, it's likely already in decimal format
                if 0 <= numeric_value <= 1:
                    return numeric_value
                # If the value is between 1 and 100, it's likely a percentage that needs conversion
                elif 1 < numeric_value <= 100:
                    return numeric_value / 100
                # If the value is greater than 100, something might be wrong, but try to convert
                else:
                    st.warning(f"⚠️ Unusual performance score found: {numeric_value}. Converting as percentage.")
                    return numeric_value / 100
            except (ValueError, TypeError):
                return None
        
        # Apply the cleaning function
        performance_melted['Performance_Score'] = performance_melted['Performance_Score'].apply(clean_performance_score)
        
        # Ensure performance scores are between 0 and 1 (only for non-null values)
        performance_melted.loc[performance_melted['Performance_Score'].notna(), 'Performance_Score'] = \
            performance_melted.loc[performance_melted['Performance_Score'].notna(), 'Performance_Score'].clip(0, 1)
        
        # Remove any rows with missing carriers
        performance_melted = performance_melted.dropna(subset=['Carrier'])
        
        # Remove the temporary Week_Column
        performance_clean = performance_melted.drop('Week_Column', axis=1)
        
        # ONLY CLEAN DATA - NO BUSINESS LOGIC CALCULATIONS
        # All performance calculations (volume-weighted averages, missing value filling)
        # are handled by performance_calculator.py after merging with container data
        
        if len(performance_clean) > 0:
            return performance_clean, True
        else:
            st.warning("⚠️ No valid performance data after processing")
            return None, False
            
    except Exception as e:
        st.warning(f"⚠️ Error processing performance data: {str(e)}. Continuing without performance metrics.")
        return None, False

def load_gvt_data(gvt_file):
    """Load and process GVT data"""
    try:
        gvt_data = pd.read_excel(gvt_file)
        
        st.write(f"- Total rows loaded from Excel: {len(gvt_data)}")
        st.write(f"- Available columns: {list(gvt_data.columns)}")
        
        # Check Week 47 data BEFORE any filtering
        if 'Week Number' in gvt_data.columns:
            wk47_all = gvt_data[gvt_data['Week Number'] == 47]
            st.write(f"- Total Week 47 rows (all ports): {len(wk47_all)}")
            
            # Check different ways to identify BAL
            if 'Lane' in gvt_data.columns:
                st.write(f"- Unique Lanes in Week 47: {sorted(wk47_all['Lane'].unique())}")
                bal_lanes = wk47_all[wk47_all['Lane'].str.startswith('BAL', na=False)]
                st.write(f"- Week 47 rows with Lane starting with 'BAL': {len(bal_lanes)}")
                
        # CRITICAL: Collect ALL BAL Week 47 container IDs from raw Excel
        bal_wk47_container_ids_initial = []
        if 'Container Numbers' in gvt_data.columns and 'Week Number' in gvt_data.columns and 'Lane' in gvt_data.columns:
            bal_wk47_raw = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Lane'].str.startswith('BAL', na=False))]
            
            st.write(f"\n**🎯 BAL WEEK 47 RAW DATA FROM EXCEL:**")
            st.write(f"- Total BAL Week 47 rows in Excel: {len(bal_wk47_raw)}")
            
            for idx, row in bal_wk47_raw.iterrows():
                cn = row['Container Numbers']
                if pd.notna(cn) and str(cn).strip():
                    ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                    bal_wk47_container_ids_initial.extend(ids)
                    
            st.write(f"- **Total BAL Week 47 container IDs (with duplicates): {len(bal_wk47_container_ids_initial)}**")
            st.write(f"- **Unique BAL Week 47 container IDs: {len(set(bal_wk47_container_ids_initial))}**")
            st.write(f"- **Duplicate container IDs: {len(bal_wk47_container_ids_initial) - len(set(bal_wk47_container_ids_initial))}**")
            
            if len(bal_wk47_container_ids_initial) > 0:
                st.write(f"- First 15 BAL Week 47 containers: {bal_wk47_container_ids_initial[:15]}")
                st.write(f"- Last 15 BAL Week 47 containers: {bal_wk47_container_ids_initial[-15:]}")
            
            # Show row-by-row breakdown
            st.write("\n**Row-by-row breakdown:**")
            for idx, row in bal_wk47_raw.iterrows():
                cn = row['Container Numbers']
                if pd.notna(cn) and str(cn).strip():
                    ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                    lane = row.get('Lane', 'N/A')
                    carrier = row.get('Dray SCAC(FL)', 'N/A')
                    facility = row.get('Facility', 'N/A')
                    st.write(f"  Row {idx}: {lane} | {carrier} | {facility} → {len(ids)} containers")
        
        # Ensure required columns exist
        required_cols = ['Dray SCAC(FL)', 'Lane', 'Facility', 'Week Number', 
                        'Container Numbers', 'Base Rate', 'Total Rate']
        
        # Check for Category column and include it
        if 'Category' in gvt_data.columns:
            required_cols.append('Category')
        
        missing_cols = [col for col in required_cols if col not in gvt_data.columns]
        if missing_cols and 'Category' not in missing_cols:  # Category is optional
            st.error(f"Missing required columns in GVT data: {missing_cols}")
            return None
        
        # First, ensure Container Numbers column exists and is clean
        if 'Container Numbers' not in gvt_data.columns:
            st.error("Container Numbers column is required but not found!")
            return None
        
        # Process other columns
        gvt_data['Discharged Port'] = gvt_data['Lane'].str.split('-').str[0]
        
        # CRITICAL: Calculate Container Count AFTER Container Numbers is confirmed to exist
        # This ensures we're counting from the actual data
        def count_containers_properly(container_str):
            """Count actual non-empty container IDs"""
            if pd.isna(container_str) or not str(container_str).strip():
                return 0
            # Split by comma and count non-empty items after stripping whitespace
            ids = [c.strip() for c in str(container_str).split(',') if c.strip()]
            return len(ids)
        
        gvt_data['Container Count'] = gvt_data['Container Numbers'].apply(count_containers_properly)
        
        bal_wk47_after = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Lane'].str.startswith('BAL', na=False))]
        st.write(f"- BAL Week 47 rows: {len(bal_wk47_after)}")
        st.write(f"- BAL Week 47 total Container Count (sum): {bal_wk47_after['Container Count'].sum()}")
        
        # Collect container IDs after calculation
        bal_container_ids_after_calc = []
        for cn in bal_wk47_after['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_container_ids_after_calc.extend(ids)
        st.write(f"- **Actual container IDs in Container Numbers: {len(bal_container_ids_after_calc)}**")
        st.write(f"- **Unique container IDs: {len(set(bal_container_ids_after_calc))}**")
        
        if len(bal_wk47_after) > 0:
            st.dataframe(bal_wk47_after[['Lane', 'Dray SCAC(FL)', 'Week Number', 'Container Count', 'Container Numbers']].head(10))
        
        # Keep Category column if it exists
        select_cols = ['Discharged Port', 'Dray SCAC(FL)', 'Lane', 'Facility', 
                      'Week Number', 'Container Numbers', 'Container Count', 
                      'Base Rate', 'Total Rate']
        
        if 'Category' in gvt_data.columns:
            select_cols.insert(1, 'Category')  # Add Category after Discharged Port
        
        bal_before_select = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Lane'].str.startswith('BAL', na=False))]
        st.write(f"- BAL Week 47 rows before select: {len(bal_before_select)}")
        st.write(f"- BAL Week 47 Container Count sum: {bal_before_select['Container Count'].sum()}")
        
        # Collect container IDs
        bal_ids_before_select = []
        for cn in bal_before_select['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_ids_before_select.extend(ids)
        st.write(f"- **Actual container IDs: {len(bal_ids_before_select)}**")
        
        gvt_data = gvt_data[select_cols]
        
        bal_after_select = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Discharged Port'] == 'BAL')]
        st.write(f"- BAL Week 47 rows after select: {len(bal_after_select)}")
        st.write(f"- BAL Week 47 Container Count sum: {bal_after_select['Container Count'].sum()}")
        st.write(f"- Total rows after column selection: {len(gvt_data)}")
        
        # Collect container IDs
        bal_ids_after_select = []
        for cn in bal_after_select['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_ids_after_select.extend(ids)
        st.write(f"- **Actual container IDs: {len(bal_ids_after_select)}**")
        st.write(f"- **Container IDs lost in column selection: {len(bal_ids_before_select) - len(bal_ids_after_select)}**")
        
        if len(bal_after_select) > 0:
            st.write("Sample data:")
            st.dataframe(bal_after_select[['Discharged Port', 'Lane', 'Dray SCAC(FL)', 'Week Number', 'Container Count', 'Container Numbers']].head(5))
        
        bal_wk47_final = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Discharged Port'] == 'BAL')]
        st.write(f"- BAL Week 47 rows: {len(bal_wk47_final)}")
        st.write(f"- BAL Week 47 total Container Count: {bal_wk47_final['Container Count'].sum()}")
        
        # Collect final container IDs
        bal_ids_final = []
        for cn in bal_wk47_final['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_ids_final.extend(ids)
        st.write(f"- **Actual container IDs being returned: {len(bal_ids_final)}**")
        st.write(f"- **Unique container IDs: {len(set(bal_ids_final))}**")
        
        return gvt_data
        
    except Exception as e:
        st.error(f"Error loading GVT data: {str(e)}")
        return None


def load_performance_data(performance_file):
    """Load and process performance data"""
    try:
        performance_data = pd.read_excel(performance_file)
        
        # Ensure required columns
        required_cols = ['Dray SCAC(FL)', 'Performance_Score']
        missing_cols = [col for col in required_cols if col not in performance_data.columns]
        if missing_cols:
            st.error(f"Missing required columns in Performance data: {missing_cols}")
            return None
        
        return performance_data[required_cols]
        
    except Exception as e:
        st.error(f"Error loading Performance data: {str(e)}")
        return None


def create_comprehensive_data(gvt_data, performance_data):
    """Merge GVT and Performance data"""
    try:
        bal_wk47_input = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Discharged Port'] == 'BAL')]
        st.write(f"- BAL Week 47 rows in input: {len(bal_wk47_input)}")
        st.write(f"- BAL Week 47 total Container Count in input: {bal_wk47_input['Container Count'].sum()}")
        
        # Merge on carrier (SCAC)
        comprehensive_data = gvt_data.merge(
            performance_data, 
            on='Dray SCAC(FL)', 
            how='left'
        )
        
        bal_wk47_merged = comprehensive_data[(comprehensive_data['Week Number'] == 47) & (comprehensive_data['Discharged Port'] == 'BAL')]
        st.write(f"- BAL Week 47 rows after merge: {len(bal_wk47_merged)}")
        st.write(f"- BAL Week 47 total Container Count after merge: {bal_wk47_merged['Container Count'].sum()}")
        
        # Fill missing performance scores with 0
        comprehensive_data['Performance_Score'] = comprehensive_data['Performance_Score'].fillna(0)
        
        # Group by relevant dimensions INCLUDING Category
        group_cols = ['Discharged Port', 'Dray SCAC(FL)', 'Lane', 'Facility', 'Week Number']
        
        # Add Category to grouping if it exists
        if 'Category' in comprehensive_data.columns:
            group_cols.insert(1, 'Category')  # Add Category after Discharged Port
        
        # Aggregate the data
        # NOTE: We aggregate Container Numbers first, then recalculate Container Count
        # This ensures Container Count is always based on the actual Container Numbers data
        agg_dict = {
            'Container Numbers': lambda x: ','.join(x),  # Concatenate all container IDs
            'Container Count': 'sum',  # Temporary - will be recalculated below
            'Base Rate': 'first',  # Assuming same rate per group
            'Total Rate': 'sum',
            'Performance_Score': 'first'  # Assuming same performance per carrier
        }
        
        comprehensive_data = comprehensive_data.groupby(group_cols, as_index=False).agg(agg_dict)
        
        bal_wk47_grouped = comprehensive_data[(comprehensive_data['Week Number'] == 47) & (comprehensive_data['Discharged Port'] == 'BAL')]
        st.write(f"- BAL Week 47 rows after groupby: {len(bal_wk47_grouped)}")
        st.write(f"- BAL Week 47 total Container Count (summed): {bal_wk47_grouped['Container Count'].sum()}")
        if len(bal_wk47_grouped) > 0:
            st.dataframe(bal_wk47_grouped[['Discharged Port', 'Lane', 'Dray SCAC(FL)', 'Week Number', 'Container Count', 'Container Numbers']].head(10))
        
        # CRITICAL: Now that Container Numbers are concatenated, recalculate Container Count
        # This is done AFTER aggregation to ensure Container Count matches Container Numbers
        def recount_containers(container_str):
            """Recount containers from concatenated string - the source of truth"""
            if pd.isna(container_str) or not str(container_str).strip():
                return 0
            # Split by comma, strip whitespace, filter empty values, then count
            ids = [c.strip() for c in str(container_str).split(',') if c.strip()]
            return len(ids)
        
        # This line ensures Container Count is ALWAYS calculated FROM Container Numbers
        comprehensive_data['Container Count'] = comprehensive_data['Container Numbers'].apply(recount_containers)
        
        bal_wk47_final = comprehensive_data[(comprehensive_data['Week Number'] == 47) & (comprehensive_data['Discharged Port'] == 'BAL')]
        st.write(f"- BAL Week 47 rows final: {len(bal_wk47_final)}")
        st.write(f"- BAL Week 47 total Container Count (recalculated): {bal_wk47_final['Container Count'].sum()}")
        if len(bal_wk47_final) > 0:
            st.dataframe(bal_wk47_final[['Discharged Port', 'Lane', 'Dray SCAC(FL)', 'Week Number', 'Container Count', 'Container Numbers']].head(10))
        
        return comprehensive_data
        
    except Exception as e:
        st.error(f"Error creating comprehensive data: {str(e)}")
        return None

