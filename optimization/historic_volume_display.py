"""
Historic Volume Visualization Module

Streamlit UI components for displaying historic volume analysis.
Shows carrier market share, trends, and participation patterns.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from .historic_volume import (
    calculate_carrier_volume_share,
    calculate_carrier_weekly_trends,
    get_carrier_lane_participation,
)


def show_historic_volume_analysis(
    data: pd.DataFrame,
    n_weeks: int = 5,
    reference_date: datetime | None = None,
):
    """
    Display comprehensive historic volume analysis interface.
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data with carrier allocations and container counts
    n_weeks : int, default=5
        Number of historical weeks to analyze
    reference_date : datetime, optional
        Reference date for determining current week (default: today)
    """
    st.header("📊 Historic Volume Analysis")
    
    if data is None or data.empty:
        st.warning("⚠️ No data available for historic volume analysis.")
        return
    
    # Show available weeks in data
    if 'Week Number' in data.columns:
        available_weeks = sorted(data['Week Number'].dropna().unique())
        total_containers_in_data = data['Container Count'].sum() if 'Container Count' in data.columns else 0
        num_available_weeks = len(available_weeks)
        st.info(
            f"📅 Available weeks in data: **{min(available_weeks)} - {max(available_weeks)}** ({num_available_weeks} weeks) | "
            f"Total containers: **{total_containers_in_data:,.0f}**"
        )
    else:
        num_available_weeks = 5  # Default fallback
    
    # Configuration
    col1, col2 = st.columns([1, 3])
    
    with col1:
        # Build options list - include "All" option that uses all available weeks
        week_options = ["All", 3, 4, 5, 6, 8, 10]
        n_weeks_selection = st.selectbox(
            "Weeks to Analyze",
            options=week_options,
            index=0,  # Default to "All"
            help="Number of weeks to include in analysis. 'All' uses all available weeks."
        )
        
        # Convert selection to actual number
        if n_weeks_selection == "All":
            n_weeks = num_available_weeks if 'Week Number' in data.columns else 999
        else:
            n_weeks = n_weeks_selection
    
    with col2:
        st.write("")  # Spacing
    
    # Calculate metrics
    try:
        volume_share = calculate_carrier_volume_share(
            data,
            n_weeks=n_weeks,
            reference_date=reference_date
        )
        
        weekly_trends = calculate_carrier_weekly_trends(
            data,
            n_weeks=n_weeks,
            reference_date=reference_date
        )
        
        participation = get_carrier_lane_participation(
            data,
            n_weeks=n_weeks,
            reference_date=reference_date
        )
        
    except Exception as e:
        st.error(f"❌ Error calculating historic volume: {str(e)}")
        return
    
    if volume_share.empty:
        st.warning("⚠️ No historical data found for the selected time period.")
        return
    
    # Display tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Market Share", 
        "📊 Weekly Trends", 
        "✅ Participation", 
        "📋 Detailed Data"
    ])
    
    with tab1:
        show_market_share_analysis(volume_share, n_weeks)
    
    with tab2:
        show_weekly_trends_analysis(weekly_trends, n_weeks)
    
    with tab3:
        show_participation_analysis(participation, n_weeks)
    
    with tab4:
        show_detailed_data_export(volume_share, weekly_trends, participation)


def show_market_share_analysis(volume_share: pd.DataFrame, n_weeks: int):
    """Display carrier market share analysis."""
    
    st.subheader(f"Carrier Market Share")
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_carriers = volume_share['Dray SCAC(FL)'].nunique()
        st.metric("Total Carriers", total_carriers)
    
    with col2:
        total_lanes = volume_share['Lane'].nunique()
        st.metric("Total Lanes", total_lanes)
    
    with col3:
        # Calculate actual container total from lane totals (avoid double counting across carriers)
        # Get unique lane totals - each lane's containers should only be counted once
        lane_cols = ['Lane']
        if 'Category' in volume_share.columns:
            lane_cols.insert(0, 'Category')
        if 'SSL' in volume_share.columns:
            lane_cols.insert(1, 'SSL')
        if 'Terminal' in volume_share.columns:
            lane_cols.append('Terminal')
        
        # Get unique lane totals (one entry per lane/category/terminal combination)
        unique_lane_totals = volume_share.drop_duplicates(subset=lane_cols)['Lane_Total_Containers'].sum()
        st.metric("Total Containers", f"{unique_lane_totals:,.0f}")
    
    with col4:
        avg_share = volume_share['Volume_Share_Pct'].mean()
        st.metric("Avg Market Share", f"{avg_share:.1f}%")
    
    st.divider()
    
    # Filter options
    col1, col2 = st.columns(2)
    
    with col1:
        selected_lane = st.selectbox(
            "Filter by Lane",
            options=["All Lanes"] + sorted(volume_share['Lane'].unique().tolist()),
            index=0
        )
    
    with col2:
        min_share = st.slider(
            "Minimum Market Share (%)",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
            help="Only show carriers with at least this market share"
        )
    
    # Apply filters
    filtered_data = volume_share.copy()
    
    if selected_lane != "All Lanes":
        filtered_data = filtered_data[filtered_data['Lane'] == selected_lane]
    
    if min_share > 0:
        filtered_data = filtered_data[filtered_data['Volume_Share_Pct'] >= min_share]
    
    if filtered_data.empty:
        st.warning("No carriers match the selected filters.")
        return
    
    # Market share visualization
    st.subheader("Market Share by Carrier and Lane")
    
    # Create bar chart
    fig = px.bar(
        filtered_data.head(30),  # Top 30 to avoid overcrowding
        x='Dray SCAC(FL)',
        y='Volume_Share_Pct',
        color='Lane',
        title=f"Carrier Market Share{' - ' + selected_lane if selected_lane != 'All Lanes' else ''}",
        labels={
            'Dray SCAC(FL)': 'Carrier',
            'Volume_Share_Pct': 'Market Share (%)',
            'Lane': 'Lane'
        },
        hover_data=['Total_Containers', 'Weeks_Active', 'Avg_Weekly_Containers']
    )
    
    fig.update_layout(
        xaxis_tickangle=-45,
        height=500,
        showlegend=True
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Data table
    st.subheader("Market Share Details")
    
    display_cols = [
        'Dray SCAC(FL)', 'Lane', 'Volume_Share_Pct', 'Total_Containers',
        'Lane_Total_Containers', 'Weeks_Active', 'Avg_Weekly_Containers'
    ]
    
    # Add Category if it exists
    if 'Category' in filtered_data.columns:
        display_cols.insert(1, 'Category')
    
    # Add SSL if it exists
    if 'SSL' in filtered_data.columns:
        display_cols.insert(2, 'SSL')
    
    st.dataframe(
        filtered_data[display_cols].style.format({
            'Volume_Share_Pct': '{:.2f}%',
            'Total_Containers': '{:.0f}',
            'Lane_Total_Containers': '{:.0f}',
            'Avg_Weekly_Containers': '{:.1f}'
        }),
        use_container_width=True,
        height=400
    )


def show_weekly_trends_analysis(weekly_trends: pd.DataFrame, n_weeks: int):
    """Display weekly volume trends."""
    
    st.subheader(f"Weekly Volume Trends (Last {n_weeks} Weeks)")
    
    if weekly_trends.empty:
        st.warning("No weekly trend data available.")
        return
    
    # Get week columns
    week_columns = [col for col in weekly_trends.columns if col.startswith('Week_') and not col.endswith('Active')]
    
    if not week_columns:
        st.warning("No weekly data columns found.")
        return
    
    # Filter options
    selected_carrier = st.selectbox(
        "Filter by Carrier",
        options=["All Carriers"] + sorted(weekly_trends['Dray SCAC(FL)'].unique().tolist()),
        index=0,
        key="trend_carrier_filter"
    )
    
    selected_lane = st.selectbox(
        "Filter by Lane",
        options=["All Lanes"] + sorted(weekly_trends['Lane'].unique().tolist()),
        index=0,
        key="trend_lane_filter"
    )
    
    # Apply filters
    filtered_trends = weekly_trends.copy()
    
    if selected_carrier != "All Carriers":
        filtered_trends = filtered_trends[filtered_trends['Dray SCAC(FL)'] == selected_carrier]
    
    if selected_lane != "All Lanes":
        filtered_trends = filtered_trends[filtered_trends['Lane'] == selected_lane]
    
    if filtered_trends.empty:
        st.warning("No data matches the selected filters.")
        return
    
    # Line chart showing trends
    st.subheader("Volume Trend Visualization")
    
    # Prepare data for plotting
    plot_data = []
    for _, row in filtered_trends.head(10).iterrows():  # Top 10 carriers/lanes
        carrier_lane = f"{row['Dray SCAC(FL)']} - {row['Lane']}"
        for week_col in week_columns:
            week_num = int(week_col.replace('Week_', ''))
            plot_data.append({
                'Carrier-Lane': carrier_lane,
                'Week': week_num,
                'Containers': row[week_col]
            })
    
    plot_df = pd.DataFrame(plot_data)
    
    fig = px.line(
        plot_df,
        x='Week',
        y='Containers',
        color='Carrier-Lane',
        title="Container Volume Trends",
        markers=True,
        labels={'Containers': 'Container Count', 'Week': 'Week Number'}
    )
    
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)
    
    # Data table
    st.subheader("Weekly Volume Data")
    
    display_cols = ['Dray SCAC(FL)', 'Lane'] + week_columns + ['Total_Containers', 'Avg_Weekly']
    
    st.dataframe(
        filtered_trends[display_cols],
        use_container_width=True,
        height=400
    )


def show_participation_analysis(participation: pd.DataFrame, n_weeks: int):
    """Display carrier participation patterns."""
    
    st.subheader(f"Carrier Participation Analysis (Last {n_weeks} Weeks)")
    
    if participation.empty:
        st.warning("No participation data available.")
        return
    
    # Summary metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        avg_participation = participation['Participation_Rate_Pct'].mean()
        st.metric("Avg Participation Rate", f"{avg_participation:.1f}%")
    
    with col2:
        consistent_carriers = (participation['Participation_Rate_Pct'] == 100).sum()
        st.metric("Always Active Carriers", consistent_carriers)
    
    with col3:
        sporadic_carriers = (participation['Participation_Rate_Pct'] < 50).sum()
        st.metric("Sporadic Carriers (<50%)", sporadic_carriers)
    
    st.divider()
    
    # Participation rate distribution
    st.subheader("Participation Rate Distribution")
    
    fig = px.histogram(
        participation,
        x='Participation_Rate_Pct',
        nbins=20,
        title="Distribution of Carrier Participation Rates",
        labels={'Participation_Rate_Pct': 'Participation Rate (%)', 'count': 'Number of Carrier-Lane Pairs'},
        color_discrete_sequence=['#1f77b4']
    )
    
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
    
    # Detailed participation table
    st.subheader("Participation Details")
    
    # Filter
    min_participation = st.slider(
        "Minimum Participation Rate (%)",
        min_value=0,
        max_value=100,
        value=0,
        step=10,
        key="participation_filter"
    )
    
    filtered_participation = participation[
        participation['Participation_Rate_Pct'] >= min_participation
    ].copy()
    
    st.dataframe(
        filtered_participation.style.format({
            'Participation_Rate_Pct': '{:.1f}%'
        }),
        use_container_width=True,
        height=400
    )


def show_detailed_data_export(
    volume_share: pd.DataFrame,
    weekly_trends: pd.DataFrame,
    participation: pd.DataFrame
):
    """Provide detailed data tables and export options."""
    
    st.subheader("📥 Export Historic Volume Data")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if not volume_share.empty:
            csv = volume_share.to_csv(index=False)
            st.download_button(
                label="📊 Download Market Share Data",
                data=csv,
                file_name="historic_market_share.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    with col2:
        if not weekly_trends.empty:
            csv = weekly_trends.to_csv(index=False)
            st.download_button(
                label="📈 Download Weekly Trends",
                data=csv,
                file_name="historic_weekly_trends.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    with col3:
        if not participation.empty:
            csv = participation.to_csv(index=False)
            st.download_button(
                label="✅ Download Participation Data",
                data=csv,
                file_name="historic_participation.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    st.divider()
    
    # Show complete data tables
    with st.expander("📋 View Complete Market Share Data"):
        st.dataframe(volume_share, use_container_width=True)
    
    with st.expander("📋 View Complete Weekly Trends"):
        st.dataframe(weekly_trends, use_container_width=True)
    
    with st.expander("📋 View Complete Participation Data"):
        st.dataframe(participation, use_container_width=True)


__all__ = [
    "show_historic_volume_analysis",
    "show_market_share_analysis",
    "show_weekly_trends_analysis",
    "show_participation_analysis",
    "show_detailed_data_export",
]
