"""
Advanced Constraints Module with Excel Upload Support

This module allows users to upload operational constraints via Excel with flexible field support.
Supports partial input, conflict resolution via priority scores, and pre-scenario enforcement.
"""
import streamlit as st
import pandas as pd
import numpy as np
from .config_styling import section_header

def initialize_advanced_constraints():
    """Initialize session state for advanced constraints"""
    if 'uploaded_constraints' not in st.session_state:
        st.session_state.uploaded_constraints = pd.DataFrame()
    if 'constraints_enabled' not in st.session_state:
        st.session_state.constraints_enabled = True
    if 'use_advanced_constraints' not in st.session_state:
        st.session_state.use_advanced_constraints = False

def show_advanced_constraints_interface(comprehensive_data):
    """Display advanced constraints interface with Excel upload"""
    section_header("🎯 Advanced Operational Constraints")
    
    initialize_advanced_constraints()
    
    st.markdown("""
    **Upload operational constraints to control carrier allocations before optimization scenarios.**
    
    📋 **Supported Fields:**
    - `Category` - Product/service category (optional)
    - `Carrier` - Carrier SCAC code (optional)
    - `Lane` - Specific lane (optional)
    - `Week Number` - Specific week(s) (optional)
    - `Maximum Container Count` - Max containers for this constraint (optional)
    - `Minimum Container Count` - Min containers for this constraint (optional)
    - `Percent Allocation` - Percentage of volume (optional)
    - `Priority Score` - Higher scores = higher priority (1-100, default 50)
    
    🧩 **Partial Input**: Not all fields are required. The system handles incomplete rows gracefully.
    
    ⚖️ **Conflict Resolution**: Overlapping constraints are resolved by Priority Score.
    """)
    
    # Toggle between simple and advanced constraints
    col1, col2 = st.columns([3, 1])
    with col1:
        use_advanced = st.checkbox(
            "🚀 Use Advanced Constraints (Excel Upload)",
            value=st.session_state.use_advanced_constraints,
            help="Enable Excel-based constraint uploads with flexible field support"
        )
        st.session_state.use_advanced_constraints = use_advanced
    
    with col2:
        st.session_state.constraints_enabled = st.checkbox(
            "🔒 Enable",
            value=st.session_state.constraints_enabled,
            help="Enable/disable constraint enforcement"
        )
    
    if not use_advanced:
        st.info("💡 Switch to Advanced Constraints to use Excel upload with flexible field support.")
        return
    
    st.markdown("---")
    
    # File upload section
    st.markdown("### 📤 Upload Constraints File")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        uploaded_file = st.file_uploader(
            "Upload Excel file with constraints",
            type=['xlsx', 'xls'],
            help="Upload an Excel file with constraint definitions"
        )
    
    with col2:
        if st.button("📥 Download Template", use_container_width=True):
            template_df = create_constraints_template()
            csv = template_df.to_csv(index=False)
            st.download_button(
                label="💾 Save Template",
                data=csv,
                file_name="constraints_template.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    # Process uploaded file
    if uploaded_file is not None:
        try:
            constraints_df = pd.read_excel(uploaded_file)
            
            # Validate and process constraints
            processed_constraints = validate_and_process_constraints(constraints_df, comprehensive_data)
            
            if processed_constraints is not None and len(processed_constraints) > 0:
                st.session_state.uploaded_constraints = processed_constraints
                st.success(f"✅ Successfully loaded {len(processed_constraints)} constraints!")
            else:
                st.error("❌ No valid constraints found in uploaded file.")
        
        except Exception as e:
            st.error(f"❌ Error reading file: {str(e)}")
            st.info("Please ensure the file matches the template format.")
    
    # Display uploaded constraints
    if len(st.session_state.uploaded_constraints) > 0:
        st.markdown("---")
        st.markdown("### 📋 Loaded Constraints")
        
        display_constraints_table(st.session_state.uploaded_constraints)
        
        # Clear button
        if st.button("🗑️ Clear All Constraints", type="secondary"):
            st.session_state.uploaded_constraints = pd.DataFrame()
            st.success("All constraints cleared!")
            st.rerun()
    else:
        st.info("ℹ️ No constraints loaded. Upload an Excel file to get started.")

def create_constraints_template():
    """Create a template DataFrame for constraints"""
    template = pd.DataFrame({
        'Category': ['FBA LCL', 'Retail CD', None],
        'Carrier': ['XPDR', 'ATMI', 'SONW'],
        'Lane': ['USOAK→TCY2-S', None, 'USEWRIEA2→'],
        'Week Number': [32, '32,33', None],
        'Maximum Container Count': [500, None, 200],
        'Minimum Container Count': [100, 50, None],
        'Percent Allocation': [None, 25.0, None],
        'Priority Score': [100, 80, 60],
        'Notes': ['High priority allocation', 'Minimum commitment', 'Backup carrier']
    })
    return template

def validate_and_process_constraints(constraints_df, comprehensive_data):
    """Validate and process uploaded constraints"""
    
    # Required columns (at least one must be present to define scope)
    scope_columns = ['Category', 'Carrier', 'Lane', 'Week Number']
    constraint_columns = ['Maximum Container Count', 'Minimum Container Count', 'Percent Allocation']
    
    # Check if we have any scope or constraint columns
    has_scope = any(col in constraints_df.columns for col in scope_columns)
    has_constraint = any(col in constraints_df.columns for col in constraint_columns)
    
    if not has_scope:
        st.warning("⚠️ No scope columns found (Category, Carrier, Lane, or Week Number)")
        return None
    
    if not has_constraint:
        st.warning("⚠️ No constraint columns found (Max, Min, or Percent Allocation)")
        return None
    
    # Add missing columns with None values
    for col in scope_columns + constraint_columns + ['Priority Score', 'Notes']:
        if col not in constraints_df.columns:
            constraints_df[col] = None
    
    # Fill missing priority scores with default (50)
    constraints_df['Priority Score'] = constraints_df['Priority Score'].fillna(50)
    
    # Validate and normalize data
    processed_rows = []
    
    for idx, row in constraints_df.iterrows():
        # Skip completely empty rows
        if row[scope_columns + constraint_columns].isna().all():
            continue
        
        # Validate Week Number format
        week_value = row['Week Number']
        if pd.notna(week_value):
            if isinstance(week_value, str):
                # Handle comma-separated weeks
                try:
                    weeks = [int(w.strip()) for w in week_value.split(',')]
                    row['Week Number'] = weeks
                except:
                    row['Week Number'] = None
            elif isinstance(week_value, (int, float)):
                row['Week Number'] = [int(week_value)]
            else:
                row['Week Number'] = None
        else:
            row['Week Number'] = None
        
        # Ensure numeric columns are numeric
        for col in ['Maximum Container Count', 'Minimum Container Count', 'Percent Allocation', 'Priority Score']:
            if pd.notna(row[col]):
                try:
                    row[col] = float(row[col])
                except:
                    row[col] = None
        
        # Validate percentages
        if pd.notna(row['Percent Allocation']):
            if row['Percent Allocation'] < 0 or row['Percent Allocation'] > 100:
                st.warning(f"⚠️ Row {idx+1}: Percent Allocation must be 0-100. Skipping.")
                continue
        
        # Validate min/max relationship
        min_val = row['Minimum Container Count']
        max_val = row['Maximum Container Count']
        if pd.notna(min_val) and pd.notna(max_val):
            if min_val > max_val:
                st.warning(f"⚠️ Row {idx+1}: Min ({min_val}) > Max ({max_val}). Swapping values.")
                row['Minimum Container Count'] = max_val
                row['Maximum Container Count'] = min_val
        
        processed_rows.append(row)
    
    if not processed_rows:
        return None
    
    processed_df = pd.DataFrame(processed_rows).reset_index(drop=True)
    
    # Sort by Priority Score (descending)
    processed_df = processed_df.sort_values('Priority Score', ascending=False).reset_index(drop=True)
    
    return processed_df

def display_constraints_table(constraints_df):
    """Display constraints in a formatted table"""
    
    # Create display DataFrame
    display_df = constraints_df.copy()
    
    # Format Week Number for display
    if 'Week Number' in display_df.columns:
        display_df['Week Number'] = display_df['Week Number'].apply(
            lambda x: ', '.join(map(str, x)) if isinstance(x, list) and x else 'All'
        )
    
    # Fill NaN values with 'Any' for scope columns
    for col in ['Category', 'Carrier', 'Lane']:
        if col in display_df.columns:
            display_df[col] = display_df[col].fillna('Any')
    
    # Format numeric columns
    for col in ['Maximum Container Count', 'Minimum Container Count', 'Percent Allocation']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda x: f"{x:,.0f}" if pd.notna(x) else '-'
            )
    
    if 'Priority Score' in display_df.columns:
        display_df['Priority Score'] = display_df['Priority Score'].apply(
            lambda x: f"{int(x)}" if pd.notna(x) else '50'
        )
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    # Summary statistics
    st.markdown("#### 📊 Constraints Summary")
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("Total Constraints", len(constraints_df))
    
    carriers_affected = constraints_df['Carrier'].dropna().nunique()
    col2.metric("Carriers Affected", carriers_affected if carriers_affected > 0 else "N/A")
    
    avg_priority = constraints_df['Priority Score'].mean()
    col3.metric("Avg Priority", f"{avg_priority:.0f}")
    
    high_priority = len(constraints_df[constraints_df['Priority Score'] >= 80])
    col4.metric("High Priority (≥80)", high_priority)

def apply_advanced_constraints(comprehensive_data):
    """
    Apply advanced constraints with flexible field support and priority-based conflict resolution
    
    Returns:
        constrained_data: DataFrame with volumes allocated by constraints
        unconstrained_data: DataFrame with remaining volumes for optimization
        constraint_summary: Summary of applied constraints
    """
    
    # Check if advanced constraints are enabled
    if not st.session_state.get('use_advanced_constraints', False):
        return pd.DataFrame(), comprehensive_data.copy(), []
    
    if not st.session_state.get('constraints_enabled', False):
        return pd.DataFrame(), comprehensive_data.copy(), []
    
    constraints_df = st.session_state.get('uploaded_constraints', pd.DataFrame())
    
    if len(constraints_df) == 0:
        return pd.DataFrame(), comprehensive_data.copy(), []
    
    # Sort by priority score (highest first)
    constraints_df = constraints_df.sort_values('Priority Score', ascending=False).reset_index(drop=True)
    
    constrained_records = []
    unconstrained_data = comprehensive_data.copy().reset_index(drop=True)
    constraint_summary = []
    
    # Track which containers have been allocated
    allocated_indices = set()
    
    st.markdown("### 🔍 Applying Constraints")
    
    # Process each constraint in priority order
    for constraint_idx, constraint in constraints_df.iterrows():
        st.markdown(f"**Constraint #{constraint_idx + 1}** (Priority: {int(constraint['Priority Score'])})")
        
        # Build filter mask based on constraint fields
        mask = pd.Series([True] * len(unconstrained_data), index=unconstrained_data.index)
        
        # Apply filters for non-null constraint fields
        if pd.notna(constraint['Category']) and 'Category' in unconstrained_data.columns:
            mask &= unconstrained_data['Category'] == constraint['Category']
            st.write(f"  - Category: {constraint['Category']}")
        
        if pd.notna(constraint['Carrier']):
            mask &= unconstrained_data['Dray SCAC(FL)'] == constraint['Carrier']
            st.write(f"  - Carrier: {constraint['Carrier']}")
        
        if pd.notna(constraint['Lane']) and 'Lane' in unconstrained_data.columns:
            # Support partial lane matching (e.g., "USOAK→" matches all lanes starting with USOAK)
            lane_pattern = str(constraint['Lane'])
            if '→' in lane_pattern:
                # Partial match
                mask &= unconstrained_data['Lane'].str.contains(lane_pattern.replace('→', ''), na=False, regex=False)
            else:
                # Exact match
                mask &= unconstrained_data['Lane'] == lane_pattern
            st.write(f"  - Lane: {constraint['Lane']}")
        
        if constraint['Week Number'] is not None and isinstance(constraint['Week Number'], list):
            mask &= unconstrained_data['Week Number'].isin(constraint['Week Number'])
            st.write(f"  - Weeks: {', '.join(map(str, constraint['Week Number']))}")
        
        # Get eligible data (not already allocated)
        available_mask = mask & ~unconstrained_data.index.isin(allocated_indices)
        eligible_data = unconstrained_data[available_mask].copy()
        
        if len(eligible_data) == 0:
            st.warning(f"  ⚠️ No matching data for this constraint")
            constraint_summary.append({
                'constraint_id': constraint_idx + 1,
                'priority': int(constraint['Priority Score']),
                'status': 'No matching data',
                'allocated_containers': 0,
                'allocated_records': 0
            })
            continue
        
        total_available = eligible_data['Container Count'].sum()
        st.write(f"  - Available: {total_available:,} containers from {len(eligible_data)} records")
        
        # Determine target allocation based on constraint type
        target_containers = None
        
        if pd.notna(constraint['Percent Allocation']):
            target_containers = int(total_available * (constraint['Percent Allocation'] / 100))
            st.write(f"  - Target: {target_containers:,} containers ({constraint['Percent Allocation']}%)")
        
        # Apply min/max constraints
        min_containers = constraint['Minimum Container Count']
        max_containers = constraint['Maximum Container Count']
        
        if target_containers is None:
            # No percentage, use min as target or all available
            if pd.notna(min_containers):
                target_containers = int(min_containers)
            else:
                target_containers = total_available
        
        # Apply boundaries
        if pd.notna(min_containers):
            target_containers = max(target_containers, int(min_containers))
            st.write(f"  - Minimum enforced: {int(min_containers):,}")
        
        if pd.notna(max_containers):
            target_containers = min(target_containers, int(max_containers))
            st.write(f"  - Maximum enforced: {int(max_containers):,}")
        
        # Can't allocate more than available
        target_containers = min(target_containers, total_available)
        
        st.write(f"  ✅ **Final target: {target_containers:,} containers**")
        
        # Allocate containers
        allocation_data = eligible_data.sort_values('Week Number').copy()
        allocated_containers = 0
        current_allocated_indices = []
        
        for idx, row in allocation_data.iterrows():
            if allocated_containers >= target_containers:
                break
            
            containers_to_allocate = min(
                row['Container Count'],
                target_containers - allocated_containers
            )
            
            if containers_to_allocate > 0:
                # Create constrained record
                constrained_record = row.copy()
                constrained_record['Container Count'] = containers_to_allocate
                constrained_record['Constraint_ID'] = constraint_idx + 1
                constrained_record['Constraint_Priority'] = int(constraint['Priority Score'])
                constrained_record['Constraint_Applied'] = f"Priority {int(constraint['Priority Score'])}"
                
                # Add constraint details as notes
                notes_parts = []
                if pd.notna(constraint['Category']):
                    notes_parts.append(f"Cat:{constraint['Category']}")
                if pd.notna(constraint['Carrier']):
                    notes_parts.append(f"Carrier:{constraint['Carrier']}")
                if pd.notna(constraint['Notes']):
                    notes_parts.append(str(constraint['Notes']))
                
                constrained_record['Constraint_Notes'] = ' | '.join(notes_parts) if notes_parts else ''
                
                constrained_records.append(constrained_record)
                allocated_containers += containers_to_allocate
                current_allocated_indices.append(idx)
                allocated_indices.add(idx)
        
        st.write(f"  📦 Allocated: {allocated_containers:,} containers across {len(current_allocated_indices)} records")
        
        constraint_summary.append({
            'constraint_id': constraint_idx + 1,
            'priority': int(constraint['Priority Score']),
            'status': 'Applied',
            'allocated_containers': allocated_containers,
            'allocated_records': len(current_allocated_indices),
            'target_containers': target_containers
        })
    
    # Create constrained DataFrame
    if constrained_records:
        constrained_data = pd.DataFrame(constrained_records)
    else:
        constrained_data = pd.DataFrame()
    
    # Remove allocated containers from unconstrained data
    if allocated_indices:
        unconstrained_data = unconstrained_data[~unconstrained_data.index.isin(allocated_indices)].copy()
    
    # Summary
    st.markdown("---")
    st.markdown("### 📊 Constraint Application Summary")
    col1, col2, col3 = st.columns(3)
    
    original_total = comprehensive_data['Container Count'].sum()
    constrained_total = constrained_data['Container Count'].sum() if len(constrained_data) > 0 else 0
    unconstrained_total = unconstrained_data['Container Count'].sum()
    
    col1.metric("Original Containers", f"{original_total:,}")
    col2.metric("Constrained", f"{constrained_total:,}")
    col3.metric("Unconstrained", f"{unconstrained_total:,}")
    
    if abs(original_total - (constrained_total + unconstrained_total)) > 0.01:
        st.error(f"⚠️ Container count mismatch! Difference: {original_total - (constrained_total + unconstrained_total):,.0f}")
    else:
        st.success("✅ Container counts balanced correctly")
    
    return constrained_data, unconstrained_data, constraint_summary

def show_advanced_constraints_summary(constraint_summary):
    """Display summary of applied advanced constraints"""
    if not constraint_summary:
        return
    
    section_header("📊 Advanced Constraints Applied")
    
    summary_df = pd.DataFrame(constraint_summary)
    
    # Format for display
    display_df = summary_df.copy()
    display_df['allocated_containers'] = display_df['allocated_containers'].apply(lambda x: f"{x:,}")
    
    if 'target_containers' in display_df.columns:
        display_df['target_containers'] = display_df['target_containers'].apply(lambda x: f"{x:,}")
    
    display_df = display_df.rename(columns={
        'constraint_id': 'ID',
        'priority': 'Priority',
        'status': 'Status',
        'allocated_containers': 'Containers',
        'allocated_records': 'Records',
        'target_containers': 'Target'
    })
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    # Summary metrics
    col1, col2, col3 = st.columns(3)
    total_allocated = summary_df['allocated_containers'].sum()
    successful = len(summary_df[summary_df['status'] == 'Applied'])
    
    col1.metric("🔒 Total Constrained", f"{total_allocated:,}")
    col2.metric("✅ Successful", successful)
    col3.metric("⚠️ No Match", len(summary_df) - successful)
