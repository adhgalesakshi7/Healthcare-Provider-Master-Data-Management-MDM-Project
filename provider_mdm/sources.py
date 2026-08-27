from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests


@dataclass(frozen=True)
class SourceConfig:
    name: str
    entity_type: str
    url: str


DEFAULT_SOURCES: tuple[SourceConfig, ...] = (
    SourceConfig(
        name="hospitals",
        entity_type="hospital",
        url="https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/providers/hospitals.csv",
    ),
    SourceConfig(
        name="primary_care_facilities",
        entity_type="clinic",
        url="https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/providers/primary_care_facilities.csv",
    ),
    SourceConfig(
        name="ambulatory_surgical_center",
        entity_type="clinic",
        url="https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/providers/ambulatory_surgical_center.csv",
    ),
)


def download_file(url: str, destination: Path, timeout: int = 60) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with destination.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)
    return destination


def fetch_sources(raw_dir: Path, sources: Iterable[SourceConfig]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for source in sources:
        file_path = raw_dir / f"{source.name}.csv"
        download_file(source.url, file_path)
        files[source.name] = file_path
    return files
