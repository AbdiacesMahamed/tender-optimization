"""
Data loading and processing module for the Carrier Tender Optimization Dashboard
"""
import pandas as pd
import numpy as np
import logging
import streamlit as st
from ..core.config_styling import section_header, info_box, success_box

logger = logging.getLogger(__name__)

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
        st.download_button(
            "📥 Download Template",
            data=_constraint_template_bytes(),
            file_name="constraint_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Blank constraints file with the correct column headers, ready to fill in",
            key="constraints_template_download",
        )

    return gvt_file, rate_file, performance_file, constraints_file


@st.cache_data(show_spinner=False)
def _constraint_template_bytes():
    """Build a blank constraints template from the canonical column schema.

    Generated on the fly from CONSTRAINT_COLUMNS (the single source of truth in
    chatbot.tools) so the download stays in sync whenever a constraint column is
    added or removed — no static file to update.
    """
    from ..chatbot.tools import constraints_to_excel_bytes
    return constraints_to_excel_bytes([])

@st.cache_data(show_spinner=False)
def _load_excel_file(file_bytes, file_name):
    """Cache Excel file loading to avoid re-reading on every interaction"""
    import io
    return pd.read_excel(io.BytesIO(file_bytes))


@st.cache_data(show_spinner=False)
def _load_performance_file(file_bytes, file_name):
    """
    Load a carrier scorecard / performance Excel file with auto-detection.

    Handles common format variations:
    - Data on any sheet (picks the one with the most week-like columns)
    - Header row may not be the first row (scans up to 10 rows)
    - Week columns may be WK42, WK 42, Week 42, Week42, W42, Wk 42, etc.
    - Carrier column may be Carrier, SCAC, Carrier Name, Carrier SCAC, etc.
    - Metrics column may be Metrics, Metric, Type, or absent/unnamed
    - Overall Carrier Scorecard format: grouped blocks per carrier with
      "Score" rows and week columns like "26 W 13" (year prefix + W + week#).
      Carrier names are mapped to SCAC codes automatically.
    """
    import io, re

    buf = io.BytesIO(file_bytes)
    xls = pd.ExcelFile(buf)

    # ---------- Try Overall Carrier Scorecard format first ----------
    # Detected by: "Score" rows in column 1 AND week columns like "YY W NN"
    result = _try_load_overall_scorecard(xls)
    if result is not None:
        logger.info("Detected Overall Carrier Scorecard format")
        return result

    # ---------- Standard scorecard format ----------
    _WEEK_RE = re.compile(
        r'^(?:wk|week|w)\s*(\d+)$', re.IGNORECASE
    )

    def _is_week_col(v):
        s = str(v).strip()
        return bool(_WEEK_RE.match(s) or s.isdigit())

    best_df = None
    best_week_count = 0

    for sheet in xls.sheet_names:
        preview = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=10)
        for row_idx in range(min(len(preview), 10)):
            row_vals = [str(v).strip() for v in preview.iloc[row_idx].values]
            wk_count = sum(1 for v in row_vals if _is_week_col(v))
            if wk_count > best_week_count:
                best_week_count = wk_count
                best_df = pd.read_excel(xls, sheet_name=sheet, header=row_idx)

    if best_df is not None and best_week_count > 0:
        return best_df

    # Fallback: default read (first sheet, header=0)
    buf.seek(0)
    return pd.read_excel(buf)


def _try_load_overall_scorecard(xls: pd.ExcelFile):
    """
    Attempt to parse an Overall Carrier Scorecard file.

    Format characteristics:
    - Column 0: carrier names (filled once per block, then NaN for metric rows)
    - Column 1: metric descriptions, with "Score" as the aggregate row
    - Columns 2+: week scores and a Total column
    - Week headers like "26 W 13" meaning year 2026, week 13

    Returns a DataFrame in standard scorecard format (Carrier + Metrics + WK columns)
    or None if the file doesn't match this format.
    """
    import re
    from config.carrier_mapping import resolve_scac

    # Year-prefixed week pattern: "26 W 13", "25 W 42", etc.
    _YR_WEEK_RE = re.compile(r'^(\d{2})\s*W\s*(\d+)$', re.IGNORECASE)

    for sheet in xls.sheet_names:
        raw = pd.read_excel(xls, sheet_name=sheet, header=None)

        if len(raw) < 10 or len(raw.columns) < 4:
            continue

        # Find the header row: look for "Carriers" in col 0 or week patterns in cols 2+
        header_row = None
        for i in range(min(len(raw), 10)):
            row_vals = [str(v).strip() for v in raw.iloc[i].values]
            # Check if this row has week-like headers (YY W NN pattern)
            week_matches = sum(1 for v in row_vals[2:] if _YR_WEEK_RE.match(v))
            if week_matches >= 2:
                header_row = i
                break

        if header_row is None:
            continue

        # Parse week column names from header row
        week_cols = {}  # col_index -> week_number
        for col_idx in range(2, len(raw.columns)):
            val = str(raw.iloc[header_row, col_idx]).strip()
            m = _YR_WEEK_RE.match(val)
            if m:
                week_num = int(m.group(2))
                week_cols[col_idx] = week_num

        if len(week_cols) < 2:
            continue

        # Check for "Score" rows in column 1 (below header)
        score_mask = raw.iloc[header_row + 1:, 1].astype(str).str.strip().str.lower() == 'score'
        if score_mask.sum() == 0:
            continue

        # This IS the Overall Carrier Scorecard format.
        # Extract carrier blocks: carrier name is in col 0, forward-filled down
        data_start = header_row + 1
        data = raw.iloc[data_start:].copy().reset_index(drop=True)

        # Forward-fill carrier names in column 0
        data[0] = data[0].ffill()

        # Filter to Score rows only
        is_score = data[1].astype(str).str.strip().str.lower() == 'score'
        score_data = data[is_score].copy()

        if len(score_data) == 0:
            continue

        # Build output DataFrame in standard format
        rows = []
        for _, row in score_data.iterrows():
            carrier_name = str(row[0]).strip()
            scac = resolve_scac(carrier_name)

            for col_idx, week_num in week_cols.items():
                score_val = row.iloc[col_idx]
                rows.append({
                    'Carrier': scac,
                    'Metrics': 'Total Score %',
                    f'WK {week_num}': score_val,
                })

        if not rows:
            continue

        # Pivot: one row per carrier, week columns spread out
        result_rows = []
        carriers_seen = []
        for _, row in score_data.iterrows():
            carrier_name = str(row[0]).strip()
            scac = resolve_scac(carrier_name)
            carriers_seen.append(scac)

            record = {'Carrier': scac, 'Metrics': 'Total Score %'}
            for col_idx, week_num in week_cols.items():
                record[f'WK {week_num}'] = row.iloc[col_idx]
            result_rows.append(record)

        result_df = pd.DataFrame(result_rows)
        logger.info(
            f"Parsed Overall Scorecard: {len(result_df)} carriers, "
            f"weeks {sorted(week_cols.values())}, "
            f"carriers: {carriers_seen}"
        )
        return result_df

    return None
def _load_rate_file(file_bytes, file_name):
    """
    Load a rate Excel file with auto-detection of format.

    Supports three formats:
    1. Standard rate sheet — flat Excel with headers in row 0, columns include
       SCAC, Port, FC, Lookup, Base Rate.
    2. Master Rate Card — multi-sheet workbook where the rate data lives in a
       sheet whose name contains 'Master Sheet' and headers start at row 3
       (rows 0-2 contain metadata). Same key columns once the correct header
       row is used.
    3. US Dray Master — has SCAC, Port, FC, Base Rate but no Lookup column.
       May be multi-sheet (data in sheet containing 'Dray' or 'Master' or '3P').
       Lookup is generated as SCAC + Port + FC. Fuel Surcharge is added to
       Base Rate to produce a CPC column if available.

    Returns:
        DataFrame with rate data, regardless of input format.
    """
    import io
    buf = io.BytesIO(file_bytes)

    # Try default load first (header=0)
    df = pd.read_excel(buf, header=0)

    # Quick check: if the expected key columns already exist, return immediately
    if 'Lookup' in df.columns and 'SCAC' in df.columns:
        return df

    # ---------- US Dray Master format detection ----------
    # Has SCAC, Port, FC, Base Rate but no Lookup column
    if 'SCAC' in df.columns and 'Port' in df.columns and 'FC' in df.columns and 'Base Rate' in df.columns:
        df = _transform_dray_master_format(df)
        logger.info("Detected US Dray Master format (first sheet)")
        return df

    # Check other sheets for dray master format
    buf.seek(0)
    xls = pd.ExcelFile(buf)

    dray_sheet = None
    for name in xls.sheet_names:
        name_lower = name.lower()
        if 'dray' in name_lower or ('master' in name_lower and '3p' in name_lower):
            dray_sheet = name
            break
        if 'master' in name_lower and 'structure' not in name_lower:
            dray_sheet = name

    if dray_sheet:
        candidate = pd.read_excel(xls, sheet_name=dray_sheet, header=0)
        if 'SCAC' in candidate.columns and 'Port' in candidate.columns and 'FC' in candidate.columns:
            df = _transform_dray_master_format(candidate)
            logger.info(f"Detected US Dray Master format in sheet '{dray_sheet}'")
            return df

    # ---------- Master Rate Card detection ----------
    # Re-open the workbook and look for a sheet matching "Master Sheet"
    master_sheet = None
    for name in xls.sheet_names:
        if 'master sheet' in name.lower() and 'original' not in name.lower():
            master_sheet = name
            break

    if master_sheet:
        # Scan the first 10 rows to find the header row containing 'Lookup' and 'SCAC'
        preview = pd.read_excel(xls, sheet_name=master_sheet, header=None, nrows=10)
        header_row = None
        for i in range(len(preview)):
            row_values = [str(v).strip() for v in preview.iloc[i].values]
            if 'Lookup' in row_values and 'SCAC' in row_values:
                header_row = i
                break

        if header_row is not None:
            df = pd.read_excel(xls, sheet_name=master_sheet, header=header_row)
            logger.info(f"Detected Master Rate Card format in sheet '{master_sheet}' (header row {header_row})")
            return df

    # ---------- Generic header-row scan (fallback) ----------
    # The file might have metadata rows above the header in the first sheet.
    # Scan the first 10 rows for 'Lookup'/'SCAC'.
    buf.seek(0)
    preview = pd.read_excel(buf, header=None, nrows=10)
    for i in range(len(preview)):
        row_values = [str(v).strip() for v in preview.iloc[i].values]
        if 'Lookup' in row_values and 'SCAC' in row_values:
            buf.seek(0)
            df = pd.read_excel(buf, header=i)
            logger.info(f"Detected rate data header at row {i}")
            return df

    # Nothing matched — return the original default load; validate_and_process_rate_data
    # will raise a clear error if required columns are missing.
    return df


_PORT_ALIASES = {
    'USBWI': 'USBAL',
    'USEWR': 'USNYC',
    'USORF': 'USNFK',
}


def _transform_dray_master_format(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform US Dray Master format into the standard rate format.

    Input columns: SCAC, Port, FC, Base Rate, Fuel Surcharge, Carrier Name, ...
    Output: adds Lookup (SCAC+Port+FC) and CPC (Base Rate + Fuel Surcharge).
    Port codes are normalized to match GVT conventions (USBWI→USBAL, USEWR→USNYC, USORF→USNFK).
    """
    df = df.copy()

    # Normalize port codes to match GVT conventions
    df['Port'] = df['Port'].astype(str).str.strip().replace(_PORT_ALIASES)

    # Generate Lookup key: SCAC + Port + FC
    df['Lookup'] = (
        df['SCAC'].astype(str).str.strip() +
        df['Port'].astype(str).str.strip() +
        df['FC'].astype(str).str.strip()
    )

    # Ensure Base Rate is numeric
    df['Base Rate'] = pd.to_numeric(df['Base Rate'], errors='coerce')

    # Compute CPC (Cost Per Container) = Base Rate + Fuel Surcharge if available
    if 'Fuel Surcharge' in df.columns:
        fuel = pd.to_numeric(df['Fuel Surcharge'], errors='coerce').fillna(0)
        df['CPC'] = df['Base Rate'] + fuel

    # Drop rows without essential data
    df = df.dropna(subset=['SCAC', 'Port', 'FC', 'Base Rate'])

    logger.info(f"Transformed Dray Master: {len(df)} rows, {df['SCAC'].nunique()} carriers, {df['Port'].nunique()} ports")

    return df

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
                # Supports both standard rate sheets and Master Rate Card format
                Ratedata = _load_rate_file(rate_file.read(), rate_file.name)
                rate_file.seek(0)  # Reset file pointer
                
        except Exception as e:
            st.error(f"❌ Error reading Rate file: {str(e)}")
            st.stop()
        
        # Performance data is optional
        if performance_file is not None:
            try:
                with st.spinner('📂 Loading Performance data...'):
                    Performancedata = _load_performance_file(performance_file.read(), performance_file.name)
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
    """Process performance data if available - ONLY handles raw data cleaning, NO business logic calculations.

    Robustly handles common spreadsheet variations:
    - Carrier column: 'Carrier', 'SCAC', 'Carrier Name', 'Carrier SCAC', or first unnamed text column
    - Metrics column: 'Metrics', 'Metric', 'Type', 'Measure', or unnamed column containing 'Total Score %'
    - Week columns: 'WK42', 'WK 42', 'Week 42', 'Week42', 'W42', 'Wk 42', etc.
    - Scores: percentages (80%), decimals (0.80), or whole numbers (80)
    """
    import re

    if not has_performance or Performancedata is None:
        return None, False
    
    try:
        performance_clean = Performancedata.copy()
        
        # Clean up column names by removing trailing/leading spaces
        # Preserve non-string column names (e.g. integer week numbers like 42)
        performance_clean.columns = [
            col.strip() if isinstance(col, str) else col
            for col in performance_clean.columns
        ]
        
        # --- Detect carrier column ---
        carrier_col = None
        _carrier_patterns = ['carrier', 'scac', 'carrier name', 'carrier scac',
                             'dray scac', 'provider', 'vendor', 'lsp']
        for col in performance_clean.columns:
            col_lower = str(col).strip().lower()
            if col_lower in _carrier_patterns or any(p in col_lower for p in _carrier_patterns):
                carrier_col = col
                break
        if carrier_col is None:
            # Fallback: first column that contains string values (skip numeric column names)
            for col in performance_clean.columns:
                if isinstance(col, (int, float)):
                    continue
                try:
                    if performance_clean[col].dtype == object:
                        sample = performance_clean[col].dropna().head(5)
                        if len(sample) > 0 and all(isinstance(v, str) for v in sample):
                            carrier_col = col
                            break
                except Exception:
                    continue
        if carrier_col is None:
            st.warning("⚠️ Could not identify a Carrier column in performance data.")
            return None, False
        
        # Rename to standard name
        if carrier_col != 'Carrier':
            performance_clean = performance_clean.rename(columns={carrier_col: 'Carrier'})
        
        # --- Optionally filter by metrics column if present ---
        # If a metrics/type column exists with 'Total Score' rows, keep only those.
        # Otherwise assume every row is a score row (no filtering needed).
        _metrics_names = ['metrics', 'metric', 'type', 'measure', 'kpi']
        metrics_col = None
        for col in performance_clean.columns:
            col_lower = str(col).strip().lower()
            if col_lower in _metrics_names:
                metrics_col = col
                break
        if metrics_col is None:
            for col in performance_clean.columns:
                if col == 'Carrier' or isinstance(col, (int, float)):
                    continue
                try:
                    if performance_clean[col].dtype != object:
                        continue
                except Exception:
                    continue
                vals = performance_clean[col].dropna().astype(str).str.strip().str.lower().unique()
                if any('total score' in v for v in vals):
                    metrics_col = col
                    break
        
        if metrics_col is not None:
            mask = performance_clean[metrics_col].astype(str).str.strip().str.lower().str.contains('total score', na=False)
            if mask.any():
                performance_clean = performance_clean[mask].copy()
        
        # --- Detect week columns (flexible pattern matching) ---
        # Accepts: WK42, WK 42, Week 42, W42, Wk 42, or bare numbers (42, 43)
        _WEEK_RE = re.compile(r'^(?:wk|week|w)\s*(\d+)$', re.IGNORECASE)
        week_columns = []
        week_mapping = {}
        for col in performance_clean.columns:
            # Handle both string and integer column names
            if isinstance(col, (int, float)) and not pd.isna(col):
                week_columns.append(col)
                week_mapping[col] = int(col)
                continue
            col_str = str(col).strip()
            m = _WEEK_RE.match(col_str)
            if m:
                week_num = int(m.group(1))
                week_columns.append(col)
                week_mapping[col] = week_num
            elif col_str.isdigit():
                week_columns.append(col)
                week_mapping[col] = int(col_str)
        
        if not week_columns:
            st.warning("⚠️ No week columns found in performance data. "
                       "Expected patterns like WK42, WK 42, Week 42, W42, or just 42.")
            return None, False
        
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
            
            str_value = str(value).strip().replace('%', '')
            if str_value == '' or str_value.lower() == 'nan':
                return None
            
            try:
                numeric_value = float(str_value)
                if 0 <= numeric_value <= 1:
                    return numeric_value
                elif 1 < numeric_value <= 100:
                    return numeric_value / 100
                else:
                    return numeric_value / 100
            except (ValueError, TypeError):
                return None
        
        performance_melted['Performance_Score'] = performance_melted['Performance_Score'].apply(clean_performance_score)
        
        # Ensure performance scores are between 0 and 1 (only for non-null values)
        performance_melted.loc[performance_melted['Performance_Score'].notna(), 'Performance_Score'] = \
            performance_melted.loc[performance_melted['Performance_Score'].notna(), 'Performance_Score'].clip(0, 1)
        
        # Remove any rows with missing carriers
        performance_melted = performance_melted.dropna(subset=['Carrier'])
        
        # Remove the temporary Week_Column
        performance_clean = performance_melted.drop('Week_Column', axis=1)
        
        # DEBUG: Print summary of processed performance data
        logger.debug(f"\n=== PERFORMANCE DATA PROCESSING DEBUG ===")
        logger.debug(f"Total performance records after processing: {len(performance_clean)}")
        logger.debug(f"Unique carriers in performance data: {performance_clean['Carrier'].nunique()}")
        logger.debug(f"Carrier names sample: {sorted(performance_clean['Carrier'].unique())[:10]}")
        logger.debug(f"Week numbers in performance data: {sorted(performance_clean['Week Number'].unique())}")
        non_null = performance_clean['Performance_Score'].notna().sum()
        logger.debug(f"Non-null performance scores: {non_null}/{len(performance_clean)} ({non_null/len(performance_clean)*100:.1f}%)")
        if non_null > 0:
            scores = performance_clean['Performance_Score'].dropna()
            logger.debug(f"Performance score range: {scores.min():.3f} - {scores.max():.3f}")
            logger.debug(f"Unique performance scores: {scores.nunique()}")
        logger.debug(f"==========================================\n")
        
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
        
        logger.debug(f"- Total rows loaded from Excel: {len(gvt_data)}")
        logger.debug(f"- Available columns: {list(gvt_data.columns)}")
        
        # Check Week 47 data BEFORE any filtering
        if 'Week Number' in gvt_data.columns:
            wk47_all = gvt_data[gvt_data['Week Number'] == 47]
            logger.debug(f"- Total Week 47 rows (all ports): {len(wk47_all)}")
            
            # Check different ways to identify BAL
            if 'Lane' in gvt_data.columns:
                logger.debug(f"- Unique Lanes in Week 47: {sorted(wk47_all['Lane'].unique())}")
                bal_lanes = wk47_all[wk47_all['Lane'].str.startswith('BAL', na=False)]
                logger.debug(f"- Week 47 rows with Lane starting with 'BAL': {len(bal_lanes)}")
                
        # CRITICAL: Collect ALL BAL Week 47 container IDs from raw Excel
        bal_wk47_container_ids_initial = []
        if 'Container Numbers' in gvt_data.columns and 'Week Number' in gvt_data.columns and 'Lane' in gvt_data.columns:
            bal_wk47_raw = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Lane'].str.startswith('BAL', na=False))]
            
            logger.debug(f"\n**🎯 BAL WEEK 47 RAW DATA FROM EXCEL:**")
            logger.debug(f"- Total BAL Week 47 rows in Excel: {len(bal_wk47_raw)}")
            
            for idx, row in bal_wk47_raw.iterrows():
                cn = row['Container Numbers']
                if pd.notna(cn) and str(cn).strip():
                    ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                    bal_wk47_container_ids_initial.extend(ids)
                    
            logger.debug(f"- **Total BAL Week 47 container IDs (with duplicates): {len(bal_wk47_container_ids_initial)}**")
            logger.debug(f"- **Unique BAL Week 47 container IDs: {len(set(bal_wk47_container_ids_initial))}**")
            logger.debug(f"- **Duplicate container IDs: {len(bal_wk47_container_ids_initial) - len(set(bal_wk47_container_ids_initial))}**")
            
            if len(bal_wk47_container_ids_initial) > 0:
                logger.debug(f"- First 15 BAL Week 47 containers: {bal_wk47_container_ids_initial[:15]}")
                logger.debug(f"- Last 15 BAL Week 47 containers: {bal_wk47_container_ids_initial[-15:]}")
            
            # Show row-by-row breakdown
            logger.debug("\n**Row-by-row breakdown:**")
            for idx, row in bal_wk47_raw.iterrows():
                cn = row['Container Numbers']
                if pd.notna(cn) and str(cn).strip():
                    ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                    lane = row.get('Lane', 'N/A')
                    carrier = row.get('Dray SCAC(FL)', 'N/A')
                    facility = row.get('Facility', 'N/A')
                    logger.debug(f"  Row {idx}: {lane} | {carrier} | {facility} → {len(ids)} containers")
        
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
        logger.debug(f"- BAL Week 47 rows: {len(bal_wk47_after)}")
        logger.debug(f"- BAL Week 47 total Container Count (sum): {bal_wk47_after['Container Count'].sum()}")
        
        # Collect container IDs after calculation
        bal_container_ids_after_calc = []
        for cn in bal_wk47_after['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_container_ids_after_calc.extend(ids)
        logger.debug(f"- **Actual container IDs in Container Numbers: {len(bal_container_ids_after_calc)}**")
        logger.debug(f"- **Unique container IDs: {len(set(bal_container_ids_after_calc))}**")
        
        if len(bal_wk47_after) > 0:
            pass  # Debug dataframe display removed
        
        # Keep Category column if it exists
        select_cols = ['Discharged Port', 'Dray SCAC(FL)', 'Lane', 'Facility', 
                      'Week Number', 'Container Numbers', 'Container Count', 
                      'Base Rate', 'Total Rate']
        
        if 'Category' in gvt_data.columns:
            select_cols.insert(1, 'Category')  # Add Category after Discharged Port
        
        if 'SSL' in gvt_data.columns:
            select_cols.insert(2, 'SSL')  # Add SSL after Category (or after Discharged Port if no Category)
        
        if 'Vessel' in gvt_data.columns:
            select_cols.insert(3, 'Vessel')  # Add Vessel after SSL
        
        bal_before_select = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Lane'].str.startswith('BAL', na=False))]
        logger.debug(f"- BAL Week 47 rows before select: {len(bal_before_select)}")
        logger.debug(f"- BAL Week 47 Container Count sum: {bal_before_select['Container Count'].sum()}")
        
        # Collect container IDs
        bal_ids_before_select = []
        for cn in bal_before_select['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_ids_before_select.extend(ids)
        logger.debug(f"- **Actual container IDs: {len(bal_ids_before_select)}**")
        
        gvt_data = gvt_data[select_cols]
        
        bal_after_select = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Discharged Port'] == 'BAL')]
        logger.debug(f"- BAL Week 47 rows after select: {len(bal_after_select)}")
        logger.debug(f"- BAL Week 47 Container Count sum: {bal_after_select['Container Count'].sum()}")
        logger.debug(f"- Total rows after column selection: {len(gvt_data)}")
        
        # Collect container IDs
        bal_ids_after_select = []
        for cn in bal_after_select['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_ids_after_select.extend(ids)
        logger.debug(f"- **Actual container IDs: {len(bal_ids_after_select)}**")
        logger.debug(f"- **Container IDs lost in column selection: {len(bal_ids_before_select) - len(bal_ids_after_select)}**")
        
        if len(bal_after_select) > 0:
            logger.debug("Sample data available")
        
        bal_wk47_final = gvt_data[(gvt_data['Week Number'] == 47) & (gvt_data['Discharged Port'] == 'BAL')]
        logger.debug(f"- BAL Week 47 rows: {len(bal_wk47_final)}")
        logger.debug(f"- BAL Week 47 total Container Count: {bal_wk47_final['Container Count'].sum()}")
        
        # Collect final container IDs
        bal_ids_final = []
        for cn in bal_wk47_final['Container Numbers']:
            if pd.notna(cn) and str(cn).strip():
                ids = [c.strip() for c in str(cn).split(',') if c.strip()]
                bal_ids_final.extend(ids)
        logger.debug(f"- **Actual container IDs being returned: {len(bal_ids_final)}**")
        logger.debug(f"- **Unique container IDs: {len(set(bal_ids_final))}**")
        
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
        logger.debug(f"- BAL Week 47 rows in input: {len(bal_wk47_input)}")
        logger.debug(f"- BAL Week 47 total Container Count in input: {bal_wk47_input['Container Count'].sum()}")
        
        # Merge on carrier (SCAC)
        comprehensive_data = gvt_data.merge(
            performance_data, 
            on='Dray SCAC(FL)', 
            how='left'
        )
        
        bal_wk47_merged = comprehensive_data[(comprehensive_data['Week Number'] == 47) & (comprehensive_data['Discharged Port'] == 'BAL')]
        logger.debug(f"- BAL Week 47 rows after merge: {len(bal_wk47_merged)}")
        logger.debug(f"- BAL Week 47 total Container Count after merge: {bal_wk47_merged['Container Count'].sum()}")
        
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
        logger.debug(f"- BAL Week 47 rows after groupby: {len(bal_wk47_grouped)}")
        logger.debug(f"- BAL Week 47 total Container Count (summed): {bal_wk47_grouped['Container Count'].sum()}")
        if len(bal_wk47_grouped) > 0:
            pass  # Debug dataframe display removed
        
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
        logger.debug(f"- BAL Week 47 rows final: {len(bal_wk47_final)}")
        logger.debug(f"- BAL Week 47 total Container Count (recalculated): {bal_wk47_final['Container Count'].sum()}")
        if len(bal_wk47_final) > 0:
            pass  # Debug dataframe display removed
        
        return comprehensive_data
        
    except Exception as e:
        st.error(f"Error creating comprehensive data: {str(e)}")
        return None

