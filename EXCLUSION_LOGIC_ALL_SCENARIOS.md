# Exclusion Logic Applied Across All Scenarios

## Summary

This update extends carrier+facility exclusion logic to work consistently across ALL optimization scenarios, not just during constraint processing.

## Problem

Previously, when a constraint like "Excluding Facility=HGR6" was set for carrier XPDR:

1. The exclusion was applied during constraint processing (clearing existing assignments)
2. BUT scenarios (Performance, Cheapest, Optimized) would re-assign the excluded carrier because they didn't know about the exclusion rules

## Solution

The exclusion rules are now collected in `constraints_processor.py` as a dictionary (`carrier_facility_exclusions`) and passed through the entire data flow:

### Data Flow

```
constraints_processor.apply_constraints_to_data()
    ↓ returns carrier_facility_exclusions dict
dashboard.py
    ↓ passes to calculate_enhanced_metrics() and show_detailed_analysis_table()
metrics.py
    ↓ filters out excluded carrier+facility rows before scenario calculations
```

### Files Modified

#### 1. `dashboard.py`

- Added `carrier_facility_exclusions = {}` initialization before constraint processing
- Updated `calculate_enhanced_metrics()` call to pass `carrier_facility_exclusions`
- Updated `show_detailed_analysis_table()` call to pass `carrier_facility_exclusions`

#### 2. `components/metrics.py`

- Updated `calculate_enhanced_metrics()` signature to accept `carrier_facility_exclusions` parameter
- Added helper function `filter_excluded_carrier_facility_rows()` to remove excluded carrier+facility combinations
- Applied filtering before:
  - Performance scenario calculation (line ~304)
  - Cheapest scenario calculation (line ~325)
  - Optimized scenario calculation (line ~384)
- Updated `show_detailed_analysis_table()` signature to accept `carrier_facility_exclusions` parameter
- Added the same helper function inside the display function
- Applied filtering before:
  - Performance scenario display (line ~956)
  - Optimized scenario display (line ~893)
  - Cheapest Cost scenario display (line ~1260)

### How the Filtering Works

```python
def filter_excluded_carrier_facility_rows(df, exclusions_dict, carrier_col='Dray SCAC(FL)'):
    """Filter out rows where a carrier is excluded from a specific facility.

    For scenario calculations, we want to prevent certain carriers from being selected
    at certain facilities. This function removes those rows so the scenario algorithms
    don't consider them as valid carrier options.
    """
    if not exclusions_dict or df.empty:
        return df

    keep_mask = pd.Series([True] * len(df), index=df.index)

    for carrier, excluded_facilities in exclusions_dict.items():
        for excluded_fc in excluded_facilities:
            carrier_match = df[carrier_col] == carrier
            # Normalize facility - compare first 4 chars
            facility_match = df['Facility'].str[:4].str.upper() == excluded_fc.upper()[:4]
            keep_mask &= ~(carrier_match & facility_match)

    return df[keep_mask].copy()
```

### Example

With constraint "Carrier=XPDR, Excluded FC=HGR6":

- `carrier_facility_exclusions = {'XPDR': {'HGR6'}}`
- When calculating Performance/Cheapest/Optimized scenarios:
  - Any row where carrier=XPDR AND facility starts with HGR6 is filtered OUT
  - XPDR can still be selected for other facilities (BWI4, TEB4, etc.)
  - Other carriers can still be selected for HGR6
  - Result: XPDR will never be assigned to HGR6 in any scenario

## Testing

To verify the fix:

1. Load data with a constraint that has "Excluded FC" set
2. Check the container at that facility (e.g., TGBU8890143 at HGR6)
3. In ALL scenarios (Current Selection, Performance, Cheapest, Optimized):
   - The excluded carrier should NOT be assigned to containers at the excluded facility
   - A different carrier should be assigned instead (or reallocated if it was originally assigned)
