"""
Streamlit Cloud Entry Point for Carrier Tender Optimization Dashboard

This file serves as the main entry point for Streamlit Cloud deployment.
It imports and runs the dashboard from the "Tender Optimization" subdirectory.

GitHub Repository Structure:
- streamlit_app.py (this file - repo root)
- Tender Optimization/
  - dashboard.py (main application)
  - components/ (application modules)
"""

import sys
from pathlib import Path

# Add the "Tender Optimization" directory to Python path
tender_opt_path = Path(__file__).parent / "Tender Optimization"
sys.path.insert(0, str(tender_opt_path))

# Import the main dashboard application
from dashboard import main

# Run the dashboard
if __name__ == "__main__":
    main()
