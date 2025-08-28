"""
Interactive visualizations module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from .config_styling import section_header

def show_interactive_visualizations(final_filtered_data):
    """Display interactive visualizations section"""
    section_header("📊 Interactive Visualizations")

    if len(final_filtered_data) > 0:
        viz_tabs = st.tabs(["🎯 Cost vs Performance", "🌍 Geographic Analysis", "📈 Time Series", "🔄 Correlation Matrix"])
        
        with viz_tabs[0]:
            show_cost_vs_performance(final_filtered_data)
        
        with viz_tabs[1]:
            show_geographic_analysis(final_filtered_data)
        
        with viz_tabs[2]:
            show_time_series_analysis(final_filtered_data)
        
        with viz_tabs[3]:
            show_correlation_analysis(final_filtered_data)

def show_cost_vs_performance(final_filtered_data):
    """Show cost vs performance scatter analysis"""
    st.markdown("**💰 Cost vs Performance Scatter Analysis**")
    
    if 'Performance_Score' in final_filtered_data.columns:
        # Interface controls
        viz_col1, viz_col2 = st.columns(2)
        
        with viz_col1:
            size_metric = st.selectbox("Bubble Size", ["Container Count", "Total Rate", "Potential Savings"])
            color_metric = st.selectbox("Color By", ["Dray SCAC(FL)", "Week Number", "Lane"])
        
        with viz_col2:
            min_containers = st.slider("Min Container Count", 1, int(final_filtered_data['Container Count'].max()), 1)
            
        # Filter data
        viz_data = final_filtered_data[final_filtered_data['Container Count'] >= min_containers]
        
        # Create scatter plot
        fig = px.scatter(
            viz_data,
            x='Base Rate',
            y='Performance_Score',
            size=size_metric,
            color=color_metric,
            hover_data=['Lane', 'Week Number', 'Container Count'],
            title="Cost vs Performance Analysis",
            labels={'Base Rate': 'Base Rate ($)', 'Performance_Score': 'Performance Score (%)'}
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        # Quadrant analysis
        show_quadrant_analysis(viz_data)
    else:
        st.info("Performance data required for cost vs performance analysis.")

def show_quadrant_analysis(viz_data):
    """Show quadrant analysis of cost vs performance"""
    med_rate = viz_data['Base Rate'].median()
    med_perf = viz_data['Performance_Score'].median()
    
    quadrants = []
    for _, row in viz_data.iterrows():
        if row['Base Rate'] <= med_rate and row['Performance_Score'] >= med_perf:
            quad = "🟢 Low Cost, High Performance"
        elif row['Base Rate'] <= med_rate and row['Performance_Score'] < med_perf:
            quad = "🟡 Low Cost, Low Performance"
        elif row['Base Rate'] > med_rate and row['Performance_Score'] >= med_perf:
            quad = "🟠 High Cost, High Performance"
        else:
            quad = "🔴 High Cost, Low Performance"
        quadrants.append(quad)
    
    viz_data_quad = viz_data.copy()
    viz_data_quad['Quadrant'] = quadrants
    
    quad_summary = viz_data_quad.groupby('Quadrant').agg({
        'Container Count': 'sum',
        'Total Rate': 'sum',
        'Dray SCAC(FL)': 'nunique'
    }).round(2)
    quad_summary.columns = ['Total Containers', 'Total Cost', 'Unique Carriers']
    
    st.write("**Quadrant Analysis:**")
    st.dataframe(quad_summary, use_container_width=True)

def show_geographic_analysis(final_filtered_data):
    """Show geographic and route analysis"""
    st.markdown("**🌍 Geographic and Route Analysis**")
    
    # Port analysis
    port_analysis = final_filtered_data.groupby('Discharged Port').agg({
        'Container Count': 'sum',
        'Total Rate': 'sum',
        'Potential Savings': 'sum',
        'Dray SCAC(FL)': 'nunique'
    }).reset_index()
    
    geo_col1, geo_col2 = st.columns(2)
    
    with geo_col1:
        geo_metric = st.selectbox("Map Metric", ["Container Count", "Total Rate", "Potential Savings"])
        
    with geo_col2:
        top_n_ports = st.slider("Show Top N Ports", 5, 20, 10)
    
    # Port volume chart
    show_port_analysis(port_analysis, geo_metric, top_n_ports)
    
    # Lane analysis heatmap
    show_lane_heatmap(final_filtered_data)

def show_port_analysis(port_analysis, geo_metric, top_n_ports):
    """Show port analysis bar chart"""
    top_ports = port_analysis.nlargest(top_n_ports, geo_metric)
    
    fig = px.bar(
        top_ports,
        x='Discharged Port',
        y=geo_metric,
        title=f'Top {top_n_ports} Ports by {geo_metric}',
        color=geo_metric,
        color_continuous_scale='viridis'
    )
    fig.update_layout(height=400, xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

def show_lane_heatmap(final_filtered_data):
    """Show lane performance heatmap"""
    st.write("**Lane Performance Heatmap:**")
    lane_heatmap = final_filtered_data.pivot_table(
        values='Potential Savings',
        index='Discharged Port',
        columns='Facility',
        aggfunc='sum',
        fill_value=0
    )
    
    # Limit to top ports and facilities for readability
    if len(lane_heatmap) > 15:
        top_ports_for_heatmap = lane_heatmap.sum(axis=1).nlargest(15).index
        lane_heatmap = lane_heatmap.loc[top_ports_for_heatmap]
    
    if len(lane_heatmap.columns) > 15:
        top_facilities = lane_heatmap.sum(axis=0).nlargest(15).index
        lane_heatmap = lane_heatmap[top_facilities]
    
    fig = px.imshow(
        lane_heatmap.values,
        labels=dict(x="Facility", y="Port", color="Potential Savings"),
        x=lane_heatmap.columns,
        y=lane_heatmap.index,
        aspect="auto",
        title="Potential Savings by Port-Facility Combination"
    )
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

def show_time_series_analysis(final_filtered_data):
    """Show time series analysis"""
    st.markdown("**📈 Time Series Analysis**")
    
    # Weekly trends
    weekly_trends = final_filtered_data.groupby('Week Number').agg({
        'Container Count': 'sum',
        'Total Rate': 'sum',
        'Potential Savings': 'sum',
        'Base Rate': 'mean'
    }).reset_index()
    
    # Multiple metrics chart
    show_weekly_trends_chart(weekly_trends)
    
    # Growth rate analysis
    show_growth_rate_analysis(weekly_trends)

def show_weekly_trends_chart(weekly_trends):
    """Show weekly trends in a subplot chart"""
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Container Volume', 'Total Costs', 'Potential Savings', 'Average Rate'),
        specs=[[{"secondary_y": False}, {"secondary_y": False}],
               [{"secondary_y": False}, {"secondary_y": False}]]
    )
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends['Container Count'], 
                  mode='lines+markers', name='Containers'),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends['Total Rate'], 
                  mode='lines+markers', name='Total Cost'),
        row=1, col=2
    )
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends['Potential Savings'], 
                  mode='lines+markers', name='Savings'),
        row=2, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends['Base Rate'], 
                  mode='lines+markers', name='Avg Rate'),
        row=2, col=2
    )
    
    fig.update_layout(height=600, showlegend=False, title_text="Weekly Trends Analysis")
    st.plotly_chart(fig, use_container_width=True)

def show_growth_rate_analysis(weekly_trends):
    """Show growth rate analysis"""
    # Growth rate calculation
    weekly_trends['Container_Growth'] = weekly_trends['Container Count'].pct_change() * 100
    weekly_trends['Cost_Growth'] = weekly_trends['Total Rate'].pct_change() * 100
    
    growth_summary = pd.DataFrame({
        'Week': weekly_trends['Week Number'],
        'Volume Growth (%)': weekly_trends['Container_Growth'].round(1),
        'Cost Growth (%)': weekly_trends['Cost_Growth'].round(1)
    }).dropna()
    
    st.write("**Week-over-Week Growth Rates:**")
    st.dataframe(growth_summary, use_container_width=True)

def show_correlation_analysis(final_filtered_data):
    """Show correlation analysis"""
    st.markdown("**🔄 Correlation Analysis**")
    
    # Prepare numeric data for correlation
    numeric_cols = ['Base Rate', 'Container Count', 'Total Rate', 'Potential Savings', 'Week Number']
    if 'Performance_Score' in final_filtered_data.columns:
        numeric_cols.append('Performance_Score')
    
    corr_data = final_filtered_data[numeric_cols].corr()
    
    # Correlation heatmap
    show_correlation_heatmap(corr_data)
    
    # Key insights
    show_correlation_insights(corr_data)

def show_correlation_heatmap(corr_data):
    """Show correlation heatmap"""
    fig = px.imshow(
        corr_data.values,
        labels=dict(color="Correlation"),
        x=corr_data.columns,
        y=corr_data.index,
        color_continuous_scale='RdBu',
        aspect="auto",
        title="Correlation Matrix of Key Metrics"
    )
    
    # Add correlation values as text
    for i in range(len(corr_data.columns)):
        for j in range(len(corr_data.columns)):
            fig.add_annotation(
                x=i, y=j,
                text=str(round(corr_data.iloc[j, i], 2)),
                showarrow=False,
                font=dict(color="white" if abs(corr_data.iloc[j, i]) > 0.5 else "black")
            )
    
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

def show_correlation_insights(corr_data):
    """Show correlation insights"""
    st.write("**Key Correlations:**")
    insights = []
    
    for i, col1 in enumerate(corr_data.columns):
        for j, col2 in enumerate(corr_data.columns):
            if i < j:  # Avoid duplicates
                corr_val = corr_data.iloc[i, j]
                if abs(corr_val) > 0.3:  # Significant correlation
                    strength = "Strong" if abs(corr_val) > 0.7 else "Moderate"
                    direction = "Positive" if corr_val > 0 else "Negative"
                    insights.append({
                        'Variables': f"{col1} vs {col2}",
                        'Correlation': f"{corr_val:.3f}",
                        'Relationship': f"{strength} {direction}"
                    })
    
    if insights:
        insights_df = pd.DataFrame(insights)
        st.dataframe(insights_df, use_container_width=True)
    else:
        st.info("No significant correlations found (threshold: |r| > 0.3)")
