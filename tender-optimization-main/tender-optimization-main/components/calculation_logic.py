"""
Calculation logic explanation and debug utilities for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
from .config_styling import section_header, info_box

def show_calculation_logic():
    """Show detailed calculation logic explanation"""
    section_header("💡 Calculation Logic")
    
    info_box("""
    <strong>Total Rate Calculation:</strong><br>
    <code>Total Rate = Base Rate × Container Count</code><br><br>
    <strong>Where:</strong><br>
    • <strong>Base Rate:</strong> The per-container rate charged by the carrier for a specific SCAC-Port-Facility combination<br>
    • <strong>Container Count:</strong> The number of containers shipped on that specific route during the selected time period<br><br>
    <strong>Example:</strong> If Base Rate = $500 and Container Count = 10, then Total Rate = $5,000<br><br>

    <strong>Cheapest Rate Calculation:</strong><br>
    <code>Cheapest Base Rate = MIN(Base Rate) for each Lane</code><br><br>
    <strong>How it works:</strong><br>
    • <strong>Lane:</strong> A unique combination of Port + Facility (e.g., USLAX + IUSF)<br>
    • <strong>Process:</strong> For each lane, the system finds all available carriers (SCACs) and identifies the one with the lowest rate<br>
    • <strong>Cheapest Total Rate:</strong> Cheapest Base Rate × Container Count<br><br>

    <strong>Potential Savings Calculation:</strong><br>
    <code>Potential Savings = Total Rate - Cheapest Total Rate</code><br><br>
    <strong>How it works:</strong><br>
    • Shows the dollar amount that could be saved by switching to the cheapest available carrier for each lane<br>
    • Represents the difference between what you're currently paying vs. the lowest available rate<br><br>

    <strong>Week Number Calculation:</strong><br>
    <code>Week Number = ISO Week Number from SSL ATA Date</code><br><br>
    <strong>How it works:</strong><br>
    • Extracted from the SSL ATA (Actual Time of Arrival) date in the GVT data<br>
    • Uses ISO 8601 standard where weeks start on Monday and week 1 contains January 4th<br>
    • Allows analysis of shipping patterns and costs by week<br><br>

    <strong>Savings Percentage Calculation:</strong><br>
    <code>Savings % = (Potential Savings ÷ Total Rate) × 100</code><br><br>
    <strong>How it works:</strong><br>
    • Shows what percentage of current costs could be saved by switching to cheapest rates<br>
    • Higher percentages indicate greater optimization opportunities<br><br>

    <strong>Performance Data Integration:</strong><br>
    <code>Performance Score matched by Carrier (SCAC) + Week Number</code><br><br>
    <strong>How it works:</strong><br>
    • Performance data is matched when the Carrier in performance data equals the Dray SCAC(FL) in GVT data<br>
    • Week numbers from both datasets must match exactly<br>
    • Performance scores are displayed as percentages and averaged in summary tables<br>
    • Allows evaluation of cost savings opportunities alongside carrier performance metrics<br><br>

    <strong>Example:</strong> For lane USLAXIUSF:<br>
    - SCAC A charges $500 per container<br>
    - SCAC B charges $450 per container<br>
    - SCAC C charges $475 per container<br>
    - Cheapest Base Rate = $450 (SCAC B)<br>
    - If you have 10 containers:<br>
      • Total Rate = $500 × 10 = $5,000<br>
      • Cheapest Total Rate = $450 × 10 = $4,500<br>
      • Potential Savings = $5,000 - $4,500 = $500<br>
      • Savings % = ($500 ÷ $5,000) × 100 = 10%<br>
      • Performance Score = 82.1% (if SCAC A has 82.1% performance for that week)
    """)

def show_debug_performance_merge(merged_data, performance_clean, has_performance):
    """Show debug information for performance data merging"""
    with st.expander("🔍 Debug Performance Merge (Click to expand)"):
        # Check if performance data exists and was merged
        st.write(f"**Has performance data:** {has_performance}")
        if has_performance:
            st.write(f"**Performance records available:** {len(performance_clean)}")
            
            # Show sample performance data
            if st.checkbox("Show Sample Performance Data"):
                st.dataframe(performance_clean.head())
            
            # Show unique carriers and weeks in performance data
            st.write(f"**Unique carriers in performance data:** {sorted(performance_clean['Carrier'].unique())}")
            st.write(f"**Unique weeks in performance data:** {sorted(performance_clean['Week Number'].unique())}")

        # Check merged data
        st.write(f"**Performance_Score column exists in merged data:** {'Performance_Score' in merged_data.columns}")
        
        if 'Performance_Score' in merged_data.columns:
            st.write(f"**Performance records with non-null values:** {merged_data['Performance_Score'].notna().sum()}")
            
            # Show sample of merged data with performance
            if st.checkbox("Show Sample Merged Data"):
                merged_with_perf = merged_data[merged_data['Performance_Score'].notna()]
                if len(merged_with_perf) > 0:
                    st.dataframe(merged_with_perf[['Dray SCAC(FL)', 'Week Number', 'Performance_Score']].head())

def show_footer():
    """Show dashboard footer"""
    st.markdown("---")
    st.markdown("*Dashboard created for Carrier Tender Optimization Analysis*")
