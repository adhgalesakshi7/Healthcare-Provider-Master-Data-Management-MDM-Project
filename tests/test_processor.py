from __future__ import annotations

import pandas as pd

from provider_mdm import pipeline
from provider_mdm.processor import build_parent_hierarchy, deduplicate, is_valid_npi


def test_is_valid_npi() -> None:
    assert is_valid_npi("1234567893")
    assert not is_valid_npi("123")


def test_deduplicate_by_npi() -> None:
    df = pd.DataFrame(
        [
            {
                "npi": "1234567893",
                "npi_valid": True,
                "organization": "Acme Health",
                "street": "10 Main St",
                "city": "Albany",
                "state": "NY",
                "zip": "12207",
                "phone": "",
                "specialty": "Hospital",
                "provider_type_code": "",
                "source_name": "hospitals",
                "entity_type": "hospital",
                "parent_npi": "",
            },
            {
                "npi": "1234567893",
                "npi_valid": True,
                "organization": "Acme Health System",
                "street": "10 Main St",
                "city": "Albany",
                "state": "NY",
                "zip": "12207",
                "phone": "5181112222",
                "specialty": "Hospital",
                "provider_type_code": "12-10",
                "source_name": "hospitals",
                "entity_type": "hospital",
                "parent_npi": "",
            },
        ]
    )
    out, merge_log = deduplicate(df)
    assert len(out) == 1
    assert not merge_log.empty


def test_build_parent_hierarchy_same_city_state() -> None:
    df = pd.DataFrame(
        [
            {
                "record_id": "PRV-0000001",
                "npi": "1111111111",
                "npi_valid": False,
                "organization": "Valley Hospital",
                "street": "1 A St",
                "city": "Boston",
                "state": "MA",
                "zip": "02101",
                "phone": "",
                "provider_type_code": "",
                "specialty": "Hospital",
                "source_name": "hospitals",
                "entity_type": "hospital",
                "parent_npi": "",
            },
            {
                "record_id": "PRV-0000002",
                "npi": "2222222222",
                "npi_valid": False,
                "organization": "Valley Pediatric Clinic",
                "street": "2 A St",
                "city": "Boston",
                "state": "MA",
                "zip": "02101",
                "phone": "",
                "provider_type_code": "12-70",
                "specialty": "Primary Care",
                "source_name": "primary_care_facilities",
                "entity_type": "clinic",
                "parent_npi": "",
            },
        ]
    )

    out = build_parent_hierarchy(df)
    clinic_parent = out.loc[out["record_id"] == "PRV-0000002", "parent_npi"].iloc[0]
    assert clinic_parent == "1111111111"


def test_pipeline_module_importable() -> None:
    assert callable(pipeline.run_pipeline)
