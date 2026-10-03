from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

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
    source_meta = {source.name: source for source in DEFAULT_SOURCES}
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


def _build_dashboard_html(
    generated_at: str,
    ingested: pd.DataFrame,
    master: pd.DataFrame,
    merge_log: pd.DataFrame,
    exceptions: pd.DataFrame,
    rollup: pd.DataFrame,
) -> str:
    issue_counts = exceptions.groupby("issue_type").size().sort_values(ascending=False)
    top_issue = issue_counts.index[0] if not issue_counts.empty else "none"
    top_issue_count = int(issue_counts.iloc[0]) if not issue_counts.empty else 0

    source_counts = ingested.groupby("source_name").size().sort_values(ascending=False)
    source_max = int(source_counts.max()) if not source_counts.empty else 1
    source_total = int(source_counts.sum()) if not source_counts.empty else 0

    specialty_counts = master.groupby("specialty").size().sort_values(ascending=False)
    specialty_max = int(specialty_counts.max()) if not specialty_counts.empty else 1
    refresh_seconds = 60
    merged_rows = int(merge_log["merged_record_count"].sum()) if not merge_log.empty else 0

    source_rows = "\n".join(
        f"<tr><td>{source.replace('_', ' ').title()}</td><td>{count:,}</td><td><div class='bar-track'><div class='bar-fill' style='width: {max(6, round((count / source_max) * 100))}%' ></div></div></td></tr>"
        for source, count in source_counts.items()
    ) or '<tr><td colspan="3">No source data available.</td></tr>'

    specialty_rows = "\n".join(
        f"<tr><td>{specialty}</td><td>{count:,}</td><td><div class='bar-track'><div class='bar-fill' style='width: {max(6, round((count / specialty_max) * 100))}%' ></div></div></td></tr>"
        for specialty, count in specialty_counts.head(5).items()
    ) or '<tr><td colspan="3">No specialty data available.</td></tr>'

    top_rollup = rollup.sort_values(by="affiliated_entity_count", ascending=False).head(5)
    rollup_rows = "\n".join(
        f"<li><span>{row.parent_npi}</span><strong>{int(row.affiliated_entity_count):,} affiliates</strong></li>"
        for row in top_rollup.itertuples(index=False)
    ) or '<li><span>No rollup data</span><strong>0 affiliates</strong></li>'

    issue_rows = "\n".join(
        f"<tr><td>{issue}</td><td>{count:,}</td></tr>"
        for issue, count in issue_counts.items()
    ) or '<tr><td>No exceptions</td><td>0</td></tr>'

    return dedent(
        f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>MDM Run Dashboard</title>
            <style>
                :root {{
                    --bg: #f7f7f5;
                    --panel: #ffffff;
                    --panel-soft: #fbfbfa;
                    --border: #d9d9d4;
                    --text: #1f2937;
                    --muted: #6b7280;
                    --shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
                }}

                * {{ box-sizing: border-box; }}
                body {{
                    margin: 0;
                    min-height: 100vh;
                    color: var(--text);
                    font-family: Segoe UI, Arial, sans-serif;
                    background: var(--bg);
                }}

                .shell {{ max-width: 1160px; margin: 0 auto; padding: 24px 18px 36px; }}
                .hero {{ display: grid; grid-template-columns: 1.45fr 0.85fr; gap: 16px; margin-bottom: 16px; }}
                .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); }}
                .hero-main {{ padding: 22px; }}
                .eyebrow {{ display: inline-flex; align-items: center; gap: 8px; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
                h1 {{ margin: 8px 0 10px; font-size: 2rem; line-height: 1.15; font-weight: 700; }}
                .lede {{ margin: 0; max-width: 74ch; color: var(--muted); font-size: 0.96rem; line-height: 1.6; }}
                .hero-side {{ padding: 16px; display: grid; gap: 10px; }}
                .mini {{ padding: 12px 14px; border-radius: 10px; background: var(--panel-soft); border: 1px solid var(--border); }}
                .mini .label {{ color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; }}
                .mini .value {{ font-size: 1.02rem; font-weight: 600; }}
                .grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }}
                .metric {{ padding: 14px; min-height: 106px; }}
                .metric .title {{ color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }}
                .metric .number {{ font-size: 1.55rem; font-weight: 700; margin-bottom: 6px; }}
                .metric .sub {{ color: var(--muted); font-size: 0.88rem; line-height: 1.45; }}
                .content, .subgrid, .chart-grid {{ display: grid; gap: 14px; }}
                .content {{ grid-template-columns: 1fr 1fr; }}
                .subgrid {{ grid-template-columns: 1fr 0.9fr; margin-top: 14px; }}
                .chart-grid {{ grid-template-columns: 1.08fr 0.92fr; margin-top: 14px; }}
                .section {{ padding: 16px; }}
                .section h2 {{ margin: 0 0 10px; font-size: 1rem; font-weight: 600; }}
                .report-list, .rank-list {{ display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }}
                .report-list li, .rank-list li {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 12px; border-radius: 8px; background: var(--panel-soft); border: 1px solid var(--border); }}
                .report-list strong {{ font-variant-numeric: tabular-nums; }}
                .bars {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
                .bars td {{ padding: 8px 6px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
                .bars td:first-child {{ width: 44%; }}
                .bars td:nth-child(2) {{ width: 14%; text-align: right; font-variant-numeric: tabular-nums; }}
                .bars td:nth-child(3) {{ width: 42%; }}
                .bar-track {{ height: 8px; border-radius: 999px; background: #e5e7eb; overflow: hidden; }}
                .bar-fill {{ height: 100%; border-radius: inherit; background: #9ca3af; }}
                .footer {{ margin-top: 12px; color: var(--muted); font-size: 0.88rem; line-height: 1.5; }}
                .source-note {{ color: var(--muted); font-size: 0.88rem; margin: 8px 0 0; }}
                .refresh-pill {{ display: inline-flex; align-items: center; gap: 8px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 0.74rem; }}
                @media (max-width: 1100px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .hero, .content, .subgrid, .chart-grid {{ grid-template-columns: 1fr; }} }}
                @media (max-width: 720px) {{ .grid {{ grid-template-columns: 1fr; }} .bars td:first-child {{ width: 46%; }} .bars td:nth-child(2) {{ width: 18%; }} .bars td:nth-child(3) {{ width: 36%; }} }}
            </style>
            <meta http-equiv="refresh" content="{refresh_seconds}">
        </head>
        <body>
            <script>
                setTimeout(() => window.location.reload(), {refresh_seconds * 1000});
            </script>
            <div class="shell">
                <div class="hero">
                    <section class="card hero-main">
                        <div class="eyebrow">MDM pipeline output</div>
                        <h1>Provider master data run</h1>
                        <p class="lede">Latest pipeline output from the provider CSVs. The page updates on a fixed interval and mirrors the processed files on disk.</p>
                    </section>

                    <aside class="card hero-side">
                        <div class="mini"><div class="label">Last refresh</div><div class="value">{generated_at}</div></div>
                        <div class="mini"><div class="label">Open exceptions</div><div class="value">{len(exceptions):,}</div></div>
                        <div class="mini"><div class="label">Top issue</div><div class="value">{top_issue} ({top_issue_count:,})</div></div>
                        <div class="mini"><div class="label">Refresh interval</div><div class="value">{refresh_seconds} seconds</div></div>
                    </aside>
                </div>

                <section class="grid">
                    <div class="card metric"><div class="title">Raw records</div><div class="number">{len(ingested):,}</div><div class="sub">Rows ingested from the provider CSVs.</div></div>
                    <div class="card metric"><div class="title">Master records</div><div class="number">{len(master):,}</div><div class="sub">Rows left after standardization and de-duplication.</div></div>
                    <div class="card metric"><div class="title">Duplicate events</div><div class="number">{len(merge_log):,}</div><div class="sub">Merged groups from exact and fuzzy matching.</div></div>
                    <div class="card metric"><div class="title">Merged rows</div><div class="number">{merged_rows:,}</div><div class="sub">Rows absorbed into duplicate groups.</div></div>
                    <div class="card metric"><div class="title">Rollup groups</div><div class="number">{len(rollup):,}</div><div class="sub">Parent-provider groups with affiliated entities.</div></div>
                </section>

                <section class="content">
                    <div class="card section">
                        <h2>Summary</h2>
                        <ul class="report-list">
                            <li><span>Raw records ingested</span><strong>{len(ingested):,}</strong></li>
                            <li><span>Master records after de-duplication</span><strong>{len(master):,}</strong></li>
                            <li><span>Duplicate merge events</span><strong>{len(merge_log):,}</strong></li>
                            <li><span>Rows merged as duplicates</span><strong>{merged_rows:,}</strong></li>
                            <li><span>Open data quality exceptions</span><strong>{len(exceptions):,}</strong></li>
                        </ul>
                    </div>

                    <div class="card section">
                        <h2>Top rollup groups</h2>
                        <ul class="rank-list">{rollup_rows}</ul>
                        <div class="footer">Largest affiliated-provider groups by parent NPI.</div>
                    </div>
                </section>

                <section class="chart-grid">
                    <div class="card section">
                        <div class="section-head">
                            <h2>Source mix</h2>
                            <span class="refresh-pill">Live snapshot</span>
                        </div>
                        <table class="bars">
                            <tr><td>Source</td><td>Count</td><td>Share</td></tr>
                            {source_rows}
                        </table>
                        <div class="source-note">{source_total:,} total rows across the three source CSVs.</div>
                    </div>

                    <div class="card section">
                        <h2>Top specialties</h2>
                        <table class="bars">
                            <tr><td>Specialty</td><td>Count</td><td>Share</td></tr>
                            {specialty_rows}
                        </table>
                        <div class="footer">Specialty distribution from the latest master file.</div>
                    </div>
                </section>

                <section class="subgrid">
                    <div class="card section">
                        <h2>Issue types</h2>
                        <table class="bars">
                            <tr><td>Issue</td><td>Count</td></tr>
                            {issue_rows}
                        </table>
                    </div>

                    <div class="card section">
                        <h2>Run notes</h2>
                        <ul class="report-list">
                            <li><span>Total exceptions</span><strong>{len(exceptions):,}</strong></li>
                            <li><span>Top issue</span><strong>{top_issue}</strong></li>
                            <li><span>Top issue count</span><strong>{top_issue_count:,}</strong></li>
                            <li><span>Refresh cadence</span><strong>{refresh_seconds}s</strong></li>
                        </ul>
                        <div class="footer">The dashboard refreshes on a timer and stays aligned to the generated CSV outputs.</div>
                    </div>
                </section>
            </div>
        </body>
        </html>
        """
    ).strip()


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
    out_dashboard = reports_dir / "dashboard.html"

    master.to_csv(out_master, index=False)
    merge_log.to_csv(out_merge, index=False)
    exceptions.to_csv(out_exceptions, index=False)
    rollup.to_csv(out_rollup, index=False)
    out_dashboard.write_text(
        _build_dashboard_html(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            ingested,
            master,
            merge_log,
            exceptions,
            rollup,
        ),
        encoding="utf-8",
    )
    out_summary.write_text(
        _build_status_report(ingested, master, merge_log, exceptions),
        encoding="utf-8",
    )

    return {
        "master": out_master,
        "duplicates": out_merge,
        "exceptions": out_exceptions,
        "rollup": out_rollup,
        "dashboard": out_dashboard,
        "status_report": out_summary,
    }
