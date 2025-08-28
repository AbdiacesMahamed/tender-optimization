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
    
    col1, col2, col3 = st.columns(3)

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
    
    return gvt_file, rate_file, performance_file

def load_data_files(gvt_file, rate_file, performance_file):
    """Load data from uploaded files or use defaults"""
    if gvt_file is not None and rate_file is not None:
        # Use uploaded files - automatically detect sheets
        try:
            # For GVT file, use first sheet or show options
            excel_file = pd.ExcelFile(gvt_file)
            gvt_sheets = excel_file.sheet_names
            
            if len(gvt_sheets) == 1:
                # Single sheet - use it
                sheet_name = gvt_sheets[0]
                st.info(f"📊 Using sheet '{sheet_name}' from GVT file")
                GVTdata = pd.read_excel(gvt_file, sheet_name=sheet_name)
            else:
                # Multiple sheets - use first one but inform user
                sheet_name = gvt_sheets[0]
                st.info(f"📊 Using first sheet '{sheet_name}' from GVT file (available: {gvt_sheets})")
                GVTdata = pd.read_excel(gvt_file, sheet_name=sheet_name)
                
        except Exception as e:
            st.error(f"❌ Error reading GVT file: {str(e)}")
            st.stop()
        
        try:
            # For Rate file, use first sheet or show options
            excel_file = pd.ExcelFile(rate_file)
            rate_sheets = excel_file.sheet_names
            
            if len(rate_sheets) == 1:
                # Single sheet - use it
                sheet_name = rate_sheets[0]
                st.info(f"💰 Using sheet '{sheet_name}' from Rate file")
                Ratedata = pd.read_excel(rate_file, sheet_name=sheet_name)
            else:
                # Multiple sheets - use first one but inform user
                sheet_name = rate_sheets[0]
                st.info(f"💰 Using first sheet '{sheet_name}' from Rate file (available: {rate_sheets})")
                Ratedata = pd.read_excel(rate_file, sheet_name=sheet_name)
                
        except Exception as e:
            st.error(f"❌ Error reading Rate file: {str(e)}")
            st.stop()
        
        # Performance data is optional
        if performance_file is not None:
            try:
                excel_file = pd.ExcelFile(performance_file)
                perf_sheets = excel_file.sheet_names
                
                if len(perf_sheets) == 1:
                    sheet_name = perf_sheets[0]
                    st.info(f"📈 Using sheet '{sheet_name}' from Performance file")
                    Performancedata = pd.read_excel(performance_file, sheet_name=sheet_name)
                else:
                    sheet_name = perf_sheets[0]
                    st.info(f"📈 Using first sheet '{sheet_name}' from Performance file (available: {perf_sheets})")
                    Performancedata = pd.read_excel(performance_file, sheet_name=sheet_name)
                    
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
            missing_count = performance_clean['Performance_Score'].isna().sum()
            actual_count = performance_clean['Performance_Score'].notna().sum()
            
            st.success(f"✅ Performance data processed: {len(performance_clean)} records from {len(week_columns)} weeks")
            st.info(f"📊 Performance data summary: {actual_count} actual scores, {missing_count} missing values (will be filled using volume weighting after merging)")
            
            return performance_clean, True
        else:
            st.warning("⚠️ No valid performance data after processing")
            return None, False
            
    except Exception as e:
        st.warning(f"⚠️ Error processing performance data: {str(e)}. Continuing without performance metrics.")
        return None, False

