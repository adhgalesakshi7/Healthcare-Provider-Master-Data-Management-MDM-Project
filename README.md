# Healthcare Provider Master Data Management (MDM)

This project builds a master provider dataset from public healthcare provider CSV files.

## Current Data Snapshot

The checked-in inputs and generated outputs currently show:

- Raw records ingested: 55,673
- Master records after de-duplication: 51,659
- Duplicate merge events: 3,115
- Rows merged as duplicates: 7,129
- Data quality exceptions open: 12
- Parent-child rollup groups: 4,587

### Source Mix

- Primary care facilities: 36,061
- Hospitals: 9,820
- Ambulatory surgical centers: 5,778

### Output Mix

- Primary Care: 22,233
- Clinic: 13,828
- Hospital: 9,820
- Ambulatory Surgical Center: 5,778

## What This Pipeline Does

- Downloads raw provider CSV files from public web sources.
- Standardizes provider fields (NPI, address, phone, provider type).
- Validates NPI values and flags invalid NPIs.
- Performs de-duplication using exact NPI and fuzzy name/address matching.
- Infers parent-child hierarchy between hospitals and affiliated clinics.
- Produces data quality exception files and a weekly status report.

## Evidence In Repo

- `data/raw/` contains the raw provider CSVs used by the pipeline.
- `data/processed/` contains the deduplicated master data, merge log, exception log, and hierarchy rollup.
- `reports/weekly_status_report.md` summarizes the latest run with the same counts shown above.

## Data Sources

- hospitals.csv (Synthea providers)
- primary_care_facilities.csv (Synthea providers)
- ambulatory_surgical_center.csv (Synthea providers)

## Run

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the pipeline with a default sample size (2500 rows per source):

```bash
python scripts/run_pipeline.py
```

3. Run full ingest (all rows from each source):

```bash
python scripts/run_pipeline.py --max-rows-per-source 0
```

4. Keep the pipeline running and rerun it when `data/raw/*.csv` changes:

```bash
python scripts/run_pipeline.py --watch
```

## Outputs

- data/processed/master_providers.csv
- data/processed/duplicates_merged.csv
- data/processed/data_quality_exceptions.csv
- data/processed/hierarchy_rollup.csv
- reports/weekly_status_report.md
