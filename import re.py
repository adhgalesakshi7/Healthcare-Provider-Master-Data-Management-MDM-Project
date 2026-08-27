import re
from typing import Optional
import pandas as pd
from provider_mdm import processor

def test_is_valid_npi():
    assert isinstance(processor.is_valid_npi("1234567893"), bool)
    assert not processor.is_valid_npi("123")

def test_deduplicate_merge():
    csv = """npi,first_name,last_name,organization,street,city,state,zip,specialty,updated_at
1234567893,John,Doe,,123 Main St,Anytown,NY,12345,Cardiology,2026-01-01
1234567893,John,D.,,123 Main St,Anytown,NY,12345,,2026-02-01
"""
    df = pd.read_csv(pd.io.common.StringIO(csv), dtype=str).fillna("")
    deduped = processor.deduplicate(df)
    assert len(deduped) == 1

def test_build_parent_hierarchy():
    df = pd.DataFrame([
        {"npi":"1111111111","organization":"Acme Health"},
        {"npi":"2222222222","organization":"Acme Health Clinic","parent_org_npi":""}
    ])
    res = processor.build_parent_hierarchy(df)
    assert res.loc[res['npi']=="2222222222","parent_npi"].values[0] in ("1111111111","")

NPPES_API = "https://npiregistry.cms.hhs.gov/api/"

def load_providers(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    if 'updated_at' not in df.columns:
        df['updated_at'] = ""
    return df

def is_valid_npi(npi: str) -> bool:
    npi = re.sub(r'\D', '', str(npi))
    if len(npi) != 10:
        return False
    # NPI uses Luhn with prefix "80840"
    digits = [int(d) for d in "80840" + npi[:-1]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    check = (10 - (total % 10)) % 10
    try:
        return check == int(npi[-1])
    except Exception:
        return False

def validate_npis(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['npi_valid'] = df['npi'].apply(lambda x: is_valid_npi(x))
    return df

def merge_records(group: pd.DataFrame) -> pd.Series:
    def pick(col):
        nonempty = group[group[col].astype(bool)]
        if nonempty.empty:
            return ""
        if 'updated_at' in group.columns:
            nonempty = nonempty.sort_values(by='updated_at', ascending=False)
        return nonempty.iloc[0][col]
    cols = group.columns
    merged = {c: pick(c) for c in cols if c != 'npi'}
    merged['npi'] = group.iloc[0]['npi']
    return pd.Series(merged)

def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['npi_key'] = df['npi'].replace("", pd.NA)
    merged = []
    for npi, group in df.groupby('npi_key', dropna=True):
        merged.append(merge_records(group))
    without = df[df['npi_key'].isna()]
    for _, group in without.groupby(['organization','street','city','state','zip']):
        if len(group) > 1:
            merged.append(merge_records(group))
        else:
            merged.append(group.iloc[0])
    result = pd.DataFrame(merged).reset_index(drop=True)
    return result

def fetch_nppes(npi: str, timeout: int = 5) -> Optional[dict]:
    if not npi or not is_valid_npi(npi):
        return None
    params = {"number": npi, "version": "2.1"}
    resp = requests.get(NPPES_API, params=params, timeout=timeout)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if 'results' not in data or not data['results']:
        return None
    return data['results'][0]

def enrich(df: pd.DataFrame, use_api: bool = False) -> pd.DataFrame:
    df = df.copy()
    df['enriched'] = False
    for i, row in df.iterrows():
        npi = row.get('npi', '')
        if use_api and is_valid_npi(npi):
            rec = fetch_nppes(npi)
            if rec:
                basic = {
                    'organization': rec.get('basic', {}).get('name', row.get('organization','')),
                    'street': rec.get('addresses', [{}])[0].get('address_1', row.get('street','')),
                    'city': rec.get('addresses', [{}])[0].get('city', row.get('city','')),
                    'state': rec.get('addresses', [{}])[0].get('state', row.get('state','')),
                    'zip': rec.get('addresses', [{}])[0].get('postal_code', row.get('zip',''))
                }
                for k,v in basic.items():
                    if v:
                        df.at[i,k] = v
                df.at[i,'enriched'] = True
        else:
            df.at[i,'organization'] = row.get('organization','').strip()
    return df

def build_parent_hierarchy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['parent_npi'] = df.get('parent_org_npi', "")
    org_to_npi = {r['organization']: r['npi'] for _,r in df.iterrows() if r.get('organization')}
    for i, row in df.iterrows():
        if not row.get('parent_npi'):
            for org, npi in org_to_npi.items():
                if org and org.lower() in str(row.get('organization','')).lower() and npi != row['npi']:
                    df.at[i, 'parent_npi'] = npi
                    break
    return df

def export_df(df: pd.DataFrame, out_path: str):
    df.to_csv(out_path, index=False)

# package init
from . import processor
__all__ = ["processor"]