"""
Configuration and styling module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st

def configure_page():
    """Configure Streamlit page settings"""
    st.set_page_config(
        page_title="Carrier Tender Optimization Dashboard",
        page_icon="🚚",
        layout="wide"
    )

def apply_custom_css():
    """Apply custom CSS styling to the dashboard"""
    st.markdown("""
    <style>
        .main-header {
            font-size: 3rem;
            font-weight: bold;
            text-align: center;
            color: #1f77b4;
            margin-bottom: 2rem;
        }
        .section-header {
            font-size: 1.5rem;
            font-weight: bold;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 0.5rem;
            margin-top: 2rem;
            margin-bottom: 1rem;
        }
        .metric-container {
            background-color: #f8f9fa;
            padding: 1rem;
            border-radius: 0.5rem;
            border-left: 4px solid #3498db;
            margin: 0.5rem 0;
        }
        .info-box {
            background-color: #e8f4fd;
            padding: 1rem;
            border-radius: 0.5rem;
            border: 1px solid #bee5eb;
            margin: 1rem 0;
        }
        .success-box {
            background-color: #d4edda;
            padding: 1rem;
            border-radius: 0.5rem;
            border: 1px solid #c3e6cb;
            margin: 1rem 0;
        }
    </style>
    """, unsafe_allow_html=True)

def show_header():
    """Display the main dashboard header"""
    st.markdown('<h1 class="main-header">🚚 Carrier Tender Optimization Dashboard</h1>', unsafe_allow_html=True)

def section_header(title):
    """Create a styled section header"""
    st.markdown(f'<div class="section-header">{title}</div>', unsafe_allow_html=True)

def info_box(message):
    """Create an info box"""
    st.markdown(f'<div class="info-box">{message}</div>', unsafe_allow_html=True)

def success_box(message):
    """Create a success box"""
    st.markdown(f'<div class="success-box">{message}</div>', unsafe_allow_html=True)
