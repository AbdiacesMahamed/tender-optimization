"""
Missing Rate Analysis module for the Carrier Tender Optimization Dashboard
Identifies and analyzes lanes with missing or invalid rate information
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header

def show_missing_rate_analysis(final_filtered_data, original_data=None):
    """Identify and display lanes with missing rate information"""
    section_header("🔍 Missing Rate Analysis")
    
    # Find lanes with missing or zero rates
    missing_rate_issues = []
    
    # Check for missing Base Rate
    missing_base_rate = final_filtered_data[
        (final_filtered_data['Base Rate'].isna()) | 
        (final_filtered_data['Base Rate'] <= 0)
    ]
    
    if len(missing_base_rate) > 0:
        for _, row in missing_base_rate.iterrows():
            missing_rate_issues.append({
                'Lane': row['Lane'],
                'Carrier_SCAC': row['Dray SCAC(FL)'],
                'Week_Number': row.get('Week Number', 'N/A'),
                'Container_Count': row['Container Count'],
                'Issue_Type': 'Missing/Zero Base Rate',
                'Base_Rate': row['Base Rate'],
                'Total_Rate': row.get('Total Rate', 'N/A'),
                'Port': row.get('Discharged Port', 'N/A'),
                'Facility': row.get('Facility', 'N/A')
            })
    
    # Check for missing Total Rate
    missing_total_rate = final_filtered_data[
        (final_filtered_data['Total Rate'].isna()) | 
        (final_filtered_data['Total Rate'] <= 0)
    ]
    
    if len(missing_total_rate) > 0:
        for _, row in missing_total_rate.iterrows():
            missing_rate_issues.append({
                'Lane': row['Lane'],
                'Carrier_SCAC': row['Dray SCAC(FL)'],
                'Week_Number': row.get('Week Number', 'N/A'),
                'Container_Count': row['Container Count'],
                'Issue_Type': 'Missing/Zero Total Rate',
                'Base_Rate': row.get('Base Rate', 'N/A'),
                'Total_Rate': row['Total Rate'],
                'Port': row.get('Discharged Port', 'N/A'),
                'Facility': row.get('Facility', 'N/A')
            })
    
    # Check for lanes with no carriers at all (if original_data is provided)
    lanes_with_no_carriers = []
    if original_data is not None:
        all_lanes = set(original_data['Lane'].unique()) if 'Lane' in original_data.columns else set()
        filtered_lanes = set(final_filtered_data['Lane'].unique())
        lanes_with_no_carriers = list(all_lanes - filtered_lanes)
    
    # Display results
    if len(missing_rate_issues) == 0 and len(lanes_with_no_carriers) == 0:
        st.success("✅ **Excellent!** No missing rate data found in your current selection.")
        st.info("ℹ️ All lanes have valid rate information for cost calculations.")
        return
    
    # Summary metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "🚨 Records with Missing Rates",
            f"{len(missing_rate_issues)}"
        )
    
    with col2:
        affected_containers = sum([issue['Container_Count'] for issue in missing_rate_issues if pd.notna(issue['Container_Count'])])
        st.metric(
            "📦 Affected Containers",
            f"{affected_containers:,}"
        )
    
    with col3:
        unique_lanes_affected = len(set([issue['Lane'] for issue in missing_rate_issues]))
        st.metric(
            "🛣️ Unique Lanes Affected",
            f"{unique_lanes_affected}"
        )
    
    # Show detailed missing rate issues
    if len(missing_rate_issues) > 0:
        st.markdown("### 🚨 **Records with Missing Rate Data**")
        
        missing_df = pd.DataFrame(missing_rate_issues)
        
        # Sort by container count (highest impact first)
        missing_df = missing_df.sort_values('Container_Count', ascending=False, na_position='last')
        
        # Format for display
        display_df = missing_df.copy()
        display_df['Container_Count'] = display_df['Container_Count'].apply(
            lambda x: f"{x:,}" if pd.notna(x) else "N/A"
        )
        display_df['Base_Rate'] = display_df['Base_Rate'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) and x > 0 else "MISSING"
        )
        display_df['Total_Rate'] = display_df['Total_Rate'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) and x > 0 else "MISSING"
        )
        
        # Rename columns for display
        display_df = display_df.rename(columns={
            'Carrier_SCAC': 'Carrier',
            'Week_Number': 'Week',
            'Container_Count': 'Containers',
            'Issue_Type': 'Issue',
            'Base_Rate': 'Base Rate',
            'Total_Rate': 'Total Rate'
        })
        
        st.dataframe(display_df, use_container_width=True)
        
        # Issue breakdown
        st.markdown("### 📊 **Issue Breakdown**")
        issue_counts = missing_df['Issue_Type'].value_counts()
        
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Issue Types:**")
            for issue_type, count in issue_counts.items():
                st.write(f"• {issue_type}: {count} records")
        
        with col2:
            # Top affected lanes
            lane_counts = missing_df['Lane'].value_counts().head(5)
            st.write("**Most Affected Lanes:**")
            for lane, count in lane_counts.items():
                st.write(f"• {lane}: {count} issues")
    
    # Show lanes with no carriers
    if len(lanes_with_no_carriers) > 0:
        st.markdown("### 🚫 **Lanes with No Carrier Data**")
        st.warning(f"⚠️ Found {len(lanes_with_no_carriers)} lanes that appear in your original data but have no carriers in the filtered results.")
        
        lanes_df = pd.DataFrame({'Lane': lanes_with_no_carriers})
        st.dataframe(lanes_df, use_container_width=True)
        
        st.info("💡 **Tip:** These lanes might be filtered out due to your current selection criteria, or they may lack rate data entirely.")
    
    # Export missing rate report
    if len(missing_rate_issues) > 0:
        export_df = pd.DataFrame(missing_rate_issues)
        csv = export_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Missing Rate Report",
            data=csv,
            file_name='missing_rate_analysis.csv',
            mime='text/csv',
            use_container_width=True
        )
    
    # Detailed analysis in expander
    if len(missing_rate_issues) > 0:
        with st.expander("🔍 Detailed Missing Rate Analysis"):
            st.markdown("### 📈 **Impact Analysis**")
            
            # Calculate potential impact
            total_containers_missing = sum([issue['Container_Count'] for issue in missing_rate_issues if pd.notna(issue['Container_Count'])])
            total_containers_valid = final_filtered_data['Container Count'].sum()
            
            if total_containers_valid > 0:
                missing_percentage = (total_containers_missing / (total_containers_missing + total_containers_valid)) * 100
                st.write(f"**Missing data impact:** {missing_percentage:.1f}% of total container volume")
            
            # Show by carrier
            carrier_issues = missing_df.groupby('Carrier_SCAC').agg({
                'Lane': 'nunique',
                'Container_Count': lambda x: x.sum() if any(pd.notna(x)) else 0,
                'Issue_Type': 'count'
            }).reset_index()
            
            carrier_issues.columns = ['Carrier', 'Affected_Lanes', 'Total_Containers', 'Total_Issues']
            carrier_issues = carrier_issues.sort_values('Total_Issues', ascending=False)
            
            st.markdown("**Issues by Carrier:**")
            st.dataframe(carrier_issues, use_container_width=True)

def identify_missing_rate_lanes(final_filtered_data):
    """
    Helper function to identify lanes with missing rate data
    Returns a dictionary with analysis results
    """
    analysis_results = {
        'missing_base_rate_count': 0,
        'missing_total_rate_count': 0,
        'affected_containers': 0,
        'affected_lanes': set(),
        'affected_carriers': set(),
        'issues_by_carrier': {},
        'issues_by_lane': {}
    }
    
    # Check for missing Base Rate
    missing_base_rate = final_filtered_data[
        (final_filtered_data['Base Rate'].isna()) | 
        (final_filtered_data['Base Rate'] <= 0)
    ]
    
    # Check for missing Total Rate
    missing_total_rate = final_filtered_data[
        (final_filtered_data['Total Rate'].isna()) | 
        (final_filtered_data['Total Rate'] <= 0)
    ]
    
    analysis_results['missing_base_rate_count'] = len(missing_base_rate)
    analysis_results['missing_total_rate_count'] = len(missing_total_rate)
    
    # Combine all missing rate issues
    all_missing = pd.concat([missing_base_rate, missing_total_rate]).drop_duplicates()
    
    if len(all_missing) > 0:
        analysis_results['affected_containers'] = all_missing['Container Count'].sum()
        analysis_results['affected_lanes'] = set(all_missing['Lane'].unique())
        analysis_results['affected_carriers'] = set(all_missing['Dray SCAC(FL)'].unique())
        
        # Issues by carrier
        carrier_issues = all_missing.groupby('Dray SCAC(FL)').agg({
            'Lane': 'nunique',
            'Container Count': 'sum'
        }).to_dict('index')
        analysis_results['issues_by_carrier'] = carrier_issues
        
        # Issues by lane
        lane_issues = all_missing.groupby('Lane').agg({
            'Dray SCAC(FL)': 'nunique',
            'Container Count': 'sum'
        }).to_dict('index')
        analysis_results['issues_by_lane'] = lane_issues
    
    return analysis_results

def get_missing_rate_summary(final_filtered_data, original_data=None):
    """
    Get a quick summary of missing rate issues
    Returns a summary dictionary for dashboard display
    """
    summary = {
        'has_missing_rates': False,
        'missing_records_count': 0,
        'affected_containers': 0,
        'affected_lanes_count': 0,
        'missing_percentage': 0.0,
        'status_message': "",
        'status_type': "success"  # success, warning, error
    }
    
    # Find missing rate issues
    missing_base = final_filtered_data[
        (final_filtered_data['Base Rate'].isna()) | 
        (final_filtered_data['Base Rate'] <= 0)
    ]
    
    missing_total = final_filtered_data[
        (final_filtered_data['Total Rate'].isna()) | 
        (final_filtered_data['Total Rate'] <= 0)
    ]
    
    all_missing = pd.concat([missing_base, missing_total]).drop_duplicates()
    
    if len(all_missing) > 0:
        summary['has_missing_rates'] = True
        summary['missing_records_count'] = len(all_missing)
        summary['affected_containers'] = int(all_missing['Container Count'].sum())
        summary['affected_lanes_count'] = all_missing['Lane'].nunique()
        
        total_containers = final_filtered_data['Container Count'].sum()
        if total_containers > 0:
            summary['missing_percentage'] = (summary['affected_containers'] / total_containers) * 100
        
        # Determine severity
        if summary['missing_percentage'] > 10:
            summary['status_type'] = "error"
            summary['status_message'] = f"🚨 Critical: {summary['missing_percentage']:.1f}% of container volume has missing rates"
        elif summary['missing_percentage'] > 5:
            summary['status_type'] = "warning"
            summary['status_message'] = f"⚠️ Warning: {summary['missing_percentage']:.1f}% of container volume has missing rates"
        else:
            summary['status_type'] = "warning"
            summary['status_message'] = f"⚠️ Minor: {summary['missing_records_count']} records with missing rates found"
    else:
        summary['status_message'] = "✅ All records have valid rate data"
    
    # Check for completely missing lanes if original data provided
    if original_data is not None:
        all_lanes = set(original_data['Lane'].unique()) if 'Lane' in original_data.columns else set()
        filtered_lanes = set(final_filtered_data['Lane'].unique())
        missing_lanes = len(all_lanes - filtered_lanes)
        
        if missing_lanes > 0:
            if not summary['has_missing_rates']:
                summary['status_type'] = "warning"
            summary['status_message'] += f" | {missing_lanes} lanes completely filtered out"
    
    return summary

def show_missing_rate_dashboard_widget(final_filtered_data, original_data=None):
    """
    Show a compact widget for the main dashboard indicating missing rate status
    """
    summary = get_missing_rate_summary(final_filtered_data, original_data)
    
    if summary['status_type'] == "success":
        st.success(summary['status_message'])
    elif summary['status_type'] == "warning":
        st.warning(summary['status_message'])
    else:
        st.error(summary['status_message'])
    
    # Show quick stats if there are issues
    if summary['has_missing_rates']:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Missing Records", summary['missing_records_count'])
        with col2:
            st.metric("Affected Containers", f"{summary['affected_containers']:,}")
        with col3:
            st.metric("Impact", f"{summary['missing_percentage']:.1f}%")
