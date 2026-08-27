# Healthcare Provider Master Data Management (MDM)

This project builds a master provider dataset from public healthcare provider CSV files.

## What This Pipeline Does

- Downloads raw provider CSV files from public web sources.
- Standardizes provider fields (NPI, address, phone, provider type).
- Validates NPI values and flags invalid NPIs.
- Performs de-duplication using exact NPI and fuzzy name/address matching.
- Infers parent-child hierarchy between hospitals and affiliated clinics.
- Produces data quality exception files and a weekly status report.

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

## Outputs

- data/processed/master_providers.csv
- data/processed/duplicates_merged.csv
- data/processed/data_quality_exceptions.csv
- data/processed/hierarchy_rollup.csv
- reports/weekly_status_report.md
