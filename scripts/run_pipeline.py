from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path
import sys
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from provider_mdm.pipeline import run_pipeline


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 64), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_source_files(raw_dir: Path) -> dict[Path, str]:
    if not raw_dir.exists():
        return {}
    return {path: _hash_file(path) for path in sorted(raw_dir.glob("*.csv"))}


def _sources_changed(previous: Mapping[Path, str], current: Mapping[Path, str]) -> bool:
    return dict(previous) != dict(current)


def _run_once(base_dir: Path, max_rows: int | None) -> dict[str, Path]:
    outputs = run_pipeline(base_dir, max_rows_per_source=max_rows)
    print("Pipeline completed successfully.")
    for name, file_path in outputs.items():
        print(f"{name}: {file_path}")
    return outputs


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
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep watching data/raw for CSV content changes and rerun the pipeline automatically.",
    )
    parser.add_argument(
        "--watch-interval",
        type=int,
        default=5,
        help="Seconds between file-change checks while --watch is enabled.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_rows = None if args.max_rows_per_source == 0 else args.max_rows_per_source
    base_dir = Path(args.base_dir)

    if not args.watch:
        _run_once(base_dir, max_rows)
        return

    raw_dir = base_dir / "data" / "raw"
    print(f"Watching {raw_dir} for source CSV changes. Press Ctrl+C to stop.")
    _run_once(base_dir, max_rows)
    last_snapshot = _snapshot_source_files(raw_dir)

    try:
        while True:
            time.sleep(max(1, args.watch_interval))
            current_snapshot = _snapshot_source_files(raw_dir)
            if not _sources_changed(last_snapshot, current_snapshot):
                continue
            print("Source CSV change detected. Rerunning pipeline...")
            _run_once(base_dir, max_rows)
            last_snapshot = _snapshot_source_files(raw_dir)
    except KeyboardInterrupt:
        print("Watch mode stopped.")


if __name__ == "__main__":
    main()
