"""Download the CDC vaccine-dose files used as VAERS exposure (STUDENT_START task 5, issue #4).

Each file is the full CSV export of a data.cdc.gov dataset, saved unchanged under
data/vaers/exposure/raw/ and frozen like data/<ds>/raw/ (an existing file is never overwritten).
The manifest records, per file: dataset id and title, export URL, CDC's last data update,
download time, size, sha256, row count and columns.

The FAA OPSNET and BTS T-100 files (ASRS exposure) are downloaded by hand in a browser; their
manifest is written with scripts/make_manifest.py data/asrs/exposure.

Usage:
  python scripts/download_exposure.py
"""

import csv
import hashlib
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "vaers" / "exposure"
UA = {"User-Agent": "cuberag-research-download/1.0"}

# id -> (file stem, why it is used)
DATASETS = {
    "rh2h-3yt2": ("cdc_covid19_vaccination_trends", "COVID-19 doses administered per day, national and by jurisdiction, by administration date (main COVID series)"),
    "unsk-b7fc": ("cdc_covid19_vaccinations_jurisdiction", "COVID-19 cumulative doses administered by jurisdiction, with 5+/12+/18+/65+ columns (age bands)"),
    "ewpg-rz7g": ("cdc_covid19_iqvia_pharmacy_office", "COVID-19 doses in retail pharmacies and physician offices, adults, from Sep 2023 (IQVIA; separate series)"),
    "83ng-twza": ("cdc_flu_iqvia_pharmacy_office", "Influenza doses in retail pharmacies and physician offices, adults 18+, weekly, 2019-20 to 2023-24 (IQVIA)"),
    "ysd3-txwj": ("cdc_flu_iqvia_pharmacy_office_by_age", "Same as 83ng-twza, by adult age group"),
    "ph8r-wzxn": ("cdc_flu_doses_distributed", "Influenza doses distributed (supply), weekly cumulative by season, from 2018-19"),
}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
        return r.read()


def main() -> None:
    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        "dataset": "CDC vaccine doses (VAERS exposure)",
        "source_page": "https://data.cdc.gov",
        "download_method": "scripts/download_exposure.py (data.cdc.gov CSV export)",
        "files": {},
    }
    for ds_id, (stem, purpose) in DATASETS.items():
        path = raw / f"{stem}__{ds_id}.csv"
        if path.exists():
            print(f"skip {path.name}: already downloaded (raw files are frozen)")
            continue
        meta = json.loads(fetch(f"https://data.cdc.gov/api/views/{ds_id}.json"))
        url = f"https://data.cdc.gov/api/views/{ds_id}/rows.csv?accessType=DOWNLOAD"
        body = fetch(url)
        path.write_bytes(body)
        reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
        columns = next(reader)
        n_rows = sum(1 for _ in reader)
        manifest["files"][path.name] = {
            "dataset_id": ds_id,
            "title": meta.get("name"),
            "purpose": purpose,
            "landing_page": f"https://data.cdc.gov/d/{ds_id}",
            "export_url": url,
            "cdc_rows_updated_utc": datetime.fromtimestamp(meta["rowsUpdatedAt"], timezone.utc).isoformat(timespec="seconds")
            if meta.get("rowsUpdatedAt") else None,
            "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "rows": n_rows,
            "columns": columns,
        }
        print(f"{path.name}: {n_rows:,} rows, {len(body) / 1e6:.1f} MB")
        manifest["manifest_written_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
