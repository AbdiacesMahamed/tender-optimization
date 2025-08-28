"""
Suboptimal Selection Analysis module for the Carrier Tender Optimization Dashboard
Identifies lanes where current selections are both higher cost AND lower performance
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header

def find_suboptimal_selections(data):
    """Find carriers that are both more expensive AND worse performing than alternatives"""
    
    if 'Performance_Score' not in data.columns:
        return pd.DataFrame()
    
    suboptimal = []
    
    # Group by lane and week to compare options
    for (lane, week), group in data.groupby(['Lane', 'Week Number']):
        if len(group) < 2:  # Skip if no alternatives
            continue
            
        # Compare each carrier against all others in the same lane/week
        for _, current in group.iterrows():
            # Skip if no performance data
            if pd.isna(current['Performance_Score']) or current['Performance_Score'] <= 0:
                continue
                
            for _, alternative in group.iterrows():
                # Skip if same carrier or no performance data
                if (current.name == alternative.name or 
                    pd.isna(alternative['Performance_Score']) or 
                    alternative['Performance_Score'] <= 0):
                    continue
                
                # Check if alternative is BOTH cheaper AND better
                cheaper = alternative['Base Rate'] < current['Base Rate']
                better_performance = alternative['Performance_Score'] > current['Performance_Score']
                
                if cheaper and better_performance:
                    cost_savings = (current['Base Rate'] - alternative['Base Rate']) * current['Container Count']
                    perf_gain = alternative['Performance_Score'] - current['Performance_Score']
                    
                    suboptimal.append({
                        'Lane': lane,
                        'Week': week,
                        'Current_Carrier': current['Dray SCAC(FL)'],
                        'Current_Rate': current['Base Rate'],
                        'Current_Performance': current['Performance_Score'],
                        'Better_Carrier': alternative['Dray SCAC(FL)'],
                        'Better_Rate': alternative['Base Rate'],
                        'Better_Performance': alternative['Performance_Score'],
                        'Containers': current['Container Count'],
                        'Cost_Savings': cost_savings,
                        'Performance_Gain': perf_gain
                    })
                    break  # Found one better alternative, that's enough
    
    return pd.DataFrame(suboptimal)

def show_suboptimal_analysis(final_filtered_data):
    """Display the suboptimal selection analysis"""
    section_header("🚨 Suboptimal Selection Analysis")
    
    st.markdown("**What this shows:** Carriers you're using that are both more expensive AND worse performing than available alternatives.")
    
    # Find suboptimal selections
    suboptimal_df = find_suboptimal_selections(final_filtered_data)
    
    if len(suboptimal_df) == 0:
        st.success("✅ **Great News!** No carriers found that are both more expensive AND worse performing than alternatives.")
        st.info("Your selections appear well-optimized from a cost-performance perspective.")
        return
    
    # Show summary metrics
    st.markdown("### 📊 Summary")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("🚨 Suboptimal Instances", len(suboptimal_df))
    
    with col2:
        total_waste = suboptimal_df['Cost_Savings'].sum()
        st.metric("💸 Total Wasted Cost", f"${total_waste:,.2f}")
    
    with col3:
        avg_perf_loss = suboptimal_df['Performance_Gain'].mean()
        st.metric("📉 Avg Performance Loss", f"{avg_perf_loss:.1%}")
    
    # Show the data
    st.markdown("### 🎯 Suboptimal Selections Found")
    
    # Format the display
    display_df = suboptimal_df.copy()
    display_df['Current_Performance'] = display_df['Current_Performance'].apply(lambda x: f"{x:.1%}")
    display_df['Better_Performance'] = display_df['Better_Performance'].apply(lambda x: f"{x:.1%}")
    display_df['Performance_Gain'] = display_df['Performance_Gain'].apply(lambda x: f"+{x:.1%}")
    display_df['Cost_Savings'] = display_df['Cost_Savings'].apply(lambda x: f"${x:,.2f}")
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    # Export option
    if len(suboptimal_df) > 0:
        csv = suboptimal_df.to_csv(index=False)
        st.download_button(
            "📥 Download Report",
            data=csv,
            file_name='suboptimal_selections.csv',
            mime='text/csv'
        )

