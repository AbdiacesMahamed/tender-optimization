# components/utils.py

## Purpose
Shared utility functions used across all component modules. Consolidates common operations to avoid duplication.

## Function Groups

### Rate Column Utilities
- `get_rate_columns() -> dict` — Returns `{'rate': 'Base Rate', 'total_rate': 'Total Rate'}` or CPC equivalents based on `st.session_state.rate_type`

### Container Utilities
- `count_containers(container_str) -> int` — Count containers in comma-separated string
- `parse_container_ids(container_str) -> list` — Split into individual IDs
- `join_container_ids(container_list) -> str` — Join list back to comma-separated string
- `concat_and_dedupe_containers(values) -> str` — Concatenate multiple container strings, deduplicate

### Data Grouping
- `get_grouping_columns(data, base_cols) -> list` — Returns available grouping columns, auto-adding Category/SSL/Vessel/Terminal if present

### Formatting
- `safe_numeric(value) -> float` — Convert any value (including formatted strings like `$1,234`) to float
- `format_currency(value) -> str` — Format as `$1,234.56` or `N/A`
- `format_percentage(value) -> str` — Format as `50.0%` or `N/A`
- `format_number(value, decimals) -> str` — Format with thousands separators

### DataFrame Utilities
- `filter_excluded_carrier_facility_rows(df, exclusions_dict, carrier_col) -> DataFrame` — Remove rows where a carrier is excluded from a specific facility
- `normalize_facility_code(facility_str) -> str` — Normalize to first 4 chars uppercase
