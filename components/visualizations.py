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

def get_rate_columns():
    """Get the appropriate rate column names based on selected rate type"""
    rate_type = st.session_state.get('rate_type', 'Base Rate')
    
    if rate_type == 'CPC':
        return {
            'rate': 'CPC',
            'total_rate': 'Total CPC'
        }
    else:
        return {
            'rate': 'Base Rate',
            'total_rate': 'Total Rate'
        }

def show_interactive_visualizations(final_filtered_data):
    """Display interactive visualizations section"""
    # Get current rate type for display
    rate_type = st.session_state.get('rate_type', 'Base Rate')
    rate_type_label = f" ({rate_type})" if rate_type == 'CPC' else ""
    
    section_header(f"📊 Interactive Visualizations{rate_type_label}")

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
    
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    
    if 'Performance_Score' in final_filtered_data.columns:
        # Interface controls
        viz_col1, viz_col2 = st.columns(2)
        
        with viz_col1:
            size_metric = st.selectbox("Bubble Size", ["Container Count", rate_cols['total_rate']])
            color_metric = st.selectbox("Color By", ["Dray SCAC(FL)", "Week Number", "Lane"])
        
        with viz_col2:
            min_containers = st.slider("Min Container Count", 1, int(final_filtered_data['Container Count'].max()), 1)
            
        # Filter data
        viz_data = final_filtered_data[final_filtered_data['Container Count'] >= min_containers]
        
        # Create scatter plot
        fig = px.scatter(
            viz_data,
            x=rate_cols['rate'],
            y='Performance_Score',
            size=size_metric,
            color=color_metric,
            hover_data=['Lane', 'Week Number', 'Container Count'],
            title="Cost vs Performance Analysis",
            labels={rate_cols['rate']: f'{rate_cols["rate"]} ($)', 'Performance_Score': 'Performance Score (%)'}
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        # Quadrant analysis
        show_quadrant_analysis(viz_data, rate_cols)
    else:
        st.info("Performance data required for cost vs performance analysis.")

def show_quadrant_analysis(viz_data, rate_cols):
    """Show quadrant analysis of cost vs performance"""
    # Vectorized calculations
    med_rate = viz_data[rate_cols['rate']].median()
    med_perf = viz_data['Performance_Score'].median()
    
    # Vectorized quadrant assignment
    low_cost = viz_data[rate_cols['rate']] <= med_rate
    high_perf = viz_data['Performance_Score'] >= med_perf
    
    conditions = [
        (low_cost & high_perf),
        (low_cost & ~high_perf),
        (~low_cost & high_perf),
        (~low_cost & ~high_perf)
    ]
    choices = [
        "� Low Cost, High Performance",
        "🟡 Low Cost, Low Performance",
        "🟠 High Cost, High Performance",
        "🔴 High Cost, Low Performance"
    ]
    
    viz_data = viz_data.copy()
    viz_data['Quadrant'] = np.select(conditions, choices, default="Unknown")
    
    # Optimized aggregation
    quad_summary = viz_data.groupby('Quadrant', as_index=False).agg({
        'Container Count': 'sum',
        rate_cols['total_rate']: 'sum',
        'Dray SCAC(FL)': 'nunique'
    })
    quad_summary.columns = ['Quadrant', 'Total Containers', 'Total Cost', 'Unique Carriers']
    quad_summary = quad_summary.round(2)
    
    st.write("**Quadrant Analysis:**")
    st.dataframe(quad_summary, use_container_width=True)

def show_geographic_analysis(final_filtered_data):
    """Show geographic and route analysis"""
    st.markdown("**🌍 Geographic and Route Analysis**")
    
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    
    # Port analysis
    port_analysis = final_filtered_data.groupby('Discharged Port').agg({
        'Container Count': 'sum',
        rate_cols['total_rate']: 'sum',
        'Dray SCAC(FL)': 'nunique'
    }).reset_index()
    
    geo_col1, geo_col2 = st.columns(2)
    
    with geo_col1:
        geo_metric = st.selectbox("Map Metric", ["Container Count", rate_cols['total_rate']])
        
    with geo_col2:
        top_n_ports = st.slider("Show Top N Ports", 5, 20, 10)
    
    # Port volume chart
    show_port_analysis(port_analysis, geo_metric, top_n_ports)
    
    # Lane analysis heatmap
    show_lane_heatmap(final_filtered_data, rate_cols)

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

def show_lane_heatmap(final_filtered_data, rate_cols):
    """Show lane performance heatmap"""
    st.write("**Lane Cost Heatmap:**")
    
    # Optimize pivot table creation
    lane_heatmap = final_filtered_data.pivot_table(
        values=rate_cols['total_rate'],
        index='Discharged Port',
        columns='Facility',
        aggfunc='sum',
        fill_value=0
    )
    
    # Limit to top ports and facilities for readability - vectorized operations
    max_items = 15
    if len(lane_heatmap) > max_items:
        top_ports = lane_heatmap.sum(axis=1).nlargest(max_items).index
        lane_heatmap = lane_heatmap.loc[top_ports]
    
    if len(lane_heatmap.columns) > max_items:
        top_facilities = lane_heatmap.sum(axis=0).nlargest(max_items).index
        lane_heatmap = lane_heatmap[top_facilities]
    
    fig = px.imshow(
        lane_heatmap.values,
        labels=dict(x="Facility", y="Port", color="Total Cost"),
        x=lane_heatmap.columns,
        y=lane_heatmap.index,
        aspect="auto",
        title=f"Total Cost by Port-Facility Combination ({rate_cols['rate']})"
    )
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

def show_time_series_analysis(final_filtered_data):
    """Show time series analysis"""
    st.markdown("**📈 Time Series Analysis**")
    
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    
    # Weekly trends
    weekly_trends = final_filtered_data.groupby('Week Number').agg({
        'Container Count': 'sum',
        rate_cols['total_rate']: 'sum',
        rate_cols['rate']: 'mean'
    }).reset_index()
    
    # Multiple metrics chart
    show_weekly_trends_chart(weekly_trends, rate_cols)
    
    # Growth rate analysis
    show_growth_rate_analysis(weekly_trends, rate_cols)

def show_weekly_trends_chart(weekly_trends, rate_cols):
    """Show weekly trends in a subplot chart"""
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Container Volume', 'Total Costs', 'Average Rate', 'Cost per Container'),
        specs=[[{"secondary_y": False}, {"secondary_y": False}],
               [{"secondary_y": False}, {"secondary_y": False}]]
    )
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends['Container Count'], 
                  mode='lines+markers', name='Containers'),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends[rate_cols['total_rate']], 
                  mode='lines+markers', name='Total Cost'),
        row=1, col=2
    )
    
    # Calculate cost per container
    weekly_trends['Cost_Per_Container'] = weekly_trends[rate_cols['total_rate']] / weekly_trends['Container Count']
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends[rate_cols['rate']], 
                  mode='lines+markers', name='Avg Rate'),
        row=2, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=weekly_trends['Week Number'], y=weekly_trends['Cost_Per_Container'], 
                  mode='lines+markers', name='Cost/Container'),
        row=2, col=2
    )
    
    fig.update_layout(height=600, showlegend=False, title_text="Weekly Trends Analysis")
    st.plotly_chart(fig, use_container_width=True)

def show_growth_rate_analysis(weekly_trends, rate_cols):
    """Show growth rate analysis"""
    # Growth rate calculation
    weekly_trends['Container_Growth'] = weekly_trends['Container Count'].pct_change() * 100
    weekly_trends['Cost_Growth'] = weekly_trends[rate_cols['total_rate']].pct_change() * 100
    
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
    
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    
    # Prepare numeric data for correlation
    numeric_cols = [rate_cols['rate'], 'Container Count', rate_cols['total_rate'], 'Week Number']
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
