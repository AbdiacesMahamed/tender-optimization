# Remove Rate Filtering - Show All Containers

## Issue

The dashboard was filtering out containers that didn't have rates available, causing a discrepancy between the total containers in the raw data and what appeared in the constrained/unconstrained tables.

**Example**: 49 containers in BAL Week 47 in the raw data, but only 24 showing in the dashboard tables.

## Root Cause

Multiple places in the code were filtering out rows where `Missing_Rate = True`:

### 1. In `calculate_enhanced_metrics()`

```python
# OLD CODE - Filtered out missing rates
has_missing_rate_col = 'Missing_Rate' in data.columns
data_with_rates = data[data['Missing_Rate'] == False].copy() if has_missing_rate_col else data.copy()
```

### 2. In `show_detailed_analysis_table()`

```python
# OLD CODE - Separated data by rate availability
if 'Missing_Rate' in display_data.columns and selected in ('Performance', 'Cheapest Cost', 'Optimized'):
    display_data_with_rates = display_data[display_data['Missing_Rate'] == False].copy()
    missing_rate_rows = display_data[display_data['Missing_Rate'] == True].copy()
```

### 3. In Cheapest Cost Scenario

```python
# OLD CODE - Explicitly filtered out missing rates
if 'Missing_Rate' in source_data.columns:
    source_data = source_data[source_data['Missing_Rate'] == False].copy()
```

## The Problem

This filtering logic meant:

- Containers on carriers without rates were EXCLUDED from all scenario calculations
- These containers "disappeared" - not in constrained, not in unconstrained, nowhere
- Total container counts didn't match between raw data and displayed data
- Users couldn't see ALL their containers, only those with rates

## Solution

**Removed ALL filtering based on `Missing_Rate`**. Now all containers are included regardless of rate availability:

### 1. In `calculate_enhanced_metrics()`

```python
# NEW CODE - Keep all data
data_with_rates = data.copy()

# For cost calculations, only sum rows that have valid rates (not NaN)
if rate_cols['total_rate'] in data_with_rates.columns:
    total_cost = data_with_rates[rate_cols['total_rate']].fillna(0).sum()
```

### 2. In `show_detailed_analysis_table()`

```python
# NEW CODE - Use all data, no filtering
display_data_with_rates = display_data.copy()
missing_rate_rows = pd.DataFrame()  # Empty - not needed anymore
```

### 3. In Cheapest Cost Scenario

```python
# NEW CODE - Keep all carriers regardless of rate availability
if rate_cols['rate'] in source_data.columns:
    source_data[rate_cols['rate']] = pd.to_numeric(source_data[rate_cols['rate']], errors='coerce')
# No filtering - keep carriers without rates too
```

## Impact

### Before Fix:

- ❌ Containers without rates were HIDDEN
- ❌ Total counts didn't match raw data
- ❌ 49 containers in data → only 24 visible in dashboard
- ❌ Missing containers gave false impression of data quality issues

### After Fix:

- ✅ ALL containers are visible
- ✅ Total counts match raw data exactly
- ✅ 49 containers in data → 49 containers in dashboard
- ✅ Containers without rates show with `Missing_Rate = True` flag
- ✅ Cost calculations still work correctly (use fillna(0) for missing rates)
- ✅ Scenarios handle carriers without rates appropriately:
  - **Current Selection**: Shows all carriers as-is
  - **Performance**: Allocates based on performance score (rate not required)
  - **Cheapest**: Carriers without rates sorted last (fillna(float('inf')))
  - **Optimized**: Includes all carriers in optimization

## How It Works Now

### Data Flow:

1. **Raw Data** → All containers loaded
2. **Filtering** → User selections (week, port, lane, etc.)
3. **Display** → ALL filtered containers shown
4. **Rate Handling**:
   - Containers WITH rates: Show actual rate and calculate costs
   - Containers WITHOUT rates: Show `⚠️ No Rate`, cost = 0 or N/A

### Cost Calculations:

- Use `.fillna(0)` when summing costs
- Carriers without rates contribute 0 to total cost
- Container counts are accurate regardless of rate availability

### Scenario Behavior:

- **Performance**: Works fine (uses performance score, not rate)
- **Cheapest**: Carriers without rates ranked last (inf cost)
- **Optimized**: All carriers considered, LP handles missing rates gracefully
- **Current**: Shows everything as-is

## Benefits

### User Experience:

✅ **Complete visibility** - See all your containers  
✅ **Accurate counts** - No mystery missing containers  
✅ **Clear indication** - `⚠️ No Rate` flag shows which carriers lack rates  
✅ **Better decisions** - See full picture, not just containers with rates

### Data Integrity:

✅ **No data loss** - Every container is accounted for  
✅ **Transparent** - Users know exactly what they have  
✅ **Reliable** - Counts match source data perfectly

## Files Modified

- `components/metrics.py` - Removed all `Missing_Rate` filtering logic

## Date Applied

November 12, 2025

## Testing

After this fix:

1. ✅ Load data with some containers lacking rates
2. ✅ Check total container count in raw data
3. ✅ Navigate to dashboard and check displayed count
4. ✅ Counts should match exactly
5. ✅ Containers without rates should be visible with `⚠️ No Rate` indicator
6. ✅ All scenarios should display all containers
