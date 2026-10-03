from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .processor import (
    build_exceptions,
    build_parent_hierarchy,
    build_rollup,
    deduplicate,
    finalize_columns,
    standardize_source,
)
from .sources import DEFAULT_SOURCES, fetch_sources


def _load_raw_sources(raw_files: dict[str, Path], max_rows_per_source: int | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    source_meta = {s.name: s for s in DEFAULT_SOURCES}
    for source_name, file_path in raw_files.items():
        source = source_meta[source_name]
        frame = pd.read_csv(file_path, dtype=str, nrows=max_rows_per_source).fillna("")
        frame = standardize_source(frame, source_name=source.name, entity_type=source.entity_type)
        frames.append(frame)
    if not frames:
        raise ValueError("No source data loaded.")
    return pd.concat(frames, ignore_index=True)


def _build_status_report(
    ingested: pd.DataFrame,
    deduped: pd.DataFrame,
    merge_log: pd.DataFrame,
    exceptions: pd.DataFrame,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_ingested = len(ingested)
    total_master = len(deduped)
    duplicate_events = len(merge_log)
    merged_rows = int(merge_log["merged_record_count"].sum()) if not merge_log.empty else 0
    total_exceptions = len(exceptions)

    lines = [
        "# Weekly Provider MDM Status Report",
        "",
        f"Generated: {now}",
        "",
        "## Summary",
        f"- Raw records ingested: {total_ingested}",
        f"- Master records after de-duplication: {total_master}",
        f"- Duplicate merge events: {duplicate_events}",
        f"- Rows merged as duplicates: {merged_rows}",
        f"- Data quality exceptions open: {total_exceptions}",
        "",
        "## Exceptions By Type",
    ]

    if exceptions.empty:
        lines.append("- No exceptions detected.")
    else:
        counts = exceptions.groupby("issue_type").size().sort_values(ascending=False)
        for issue_type, count in counts.items():
            lines.append(f"- {issue_type}: {count}")

    lines.extend(
        [
            "",
            "## Notes",
            "- Inputs were downloaded from public healthcare provider CSV sources.",
            "- Parent-child hierarchy was inferred using city/state and organization similarity.",
        ]
    )
    return "\n".join(lines)


def run_pipeline(
    base_dir: Path,
    max_rows_per_source: int | None = 2500,
) -> dict[str, Path]:
    base_dir = Path(base_dir)
    data_raw = base_dir / "data" / "raw"
    data_processed = base_dir / "data" / "processed"
    reports_dir = base_dir / "reports"
    data_processed.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    raw_files = fetch_sources(data_raw, DEFAULT_SOURCES)
    ingested = _load_raw_sources(raw_files, max_rows_per_source=max_rows_per_source)
    deduped, merge_log = deduplicate(ingested)
    hierarchy = build_parent_hierarchy(deduped)
    exceptions = build_exceptions(hierarchy)
    rollup = build_rollup(hierarchy)
    master = finalize_columns(hierarchy)

    out_master = data_processed / "master_providers.csv"
    out_merge = data_processed / "duplicates_merged.csv"
    out_exceptions = data_processed / "data_quality_exceptions.csv"
    out_rollup = data_processed / "hierarchy_rollup.csv"
    out_summary = reports_dir / "weekly_status_report.md"

    master.to_csv(out_master, index=False)
    merge_log.to_csv(out_merge, index=False)
    exceptions.to_csv(out_exceptions, index=False)
    rollup.to_csv(out_rollup, index=False)
    out_summary.write_text(
        _build_status_report(ingested, master, merge_log, exceptions),
        encoding="utf-8",
    )

    return {
        "master": out_master,
        "duplicates": out_merge,
        "exceptions": out_exceptions,
        "rollup": out_rollup,
        "status_report": out_summary,
    }
