# components/data_loader.py

## Purpose
Handles file upload UI and raw Excel file loading. This is the first step in the data pipeline — it reads GVT, Rate, and Performance Excel files from the Streamlit file uploader and returns raw DataFrames.

## Key Functions

### `show_file_upload_section() -> tuple`
Renders the Streamlit file upload widgets for GVT, Rate, Performance, and Constraints files. Returns a tuple of `(gvt_file, rate_file, performance_file, constraints_file)` — each is either a Streamlit `UploadedFile` or `None`.

### `load_data_files(gvt_file, rate_file, performance_file) -> tuple`
Reads the uploaded Excel files into DataFrames. Returns `(GVTdata, Ratedata, Performancedata, has_performance)`. Uses `_load_excel_file()` for GVT/Performance and `_load_rate_file()` for Rate data.

### `_load_rate_file(file_bytes, file_name) -> DataFrame`
Loads a rate Excel file with auto-detection of format. Supports two formats:
1. **Standard rate sheet** — flat Excel with headers in row 0 (`SCAC`, `Port`, `FC`, `Lookup`, `Base Rate`, etc.)
2. **Master Rate Card** — multi-sheet workbook (e.g., `NA 3P Dray 2025-26 - Master Rate Card.xlsx`) where rate data lives in a sheet whose name contains "Master Sheet" and headers start at row 3 (rows 0-2 contain metadata)

Detection logic:
1. Try default load (header=0). If `Lookup` and `SCAC` columns exist, return immediately.
2. Scan sheet names for one containing "Master Sheet" (excluding "Original"). Read that sheet's first 10 rows to find the header row containing `Lookup` and `SCAC`.
3. Fallback: scan first 10 rows of the default sheet for the header.
4. If nothing matches, return the default load — `validate_and_process_rate_data()` will raise a clear error.

### `process_performance_data(Performancedata, has_performance) -> tuple`
Melts the wide-format performance file (columns like `WK27`, `WK28`, etc.) into long format with `Carrier`, `Week Number`, `Performance_Score` columns. Returns `(performance_clean, has_performance)`.

### `load_gvt_data(gvt_file) -> DataFrame | None`
Lower-level GVT loader used by the legacy `create_comprehensive_data` path. Selects specific columns (`select_cols`) and calculates `Container Count` from `Container Numbers`. Columns not in `select_cols` are dropped here.

**Important**: When adding new GVT columns to the pipeline (e.g., `Ocean ETA`), they must be added to `select_cols` in this function AND to the `agg_dict` in `data_processor.merge_all_data()`.

## Data Flow
```
Excel files → show_file_upload_section() → load_data_files() → raw DataFrames
                                                                    ↓
                                                          data_processor.py
```

## Logging
All `st.write()` and `print()` debug statements replaced with `logging.getLogger(__name__).debug()`. Console is clean by default.

## Dependencies
- `streamlit` (file upload widgets)
- `pandas` / `openpyxl` (Excel reading)
