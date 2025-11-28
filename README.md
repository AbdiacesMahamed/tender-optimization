# Carrier Tender Optimization Dashboard

A Streamlit-based application for optimizing carrier allocations in transportation logistics. The system analyzes container volumes, carrier rates, and performance metrics to provide intelligent allocation recommendations.

## Features

- **Data Integration**: Merge GVT (container data), Rate data, and Performance data
- **Optimization Scenarios**: Multiple allocation strategies (Current, Performance, Cheapest, LP Optimized)
- **Constraint Management**: Apply operational constraints with priority scoring
- **Carrier Flips Tracking**: Track container movements between carriers
- **Export Capabilities**: Download optimized data and analysis reports

## Project Structure

```
Tender Optimization/
├── dashboard.py                 # Main Streamlit application entry point
├── streamlit_app.py            # Alternative entry point
├── requirements.txt            # Python dependencies
│
├── components/                  # UI and processing components
│   ├── __init__.py             # Component exports
│   ├── config_styling.py       # Page configuration and CSS
│   ├── data_loader.py          # File upload and data loading
│   ├── data_processor.py       # Data validation and merging
│   ├── filters.py              # Filter interface and application
│   ├── metrics.py              # Metrics calculation and display
│   ├── constraints_processor.py # Constraint file processing
│   ├── container_tracer.py     # Container movement tracking
│   ├── summary_tables.py       # Summary table generation
│   ├── analytics.py            # Advanced analytics
│   ├── visualizations.py       # Charts and graphs
│   └── performance_*.py        # Performance scoring utilities
│
├── optimization/               # Optimization algorithms
│   ├── __init__.py            # Module exports
│   ├── optimization.py        # Main orchestration
│   ├── linear_programming.py  # LP optimization
│   ├── cascading_logic.py     # Cascading allocation with constraints
│   ├── cheapest_logic.py      # Cheapest carrier allocation
│   ├── performance_logic.py   # Performance-based allocation
│   └── historic_volume.py     # Historical volume analysis
│
└── docs/                       # Documentation
    ├── CONSTRAINTS.md          # Constraint system documentation
    └── OPTIMIZATION.md         # Optimization strategies documentation
```

## Quick Start

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:

   ```bash
   streamlit run dashboard.py
   ```

3. Upload your data files:
   - **GVT File**: Container movement data (required)
   - **Rate File**: Carrier rates by lane (required)
   - **Performance File**: Carrier performance scores (optional)
   - **Constraints File**: Operational constraints (optional)

## Data Requirements

### GVT File (Container Data)

Required columns:

- `Discharged Port` - Port of discharge
- `Facility` - Destination facility code
- `Dray SCAC(FL)` - Carrier SCAC code
- `Container Numbers` - Comma-separated container IDs
- `Week Number` - Week identifier
- `Category` - Business category (FBA FCL, Retail CD, etc.)

### Rate File

Required columns:

- `Lookup` - Unique key (Carrier + Port + Facility)
- `Base Rate` - Rate per container
- Lane/Port/Facility identifiers

### Performance File (Optional)

- `Carrier` - Carrier SCAC code
- `Week Number` - Week identifier
- `Performance_Score` - Score between 0-1

### Constraints File (Optional)

See [Constraints Documentation](docs/CONSTRAINTS.md)

## Optimization Scenarios

| Scenario              | Description                                                    |
| --------------------- | -------------------------------------------------------------- |
| **Current Selection** | Shows data as-is from GVT file                                 |
| **Performance**       | Allocates all volume to highest-performing carrier per lane    |
| **Cheapest Cost**     | Allocates all volume to cheapest carrier per lane              |
| **Optimized (LP)**    | Linear programming optimization balancing cost and performance |

The Optimized scenario uses configurable weights (default 70% cost, 30% performance) and applies historical volume constraints to limit carrier growth.

## License

Internal use only.
