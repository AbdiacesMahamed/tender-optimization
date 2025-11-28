"""
Advanced analytics and machine learning module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from sklearn.linear_model import LinearRegression
from .config_styling import section_header
from .utils import get_rate_columns


def show_advanced_analytics(final_filtered_data):
    """Display advanced analytics section"""
    # Get current rate type for display
    rate_type = st.session_state.get('rate_type', 'Base Rate')
    rate_type_label = f" ({rate_type})" if rate_type == 'CPC' else ""
    
    section_header(f"🔮 Advanced Analytics & Machine Learning{rate_type_label}")

    if len(final_filtered_data) > 0:
        analytics_tabs = st.tabs(["📈 Predictive Analytics", "🎯 Performance Trends", "🔍 Anomaly Detection"])
        
        with analytics_tabs[0]:
            show_predictive_analytics(final_filtered_data)
        
        with analytics_tabs[1]:
            show_performance_trends(final_filtered_data)
        
        with analytics_tabs[2]:
            show_anomaly_detection(final_filtered_data)

def show_predictive_analytics(final_filtered_data):
    """Show predictive analytics tab"""
    st.markdown("**📊 Container Volume Forecasting**")
    
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    
    # Prepare time series data
    weekly_data = final_filtered_data.groupby(['Week Number', 'Lane']).agg({
        'Container Count': 'sum',
        rate_cols['total_rate']: 'sum',
        rate_cols['rate']: 'mean'
    }).reset_index()
    
    if len(weekly_data) >= 4:  # Need minimum data for forecasting
        show_forecasting_interface(weekly_data)
    else:
        st.info("Need at least 4 weeks of data for forecasting. Add more data or adjust filters.")

def show_forecasting_interface(weekly_data):
    """Show the forecasting interface"""
    col1, col2 = st.columns(2)
    
    with col1:
        selected_lane = st.selectbox(
            "Select Lane for Forecasting",
            options=weekly_data['Lane'].unique(),
            key="forecast_lane"
        )
        
        forecast_weeks = st.slider("Weeks to Forecast", 1, 8, 4)
    
    with col2:
        st.write("**Forecast Parameters:**")
        confidence_level = st.slider("Confidence Level (%)", 80, 99, 95)
        
    if st.button("🚀 Generate Forecast"):
        generate_forecast(weekly_data, selected_lane, forecast_weeks, confidence_level)

def generate_forecast(weekly_data, selected_lane, forecast_weeks, confidence_level):
    """Generate and display forecast"""
    lane_data = weekly_data[weekly_data['Lane'] == selected_lane].sort_values('Week Number')
    
    if len(lane_data) >= 3:
        # Simple forecasting using linear trend
        X = lane_data['Week Number'].values.reshape(-1, 1)
        y = lane_data['Container Count'].values
        
        model = LinearRegression()
        model.fit(X, y)
        
        # Generate forecast
        last_week = lane_data['Week Number'].max()
        future_weeks = np.arange(last_week + 1, last_week + 1 + forecast_weeks).reshape(-1, 1)
        forecast = model.predict(future_weeks)
        
        # Create visualization
        fig = go.Figure()
        
        # Historical data
        fig.add_trace(go.Scatter(
            x=lane_data['Week Number'],
            y=lane_data['Container Count'],
            mode='lines+markers',
            name='Historical',
            line=dict(color='blue')
        ))
        
        # Forecast
        fig.add_trace(go.Scatter(
            x=future_weeks.flatten(),
            y=forecast,
            mode='lines+markers',
            name='Forecast',
            line=dict(color='red', dash='dash')
        ))
        
        fig.update_layout(
            title=f'Container Volume Forecast - {selected_lane}',
            xaxis_title='Week Number',
            yaxis_title='Container Count',
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Forecast summary
        forecast_df = pd.DataFrame({
            'Week': future_weeks.flatten(),
            'Forecasted Containers': forecast.astype(int),
            'Confidence Level': f"{confidence_level}%"
        })
        st.dataframe(forecast_df, use_container_width=True)
    else:
        st.warning("Not enough historical data for this lane. Select a different lane.")

def show_performance_trends(final_filtered_data):
    """Show performance trends analysis"""
    st.markdown("**📊 Carrier Performance Trends**")
    
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    
    if 'Performance_Score' in final_filtered_data.columns:
        # Performance trend analysis
        perf_trends = final_filtered_data.groupby(['Week Number', 'Dray SCAC(FL)']).agg({
            'Performance_Score': 'mean',
            'Container Count': 'sum',
            rate_cols['rate']: 'mean'
        }).reset_index()
        
        # Select top carriers by volume
        top_carriers = final_filtered_data.groupby('Dray SCAC(FL)')['Container Count'].sum().nlargest(5).index.tolist()
        
        show_trend_analysis_interface(final_filtered_data, perf_trends, top_carriers, rate_cols)
        
        # Performance ranking
        show_performance_ranking(final_filtered_data)
    else:
        st.info("Performance data required for trend analysis. Upload performance data to enable this feature.")

def show_trend_analysis_interface(final_filtered_data, perf_trends, top_carriers, rate_cols):
    """Show trend analysis interface"""
    trend_col1, trend_col2 = st.columns(2)
    
    with trend_col1:
        selected_carriers = st.multiselect(
            "Select Carriers for Trend Analysis",
            options=final_filtered_data['Dray SCAC(FL)'].unique(),
            default=top_carriers[:3],
            key="trend_carriers"
        )
    
    with trend_col2:
        trend_metric = st.selectbox(
            "Trend Metric",
            ["Performance_Score", rate_cols['rate'], "Container Count"]
        )
    
    if selected_carriers:
        trend_data = perf_trends[perf_trends['Dray SCAC(FL)'].isin(selected_carriers)]
        
        fig = px.line(
            trend_data,
            x='Week Number',
            y=trend_metric,
            color='Dray SCAC(FL)',
            title=f'{trend_metric} Trends by Carrier',
            markers=True
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

def show_performance_ranking(final_filtered_data):
    """Show performance ranking table"""
    # Ensure Performance_Score is numeric
    final_filtered_data['Performance_Score'] = pd.to_numeric(final_filtered_data['Performance_Score'], errors='coerce')
    
    current_perf = final_filtered_data.groupby('Dray SCAC(FL)')['Performance_Score'].mean().sort_values(ascending=False)
    st.write("**Current Performance Ranking:**")
    perf_rank_df = pd.DataFrame({
        'Rank': range(1, len(current_perf) + 1),
        'Carrier': current_perf.index,
        'Avg Performance': current_perf.values.round(1)
    })
    st.dataframe(perf_rank_df.head(10), use_container_width=True)

def show_anomaly_detection(final_filtered_data):
    """Show anomaly detection analysis"""
    st.markdown("**🚨 Anomaly Detection**")
    
    # Get dynamic rate columns
    rate_cols = get_rate_columns()
    rate_type_label = "CPC" if rate_cols['rate'] == 'CPC' else "Rate"
    
    # Rate anomaly detection
    Q1 = final_filtered_data[rate_cols['rate']].quantile(0.25)
    Q3 = final_filtered_data[rate_cols['rate']].quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    
    anomalies = final_filtered_data[
        (final_filtered_data[rate_cols['rate']] < lower_bound) | 
        (final_filtered_data[rate_cols['rate']] > upper_bound)
    ]
    
    # Show anomaly metrics
    show_anomaly_metrics(anomalies, final_filtered_data, lower_bound, upper_bound, rate_type_label)
    
    # Show anomaly details and visualization
    if len(anomalies) > 0:
        show_anomaly_details(anomalies, final_filtered_data, lower_bound, rate_cols)

def show_anomaly_metrics(anomalies, final_filtered_data, lower_bound, upper_bound, rate_type_label):
    """Show anomaly detection metrics"""
    anom_col1, anom_col2, anom_col3 = st.columns(3)
    
    with anom_col1:
        st.metric(f"🔍 {rate_type_label} Anomalies", len(anomalies))
    with anom_col2:
        st.metric("📊 Normal Range", f"${lower_bound:.0f} - ${upper_bound:.0f}")
    with anom_col3:
        anomaly_pct = (len(anomalies) / len(final_filtered_data) * 100)
        st.metric("📈 Anomaly Rate", f"{anomaly_pct:.1f}%")

def show_anomaly_details(anomalies, final_filtered_data, lower_bound, rate_cols):
    """Show anomaly details table and visualization"""
    st.write(f"**Detected {rate_cols['rate']} Anomalies:**")
    anomaly_display = anomalies[['Lane', 'Dray SCAC(FL)', 'Week Number', rate_cols['rate'], 'Container Count']].copy()
    
    # Vectorized anomaly type assignment
    anomaly_display['Anomaly Type'] = np.where(
        anomaly_display[rate_cols['rate']] < lower_bound,
        'Unusually Low',
        'Unusually High'
    )
    st.dataframe(anomaly_display.sort_values(rate_cols['rate']), use_container_width=True)
    
    # Visualization
    fig = px.box(
        final_filtered_data,
        y=rate_cols['rate'],
        title=f'{rate_cols["rate"]} Distribution with Anomalies',
        points='outliers'
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
