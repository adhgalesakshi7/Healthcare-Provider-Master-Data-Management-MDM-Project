from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from provider_mdm.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run healthcare provider MDM pipeline.")
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Project root where data/raw, data/processed, and reports folders are managed.",
    )
    parser.add_argument(
        "--max-rows-per-source",
        type=int,
        default=2500,
        help="Rows to ingest from each source. Use 0 for full dataset.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_rows = None if args.max_rows_per_source == 0 else args.max_rows_per_source
    outputs = run_pipeline(Path(args.base_dir), max_rows_per_source=max_rows)
    print("Pipeline completed successfully.")
    for name, file_path in outputs.items():
        print(f"{name}: {file_path}")


if __name__ == "__main__":
    main()
