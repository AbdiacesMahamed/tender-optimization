# Historic Volume Analysis - Documentation

## Overview

The historic volume analysis module calculates carrier market share based on **historical data only**. It analyzes the last 5 completed weeks (configurable) and **excludes the current week and any future weeks** based on today's date.

## Key Features

✅ **Automatic Week Filtering**: Uses ISO week numbers and today's date to exclude current/future weeks  
✅ **Market Share Calculation**: Shows what percentage of volume each carrier handled per lane  
✅ **Weekly Trends**: Visualizes how carrier volume changed week-by-week  
✅ **Participation Analysis**: Identifies consistent vs sporadic carriers  
✅ **Configurable Lookback**: Analyze last 3, 5, 8, or 10 weeks

## How It Works

### 1. Week Filtering Logic

```python
from datetime import datetime
from optimization import filter_historical_weeks, get_current_week_number

# Get current ISO week number
current_week = get_current_week_number()  # e.g., 44 for November 2025
print(f"Current week: {current_week}")

# Filter to only include completed weeks (< current week)
historical_data = filter_historical_weeks(data)
# If today is Week 44, this returns only data from Weeks 1-43
```

**Important**: The module uses ISO week numbers (1-53) based on Python's `isocalendar()` method.

### 2. Get Last N Weeks

```python
from optimization import get_last_n_weeks

# Get data for last 5 completed weeks
last_5_weeks = get_last_n_weeks(data, n_weeks=5)

# Example: If current week is 44
# Returns data for weeks: 39, 40, 41, 42, 43 (most recent 5 completed)
```

### 3. Calculate Market Share

```python
from optimization import calculate_carrier_volume_share

# Calculate carrier market share for each lane
volume_share = calculate_carrier_volume_share(data, n_weeks=5)

# Returns DataFrame with:
# - Carrier: Carrier identifier
# - Lane: Lane identifier
# - Total_Containers: Containers handled by carrier
# - Lane_Total_Containers: Total containers in lane
# - Volume_Share_Pct: Carrier's percentage of lane volume
# - Weeks_Active: Number of weeks carrier was active
# - Avg_Weekly_Containers: Average containers per week
```

### 4. Analyze Weekly Trends

```python
from optimization import calculate_carrier_weekly_trends

# Get week-by-week container counts
weekly_trends = calculate_carrier_weekly_trends(data, n_weeks=5)

# Returns DataFrame with columns like:
# - Carrier, Lane, Week_39, Week_40, Week_41, Week_42, Week_43
# - Total_Containers, Avg_Weekly
```

### 5. Check Participation Patterns

```python
from optimization import get_carrier_lane_participation

# See which weeks each carrier participated
participation = get_carrier_lane_participation(data, n_weeks=5)

# Returns DataFrame showing:
# - Which weeks carrier was active (1) or inactive (0)
# - Participation_Rate_Pct: Percentage of weeks carrier was active
```

## Streamlit Integration

### Basic Usage

```python
import streamlit as st
from optimization import show_historic_volume_analysis

# Add to your dashboard
st.title("Historic Volume Analysis")
show_historic_volume_analysis(data, n_weeks=5)
```

### Full Integration Example

```python
import streamlit as st
from optimization import show_historic_volume_analysis

def show_analytics_tab(comprehensive_data):
    """Add historic volume as a sub-section in analytics."""

    st.header("📊 Analytics Dashboard")

    # Create tabs
    tab1, tab2, tab3 = st.tabs([
        "Current Analysis",
        "Historic Volume",
        "Forecasting"
    ])

    with tab1:
        # Your existing analytics
        show_current_analytics(comprehensive_data)

    with tab2:
        # Historic volume analysis
        show_historic_volume_analysis(comprehensive_data, n_weeks=5)

    with tab3:
        # Future forecasting
        show_forecasting(comprehensive_data)
```

## Display Components

The `show_historic_volume_analysis()` function provides 4 tabs:

### Tab 1: Market Share

- Summary metrics (carriers, lanes, total containers)
- Interactive filters (lane, minimum share %)
- Bar chart showing market share by carrier and lane
- Detailed data table with all metrics

### Tab 2: Weekly Trends

- Line chart showing volume changes over time
- Filter by carrier and/or lane
- Week-by-week data table

### Tab 3: Participation

- Participation rate distribution histogram
- Metrics for consistent vs sporadic carriers
- Detailed participation patterns table

### Tab 4: Detailed Data

- Download buttons for all datasets (CSV)
- Expandable raw data tables

## Data Requirements

### Required Columns

The input data must contain:

```python
required_columns = [
    "Dray SCAC(FL)",      # Carrier identifier
    "Container Count",     # Number of containers
    "Week Number",         # ISO week number (1-53)
    "Lane",               # Lane identifier
]
```

### Optional Columns

```python
optional_columns = [
    "Category",           # Product category (enhances grouping)
    "Discharged Port",    # Additional grouping dimension
    "Facility",           # Additional grouping dimension
]
```

## Example Output

### Market Share Example

```
Carrier        | Lane      | Volume_Share_Pct | Total_Containers | Weeks_Active
---------------|-----------|------------------|------------------|-------------
CARRIER_A      | USLAX-DC1 | 65.5%           | 1,310            | 5
CARRIER_B      | USLAX-DC1 | 34.5%           | 690              | 5
CARRIER_A      | USNYC-DC2 | 100.0%          | 2,500            | 4
CARRIER_C      | USNYC-DC2 | 0.0%            | 0                | 0
```

**Interpretation**:

- CARRIER_A handled 65.5% of USLAX-DC1 volume over last 5 weeks
- CARRIER_A was active all 5 weeks on USLAX-DC1
- CARRIER_A had 100% market share on USNYC-DC2 (only carrier serving it)

### Weekly Trends Example

```
Carrier   | Lane      | Week_39 | Week_40 | Week_41 | Week_42 | Week_43 | Total | Avg
----------|-----------|---------|---------|---------|---------|---------|-------|-----
CARRIER_A | USLAX-DC1 | 250     | 265     | 270     | 260     | 265     | 1,310 | 262
CARRIER_B | USLAX-DC1 | 130     | 140     | 145     | 135     | 140     | 690   | 138
```

**Interpretation**:

- CARRIER_A's volume is stable around 260-270 containers/week
- CARRIER_B's volume is stable around 135-145 containers/week
- Trend is relatively flat (no significant growth or decline)

## Advanced Usage

### Custom Reference Date

```python
from datetime import datetime
from optimization import calculate_carrier_volume_share

# Analyze as if today were October 1, 2025
reference_date = datetime(2025, 10, 1)

volume_share = calculate_carrier_volume_share(
    data,
    n_weeks=5,
    reference_date=reference_date
)

# This will exclude Week 40 and later (if Oct 1 falls in Week 40)
```

### Different Lookback Periods

```python
# Compare different time horizons
for n_weeks in [3, 5, 8]:
    share = calculate_carrier_volume_share(data, n_weeks=n_weeks)
    print(f"\nLast {n_weeks} weeks analysis:")
    print(share.head(10))
```

### Lane-Specific Analysis

```python
# Analyze specific lane only
lane_data = data[data['Lane'] == 'USLAX-DC1']
volume_share = calculate_carrier_volume_share(lane_data, n_weeks=5)
```

## Use Cases

### 1. Carrier Performance Review

**Question**: "Which carriers have been most reliable over the past 5 weeks?"

```python
participation = get_carrier_lane_participation(data, n_weeks=5)
reliable_carriers = participation[participation['Participation_Rate_Pct'] == 100]
print(f"Found {len(reliable_carriers)} carrier-lane pairs with 100% participation")
```

### 2. Market Concentration Analysis

**Question**: "Are we too dependent on a single carrier for any lane?"

```python
volume_share = calculate_carrier_volume_share(data, n_weeks=5)
concentrated_lanes = volume_share[volume_share['Volume_Share_Pct'] > 80]
print(f"High concentration lanes: {concentrated_lanes['Lane'].nunique()}")
```

### 3. Volume Trend Detection

**Question**: "Which carriers are gaining or losing market share?"

```python
trends = calculate_carrier_weekly_trends(data, n_weeks=5)

# Compare first week vs last week
week_cols = [col for col in trends.columns if col.startswith('Week_')]
first_week = week_cols[0]
last_week = week_cols[-1]

trends['Change'] = trends[last_week] - trends[first_week]
trends['Change_Pct'] = (trends['Change'] / trends[first_week] * 100).fillna(0)

growing = trends[trends['Change_Pct'] > 20]  # 20%+ growth
declining = trends[trends['Change_Pct'] < -20]  # 20%+ decline
```

### 4. New Carrier Identification

**Question**: "Which carriers just started serving lanes?"

```python
participation = get_carrier_lane_participation(data, n_weeks=5)

# Carriers active 1-2 weeks only (new entrants)
new_carriers = participation[
    (participation['Weeks_Participated'] >= 1) &
    (participation['Weeks_Participated'] <= 2)
]
```

## Technical Details

### ISO Week Numbering

The module uses ISO 8601 week numbering:

- Week 1 is the first week with a Thursday in the new year
- Weeks run Monday to Sunday
- Week numbers range from 1 to 52 or 53

```python
from datetime import datetime

# November 4, 2025 is Week 45
date = datetime(2025, 11, 4)
week_num = date.isocalendar().week  # Returns 45
```

### Performance Considerations

**For large datasets** (>100K rows):

```python
# Filter data before analysis to improve performance
recent_data = data[data['Week Number'] >= 35]  # Roughly last 3 months
volume_share = calculate_carrier_volume_share(recent_data, n_weeks=5)
```

**Memory optimization**:

- The module creates intermediate DataFrames for calculations
- For very large datasets, consider processing by lane or category

## Integration Checklist

- [ ] Ensure `Week Number` column exists in your data
- [ ] Verify week numbers are ISO week numbers (1-53)
- [ ] Confirm `Container Count` is numeric
- [ ] Test with current date to verify proper week exclusion
- [ ] Add to dashboard in appropriate section
- [ ] Configure default lookback period (3, 5, or 8 weeks)
- [ ] Consider adding export functionality for reports

## Files

```
optimization/
├── historic_volume.py              # Core calculation logic
├── historic_volume_display.py      # Streamlit UI components
└── __init__.py                     # Exports
```

## API Reference

### Core Functions

**`calculate_carrier_volume_share(data, n_weeks=5, ...)`**

- Returns: DataFrame with market share percentages
- Use: Main analysis function

**`calculate_carrier_weekly_trends(data, n_weeks=5, ...)`**

- Returns: DataFrame with week-by-week volumes
- Use: Trend analysis and visualization

**`get_carrier_lane_participation(data, n_weeks=5, ...)`**

- Returns: DataFrame with participation patterns
- Use: Consistency and reliability analysis

**`filter_historical_weeks(data, ...)`**

- Returns: DataFrame with only completed weeks
- Use: General purpose historical filtering

**`get_last_n_weeks(data, n_weeks=5, ...)`**

- Returns: DataFrame with last N completed weeks
- Use: Time-windowed analysis

### Display Functions

**`show_historic_volume_analysis(data, n_weeks=5, ...)`**

- Complete Streamlit interface with all visualizations
- Use: Primary dashboard integration

## Troubleshooting

**Issue**: "No historical data found"

- **Cause**: Current week equals or exceeds all week numbers in data
- **Solution**: Verify your data includes past weeks

**Issue**: "Week numbers don't match expected values"

- **Cause**: Week numbers not ISO standard
- **Solution**: Recalculate using `pd.to_datetime(date).dt.isocalendar().week`

**Issue**: "Market share doesn't add up to 100%"

- **Cause**: Normal - not all carriers serve all lanes
- **Solution**: Filter by specific lane to see 100% distribution

## Next Steps

1. **Test the module** with your actual data
2. **Integrate into dashboard** using example code
3. **Customize lookback period** based on business needs
4. **Add custom metrics** if needed (e.g., revenue share)
5. **Set up automated reports** using the export functions
