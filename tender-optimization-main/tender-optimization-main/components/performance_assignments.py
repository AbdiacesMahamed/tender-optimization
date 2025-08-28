"""
Performance Assignment Module
Manages and tracks carrier performance score assignments
"""
import pandas as pd
import streamlit as st
from datetime import datetime

class PerformanceAssignmentTracker:
    """Track and manage carrier performance score assignments"""
    
    def __init__(self):
        self.assignments = []
        self.processing_log = []
    
    def log_assignment(self, carrier, assignment_type, score_value, records_affected=0):
        """Log a performance score assignment"""
        assignment = {
            'Carrier': carrier,
            'Assignment_Type': assignment_type,
            'Assigned_Score': score_value,
            'Records_Affected': records_affected,
            'Timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.assignments.append(assignment)
    
    def log_processing_step(self, step_name, details):
        """Log a processing step"""
        log_entry = {
            'Step': step_name,
            'Details': details,
            'Timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.processing_log.append(log_entry)
    
    def get_assignments_table(self):
        """Get performance assignments as a DataFrame"""
        if not self.assignments:
            return pd.DataFrame()
        return pd.DataFrame(self.assignments)
    
    def get_processing_log_table(self):
        """Get processing log as a DataFrame"""
        if not self.processing_log:
            return pd.DataFrame()
        return pd.DataFrame(self.processing_log)
    
    def show_assignments_summary(self):
        """Display a summary of performance assignments"""
        if not self.assignments:
            st.info("No performance assignments recorded")
            return
        
        assignments_df = self.get_assignments_table()
        
        with st.expander("📊 Performance Score Assignments Summary"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                total_carriers = len(assignments_df)
                st.metric("Carriers Processed", total_carriers)
            
            with col2:
                total_records = assignments_df['Records_Affected'].sum()
                st.metric("Total Records Filled", total_records)
            
            with col3:
                avg_score = assignments_df['Assigned_Score'].mean()
                st.metric("Average Assigned Score", f"{avg_score:.3f}")
            
            st.markdown("### Assignment Details")
            
            # Group by assignment type
            type_summary = assignments_df.groupby('Assignment_Type').agg({
                'Carrier': 'count',
                'Records_Affected': 'sum',
                'Assigned_Score': 'mean'
            }).round(3)
            type_summary.columns = ['Carriers', 'Records_Affected', 'Avg_Score']
            st.dataframe(type_summary, use_container_width=True)
            
            st.markdown("### Detailed Assignments")
            display_df = assignments_df[['Carrier', 'Assignment_Type', 'Assigned_Score', 'Records_Affected']]
            st.dataframe(display_df, use_container_width=True)
    
    def clear_assignments(self):
        """Clear all assignments and logs"""
        self.assignments = []
        self.processing_log = []

# Global tracker instance
performance_tracker = PerformanceAssignmentTracker()

def track_performance_assignment(carrier, assignment_type, score_value, records_affected=0):
    """Helper function to track a performance assignment"""
    performance_tracker.log_assignment(carrier, assignment_type, score_value, records_affected)

def track_processing_step(step_name, details):
    """Helper function to track a processing step"""
    performance_tracker.log_processing_step(step_name, details)

def show_performance_assignments_table():
    """Display the performance assignments table"""
    performance_tracker.show_assignments_summary()

def clear_performance_tracking():
    """Clear all performance tracking data"""
    performance_tracker.clear_assignments()

def export_performance_assignments():
    """Export performance assignments to CSV"""
    assignments_df = performance_tracker.get_assignments_table()
    if not assignments_df.empty:
        csv_data = assignments_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Performance Assignments",
            data=csv_data,
            file_name=f'performance_assignments_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
            mime='text/csv'
        )
