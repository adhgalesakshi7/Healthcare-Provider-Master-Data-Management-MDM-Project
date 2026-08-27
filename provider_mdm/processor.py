from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import pandas as pd


REQUIRED_OUTPUT_COLUMNS = [
    "record_id",
    "source_name",
    "entity_type",
    "npi",
    "npi_valid",
    "organization",
    "street",
    "city",
    "state",
    "zip",
    "phone",
    "provider_type_code",
    "specialty",
    "parent_npi",
]


def is_valid_npi(npi: str) -> bool:
    npi = re.sub(r"\D", "", str(npi))
    if len(npi) != 10:
        return False
    digits = [int(d) for d in "80840" + npi[:-1]]
    total = 0
    for i, value in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = value * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += value
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(npi[-1])


def normalize_zip(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5] if digits else ""


def normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def infer_specialty(entity_type: str, provider_type_code: str, source_name: str) -> str:
    code = str(provider_type_code or "").strip()
    if source_name == "hospitals":
        return "Hospital"
    if source_name == "ambulatory_surgical_center":
        return "Ambulatory Surgical Center"
    if code.startswith("12-"):
        return "Primary Care"
    if entity_type == "clinic":
        return "Clinic"
    return "General Healthcare"


def standardize_source(df: pd.DataFrame, source_name: str, entity_type: str) -> pd.DataFrame:
    rename_map = {
        "name": "organization",
        "address": "street",
    }
    frame = df.rename(columns=rename_map).copy()
    for col in ["npi", "organization", "street", "city", "state", "zip", "phone", "provider_type_code"]:
        if col not in frame.columns:
            frame[col] = ""
        frame[col] = frame[col].fillna("").astype(str).str.strip()

    frame["source_name"] = source_name
    frame["entity_type"] = entity_type
    frame["zip"] = frame["zip"].apply(normalize_zip)
    frame["phone"] = frame["phone"].apply(normalize_phone)
    frame["npi"] = frame["npi"].str.replace(r"\D", "", regex=True)
    frame["npi_valid"] = frame["npi"].apply(is_valid_npi)
    frame["specialty"] = frame.apply(
        lambda row: infer_specialty(entity_type, row.get("provider_type_code", ""), source_name),
        axis=1,
    )
    frame["parent_npi"] = ""
    return frame


def _completeness_score(row: pd.Series) -> int:
    cols = ["npi", "organization", "street", "city", "state", "zip", "phone", "specialty"]
    return sum(bool(str(row.get(c, "")).strip()) for c in cols)


def _merge_rows(group: pd.DataFrame) -> pd.Series:
    ranked = group.copy()
    ranked["_score"] = ranked.apply(_completeness_score, axis=1)
    ranked = ranked.sort_values(by="_score", ascending=False)
    merged = ranked.iloc[0].copy()
    for col in ranked.columns:
        if col.startswith("_"):
            continue
        if str(merged.get(col, "")).strip():
            continue
        candidates = ranked[col].astype(str).str.strip()
        non_empty = candidates[candidates.astype(bool)]
        if not non_empty.empty:
            merged[col] = non_empty.iloc[0]
    return merged.drop(labels=[c for c in merged.index if c.startswith("_")], errors="ignore")


def _name_address_similarity(left: pd.Series, right: pd.Series) -> float:
    left_key = f"{left.get('organization','')}|{left.get('street','')}".lower().strip()
    right_key = f"{right.get('organization','')}|{right.get('street','')}".lower().strip()
    return SequenceMatcher(None, left_key, right_key).ratio()


def deduplicate(df: pd.DataFrame, fuzzy_threshold: float = 0.93) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = df.copy().reset_index(drop=True)
    frame["_row_id"] = frame.index
    merged_rows: list[pd.Series] = []
    merge_log: list[dict[str, Any]] = []

    with_npi = frame[frame["npi_valid"] & frame["npi"].astype(bool)]
    for npi, group in with_npi.groupby("npi", dropna=False):
        if len(group) > 1:
            merged = _merge_rows(group)
            merged_rows.append(merged)
            merge_log.append(
                {
                    "merge_reason": "same_npi",
                    "master_npi": npi,
                    "merged_record_count": len(group),
                    "source_row_ids": ",".join(group["_row_id"].astype(str).tolist()),
                }
            )
        else:
            merged_rows.append(group.iloc[0])

    consumed_ids = set(with_npi["_row_id"].tolist())
    without_valid_npi = frame[~frame["_row_id"].isin(consumed_ids)].copy()
    without_valid_npi["_block_key"] = (
        without_valid_npi["city"].str.lower()
        + "|"
        + without_valid_npi["state"].str.lower()
        + "|"
        + without_valid_npi["zip"].str.lower()
    )

    for _, block in without_valid_npi.groupby("_block_key", dropna=False):
        remaining = block.sort_values(by="organization").to_dict("records")
        while remaining:
            seed = pd.Series(remaining.pop(0))
            cluster = [seed]
            kept: list[dict[str, Any]] = []
            for candidate in remaining:
                candidate_series = pd.Series(candidate)
                if _name_address_similarity(seed, candidate_series) >= fuzzy_threshold:
                    cluster.append(candidate_series)
                else:
                    kept.append(candidate)
            remaining = kept
            cluster_df = pd.DataFrame(cluster)
            if len(cluster_df) > 1:
                merged_rows.append(_merge_rows(cluster_df))
                merge_log.append(
                    {
                        "merge_reason": "fuzzy_name_address",
                        "master_npi": cluster_df.iloc[0].get("npi", ""),
                        "merged_record_count": len(cluster_df),
                        "source_row_ids": ",".join(cluster_df["_row_id"].astype(str).tolist()),
                    }
                )
            else:
                merged_rows.append(cluster_df.iloc[0])

    if not merged_rows:
        deduped = frame.copy()
    else:
        deduped = pd.DataFrame(merged_rows)

    deduped = deduped.drop(columns=[c for c in deduped.columns if c.startswith("_")], errors="ignore")
    deduped = deduped.reset_index(drop=True)
    deduped["record_id"] = [f"PRV-{i + 1:07d}" for i in range(len(deduped))]
    merge_report = pd.DataFrame(merge_log)
    return deduped, merge_report


def build_parent_hierarchy(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    hospitals = frame[frame["entity_type"] == "hospital"].copy()

    for idx, row in frame.iterrows():
        if row.get("parent_npi"):
            continue
        if row.get("entity_type") == "hospital":
            continue

        candidates = hospitals[
            (hospitals["city"].str.lower() == str(row.get("city", "")).lower())
            & (hospitals["state"].str.lower() == str(row.get("state", "")).lower())
        ]
        if candidates.empty:
            continue

        if len(candidates) == 1:
            frame.at[idx, "parent_npi"] = candidates.iloc[0].get("npi", "")
            continue

        best_idx = None
        best_score = 0.0
        for cand_idx, cand in candidates.iterrows():
            score = SequenceMatcher(
                None,
                str(row.get("organization", "")).lower(),
                str(cand.get("organization", "")).lower(),
            ).ratio()
            if score > best_score:
                best_score = score
                best_idx = cand_idx
        if best_idx is not None and best_score >= 0.45:
            frame.at[idx, "parent_npi"] = candidates.loc[best_idx, "npi"]

    return frame


def build_exceptions(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["record_id", "npi", "organization", "issue_type", "details"]
    issues: list[dict[str, str]] = []
    for _, row in df.iterrows():
        record_id = row.get("record_id", "")
        npi = row.get("npi", "")
        organization = row.get("organization", "")

        if npi and not row.get("npi_valid", False):
            issues.append(
                {
                    "record_id": record_id,
                    "npi": npi,
                    "organization": organization,
                    "issue_type": "invalid_npi",
                    "details": "NPI failed checksum validation.",
                }
            )

        if not str(row.get("street", "")).strip() or not str(row.get("city", "")).strip() or not str(row.get("state", "")).strip():
            issues.append(
                {
                    "record_id": record_id,
                    "npi": npi,
                    "organization": organization,
                    "issue_type": "missing_address_fields",
                    "details": "One or more required address fields are missing.",
                }
            )

        if not str(row.get("specialty", "")).strip() or not str(row.get("provider_type_code", "")).strip():
            issues.append(
                {
                    "record_id": record_id,
                    "npi": npi,
                    "organization": organization,
                    "issue_type": "inconsistent_specialty_or_type",
                    "details": "Specialty or provider type code is not populated consistently.",
                }
            )

    if not issues:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(issues, columns=columns)


def build_rollup(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    children = frame[frame["parent_npi"].astype(bool)]
    if children.empty:
        return pd.DataFrame(columns=["parent_npi", "affiliated_entity_count", "child_entity_types"])

    grouped = children.groupby("parent_npi").agg(
        affiliated_entity_count=("record_id", "count"),
        child_entity_types=("entity_type", lambda s: ", ".join(sorted(set(s)))),
    )
    return grouped.reset_index()


def finalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    for col in REQUIRED_OUTPUT_COLUMNS:
        if col not in frame.columns:
            frame[col] = ""
    return frame[REQUIRED_OUTPUT_COLUMNS]
