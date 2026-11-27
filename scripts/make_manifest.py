"""Write a manifest for manually downloaded raw files (VAERS, ASRS).

For each file in <dataset_dir>/raw (zip or csv) it records: size, sha256, file mtime,
and for each CSV inside: real record count (CSV-parsed, so line breaks inside text
fields are handled), columns, and the min/max of a date column if one is given.

Usage:
  python scripts/make_manifest.py data/vaers --dataset VAERS \
      --source https://vaers.hhs.gov/data/datasets.html --date-col RECVDATE --id-col VAERS_ID
"""

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe_csv(fh, name: str, date_col: str | None, id_col: str | None, header_rows: int = 1) -> dict:
    if header_rows == 1:
        df = pd.read_csv(fh, dtype=str, encoding="latin-1", keep_default_na=False)
    else:  # e.g. ASRS: group row + field row; flatten to "Group|Field"
        df = pd.read_csv(fh, header=list(range(header_rows)), dtype=str, encoding="latin-1", keep_default_na=False)
        df.columns = [
            "|".join(p for p in parts if p.strip() and not p.startswith("Unnamed")) for parts in df.columns
        ]
    info = {"name": name, "rows": len(df), "columns": list(df.columns)}
    if id_col and id_col in df.columns:
        info[f"distinct_{id_col}"] = int(df[id_col].nunique())
    if date_col and date_col in df.columns:
        d = pd.to_datetime(df[date_col], errors="coerce", format="%Y%m" if df[date_col].str.fullmatch(r"\d{6}").all() else None)
        info[f"{date_col}_min"] = str(d.min().date()) if d.notna().any() else None
        info[f"{date_col}_max"] = str(d.max().date()) if d.notna().any() else None
        info[f"{date_col}_unparsed"] = int(d.isna().sum())
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_dir")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--source", required=True, help="page the files were downloaded from")
    ap.add_argument("--date-col")
    ap.add_argument("--id-col")
    ap.add_argument("--header-rows", type=int, default=1)
    ap.add_argument("--note", help="free-text note stored in the manifest")
    args = ap.parse_args()

    root = Path(args.dataset_dir)
    manifest = {
        "dataset": args.dataset,
        "source_page": args.source,
        "download_method": "manual (website)",
        "manifest_written_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {},
    }
    if args.note:
        manifest["note"] = args.note
    for path in sorted((root / "raw").iterdir()):
        if path.name.startswith(".") or path.suffix.lower() not in {".zip", ".csv", ".xls"}:
            continue
        print(f"-> {path.name}", flush=True)
        entry = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "file_mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "members": [],
        }
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for m in z.namelist():
                    if m.lower().endswith(".csv"):
                        with z.open(m) as fh:
                            entry["members"].append(describe_csv(fh, m, args.date_col, args.id_col, args.header_rows))
        elif path.suffix.lower() == ".xls":  # web report saved as an HTML table (e.g. FAA OPSNET export)
            for i, t in enumerate(pd.read_html(path)):
                cols = ["|".join(p for p in (c if isinstance(c, tuple) else (c,)) if not str(p).startswith("Unnamed"))
                        for c in t.columns]
                entry["members"].append({"name": f"{path.name}#table{i}", "format": "html table",
                                         "rows": len(t), "columns": [c for c in cols if c]})
        else:
            with path.open("rb") as fh:
                entry["members"].append(describe_csv(fh, path.name, args.date_col, args.id_col, args.header_rows))
        manifest["files"][path.name] = entry

    out = root / "MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2))
    print(f"done: {out}")


if __name__ == "__main__":
    main()
