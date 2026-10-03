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
        source_palette = ["#38bdf8", "#22c55e", "#f59e0b", "#fb7185", "#a78bfa"]
        source_segments: list[str] = []
        source_legend_items: list[str] = []
        if source_total:
            start = 0.0
            for idx, (source, count) in enumerate(source_counts.items()):
                share = (count / source_total) * 100
                end = start + share
                color = source_palette[idx % len(source_palette)]
                label = source.replace("_", " ").title()
                source_segments.append(f"{color} {start:.2f}% {end:.2f}%")
                source_legend_items.append(
                    f'<div class="legend-item"><span class="legend-swatch" style="background: {color}"></span><span>{label}</span><strong>{count:,}</strong></div>'
                )
                start = end
        source_donut_style = (
            f"background: conic-gradient({', '.join(source_segments)});"
            if source_segments
            else "background: conic-gradient(#334155 0 100%);"
        )
        source_legend_html = "\n".join(source_legend_items) or '<p class="empty">No source data available.</p>'

        specialty_counts = master.groupby("specialty").size().sort_values(ascending=False)
        specialty_max = int(specialty_counts.max()) if not specialty_counts.empty else 1
        refresh_seconds = 60

        source_rows = "\n".join(
                f'''
                    <div class="bar-row">
                        <span>{source.replace("_", " ").title()}</span>
                        <div class="bar-track"><div class="bar-fill" style="width: {max(6, round((count / source_max) * 100))}%"></div></div>
                        <span>{count:,}</span>
                    </div>'''
                for source, count in source_counts.items()
        ) or '<p class="empty">No source data available.</p>'

        specialty_rows = "\n".join(
                f'''
                    <div class="bar-row">
                        <span>{specialty}</span>
                        <div class="bar-track"><div class="bar-fill alt" style="width: {max(6, round((count / specialty_max) * 100))}%"></div></div>
                        <span>{count:,}</span>
                    </div>'''
                for specialty, count in specialty_counts.head(5).items()
        ) or '<p class="empty">No specialty data available.</p>'

        top_rollup = rollup.sort_values(by="affiliated_entity_count", ascending=False).head(5)
        rollup_rows = "\n".join(
                f"<li><span>{row.parent_npi}</span><strong>{int(row.affiliated_entity_count):,} affiliates</strong></li>"
                for row in top_rollup.itertuples(index=False)
        ) or '<li><span>No rollup data</span><strong>0 affiliates</strong></li>'

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
                            --bg: #07111f;
                            --panel: rgba(15, 23, 42, 0.82);
                            --panel-soft: rgba(15, 23, 42, 0.62);
                            --border: rgba(148, 163, 184, 0.18);
                            --text: #e2e8f0;
                            --muted: #94a3b8;
                            --accent: #38bdf8;
                            --accent-2: #22c55e;
                            --accent-3: #f59e0b;
                            --shadow: 0 24px 60px rgba(2, 6, 23, 0.48);
                        }}

                        * {{ box-sizing: border-box; }}
                        body {{
                            margin: 0;
                            min-height: 100vh;
                            color: var(--text);
                            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                            background:
                                radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 28%),
                                radial-gradient(circle at top right, rgba(34, 197, 94, 0.14), transparent 24%),
                                linear-gradient(135deg, #020617 0%, #0f172a 55%, #111827 100%);
                        }}

                        .shell {{ max-width: 1240px; margin: 0 auto; padding: 30px 20px 42px; }}
                        .hero {{ display: grid; grid-template-columns: 1.45fr 0.95fr; gap: 20px; margin-bottom: 20px; }}
                        .card {{
                            background: var(--panel);
                            border: 1px solid var(--border);
                            border-radius: 26px;
                            box-shadow: var(--shadow);
                            backdrop-filter: blur(16px);
                        }}
                        .hero-main {{ padding: 28px; position: relative; overflow: hidden; }}
                        .hero-main::after {{
                            content: "";
                            position: absolute;
                            inset: auto -12% -24% auto;
                            width: 260px;
                            height: 260px;
                            background: radial-gradient(circle, rgba(56, 189, 248, 0.24), transparent 68%);
                            pointer-events: none;
                        }}
                        .eyebrow {{
                            display: inline-flex; align-items: center; gap: 8px;
                            padding: 7px 12px; border-radius: 999px;
                            background: rgba(56, 189, 248, 0.12); color: #bae6fd;
                            font-size: 0.82rem; letter-spacing: 0.08em; text-transform: uppercase;
                        }}
                        h1 {{ margin: 14px 0 12px; font-size: clamp(2.2rem, 4vw, 4rem); line-height: 0.98; letter-spacing: -0.06em; }}
                        .lede {{ margin: 0; max-width: 74ch; color: var(--muted); font-size: 1rem; line-height: 1.72; }}
                        .hero-side {{ padding: 22px; display: grid; gap: 14px; }}
                        .mini {{ padding: 16px 18px; border-radius: 20px; background: var(--panel-soft); border: 1px solid rgba(148, 163, 184, 0.12); }}
                        .mini .label {{ color: var(--muted); font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 8px; }}
                        .mini .value {{ font-size: 1.42rem; font-weight: 800; }}
                        .grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin: 20px 0; }}
                        .metric {{ padding: 18px; min-height: 126px; position: relative; overflow: hidden; }}
                        .metric::before {{
                            content: ""; position: absolute; inset: auto -18px -18px auto; width: 88px; height: 88px;
                            border-radius: 50%; background: radial-gradient(circle, rgba(56, 189, 248, 0.15), transparent 70%);
                        }}
                        .metric .title {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 10px; }}
                        .metric .number {{ font-size: clamp(1.6rem, 3vw, 2.4rem); font-weight: 850; margin-bottom: 8px; }}
                        .metric .sub {{ color: var(--muted); font-size: 0.92rem; line-height: 1.55; }}
                        .content {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
                        .section {{ padding: 22px; }}
                        .section h2 {{ margin: 0 0 14px; font-size: 1.08rem; letter-spacing: -0.02em; }}
                        .report-list {{ display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }}
                        .report-list li {{ display: flex; justify-content: space-between; gap: 12px; padding: 12px 14px; border-radius: 14px; background: rgba(15, 23, 42, 0.64); border: 1px solid rgba(148, 163, 184, 0.1); }}
                        .report-list strong {{ font-variant-numeric: tabular-nums; }}
                        .tag {{ display: inline-flex; align-items: center; justify-content: center; padding: 4px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 700; background: rgba(34, 197, 94, 0.14); color: #86efac; }}
                        .tag.warn {{ background: rgba(245, 158, 11, 0.14); color: #fcd34d; }}
                        .bars {{ display: grid; gap: 12px; margin-top: 10px; }}
                        .bar-row {{ display: grid; grid-template-columns: 118px 1fr 88px; gap: 10px; align-items: center; }}
                        .bar-track {{ height: 12px; border-radius: 999px; background: rgba(148, 163, 184, 0.12); overflow: hidden; }}
                        .bar-fill {{ height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }}
                        .bar-fill.alt {{ background: linear-gradient(90deg, var(--accent-3), #fb7185); }}
                        .bar-row span:last-child {{ text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }}
                        .rank-list {{ display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }}
                        .rank-list li {{ display: flex; justify-content: space-between; gap: 12px; padding: 12px 14px; border-radius: 14px; background: rgba(15, 23, 42, 0.64); border: 1px solid rgba(148, 163, 184, 0.1); }}
                        .footer {{ margin-top: 18px; color: var(--muted); font-size: 0.92rem; line-height: 1.6; }}
                        .empty {{ color: var(--muted); margin: 0; padding: 12px 0 0; }}
                        .subgrid {{ display: grid; grid-template-columns: 1fr 0.9fr; gap: 20px; margin-top: 20px; }}
                        .chart-grid {{ display: grid; grid-template-columns: 1.12fr 0.88fr; gap: 20px; margin-top: 20px; }}
                        .section-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }}
                        .refresh-pill {{ display: inline-flex; align-items: center; gap: 8px; padding: 7px 12px; border-radius: 999px; background: rgba(148, 163, 184, 0.12); color: #dbeafe; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; }}
                        .donut-wrap {{ display: grid; grid-template-columns: 220px 1fr; gap: 18px; align-items: center; }}
                        .donut {{ width: 220px; aspect-ratio: 1; border-radius: 50%; padding: 18px; display: grid; place-items: center; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06); }}
                        .donut-hole {{ width: 100%; height: 100%; border-radius: 50%; display: grid; place-items: center; text-align: center; background: rgba(2, 6, 23, 0.9); border: 1px solid rgba(148, 163, 184, 0.14); }}
                        .donut-hole strong {{ display: block; font-size: 2rem; line-height: 1; letter-spacing: -0.05em; }}
                        .donut-hole span {{ display: block; margin-top: 6px; color: var(--muted); font-size: 0.8rem; letter-spacing: 0.12em; text-transform: uppercase; }}
                        .legend {{ display: grid; gap: 10px; }}
                        .legend-item {{ display: grid; grid-template-columns: 14px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 14px; background: rgba(15, 23, 42, 0.64); border: 1px solid rgba(148, 163, 184, 0.1); }}
                        .legend-swatch {{ width: 12px; height: 12px; border-radius: 999px; box-shadow: 0 0 0 3px rgba(255,255,255,0.03); }}
                        @media (max-width: 1100px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .hero, .content, .subgrid {{ grid-template-columns: 1fr; }} }}
                        @media (max-width: 720px) {{ .grid {{ grid-template-columns: 1fr; }} .bar-row {{ grid-template-columns: 90px 1fr 72px; }} .donut-wrap {{ grid-template-columns: 1fr; justify-items: center; }} .donut {{ width: 190px; }} }}
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
                                <div class="eyebrow">Fresh MDM Run</div>
                                <h1>Healthcare Provider Master Data Management</h1>
                                <p class="lede">
                                    This dashboard is generated by the pipeline from the latest provider ingest. It shows the current run summary,
                                    data mix, and hierarchy rollup so you can see the project output in a browser.
                                </p>
                            </section>

                            <aside class="card hero-side">
                                <div class="mini"><div class="label">Last Refresh</div><div class="value">{generated_at}</div></div>
                                <div class="mini"><div class="label">Open Exceptions</div><div class="value">{len(exceptions):,}</div></div>
                                <div class="mini"><div class="label">Top Issue</div><div class="value">{top_issue} ({top_issue_count:,})</div></div>
                                <div class="mini"><div class="label">Auto Refresh</div><div class="value">Every {refresh_seconds}s</div></div>
                            </aside>
                        </div>

                        <section class="grid">
                            <div class="card metric"><div class="title">Raw Records</div><div class="number">{len(ingested):,}</div><div class="sub">Rows ingested from the provider CSVs in this run.</div></div>
                            <div class="card metric"><div class="title">Master Records</div><div class="number">{len(master):,}</div><div class="sub">Records left after standardization and de-duplication.</div></div>
                            <div class="card metric"><div class="title">Duplicate Events</div><div class="number">{len(merge_log):,}</div><div class="sub">Merged groups identified by exact NPI or fuzzy matching.</div></div>
                            <div class="card metric"><div class="title">Merged Rows</div><div class="number">{int(merge_log["merged_record_count"].sum()) if not merge_log.empty else 0:,}</div><div class="sub">Rows absorbed into duplicate merge groups.</div></div>
                            <div class="card metric"><div class="title">Rollup Groups</div><div class="number">{len(rollup):,}</div><div class="sub">Parent-provider groups with one or more affiliated entities.</div></div>
                        </section>

                        <section class="content">
                            <div class="card section">
                                <h2>Report Summary</h2>
                                <ul class="report-list">
                                    <li><span>Raw records ingested</span><strong>{len(ingested):,}</strong></li>
                                    <li><span>Master records after de-duplication</span><strong>{len(master):,}</strong></li>
                                    <li><span>Duplicate merge events</span><strong>{len(merge_log):,}</strong></li>
                                    <li><span>Rows merged as duplicates</span><strong>{int(merge_log["merged_record_count"].sum()) if not merge_log.empty else 0:,}</strong></li>
                                    <li><span>Open data quality exceptions</span><strong>{len(exceptions):,}</strong></li>
                                </ul>
                            </div>

                            <div class="card section">
                                <h2>Top Rollup Groups</h2>
                                <ul class="rank-list">
                                    {rollup_rows}
                                </ul>
                                <div class="footer">Largest affiliated-provider groups by parent NPI in the latest run.</div>
                            </div>
                        </section>

                        <section class="chart-grid">
                            <div class="card section">
                                <div class="section-head">
                                    <h2>Source Distribution</h2>
                                    <span class="refresh-pill">Live snapshot</span>
                                </div>
                                <div class="donut-wrap">
                                    <div class="donut" style="{source_donut_style}">
                                        <div class="donut-hole">
                                            <div>
                                                <strong>{source_total:,}</strong>
                                                <span>rows</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="legend">
                                        {source_legend_html}
                                    </div>
                                </div>
                                <div class="footer">The donut chart summarizes the current raw CSV mix by source.</div>
                            </div>

                            <div class="card section">
                                <h2>Top Specialties</h2>
                                <div class="bars">{specialty_rows}</div>
                                <div class="footer">The largest specialty in this run is highlighted by the longest bar.</div>
                            </div>
                        </section>

                        <section class="subgrid">
                            <div class="card section">
                                <h2>Source Mix</h2>
                                <div class="bars">{source_rows}</div>
                            </div>

                            <div class="card section">
                                <h2>Data Quality</h2>
                                <ul class="report-list">
                                    <li><span>Total exceptions</span><strong>{len(exceptions):,}</strong></li>
                                    <li><span>Top issue</span><strong>{top_issue}</strong></li>
                                    <li><span>Top issue count</span><strong>{top_issue_count:,}</strong></li>
                                    <li><span>Refresh cadence</span><strong>{refresh_seconds}s</strong></li>
                                </ul>
                                <div class="footer">This card makes the page feel live and keeps the latest exception signal visible.</div>
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
