"""Download raw FDA MAUDE files and write a manifest.

Source page: https://www.fda.gov/medical-devices/medical-device-reporting-mdr-how-report-medical-device-problems/mdr-data-files
Files land in data/maude/raw/ (gitignored). The manifest is data/maude/MANIFEST.json.

Usage: python scripts/download_maude.py [--years 2018-2025]
"""

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.accessdata.fda.gov/MAUDE/ftparea/"
SOURCE_PAGE = (
    "https://www.fda.gov/medical-devices/medical-device-reporting-mdr-how-report-medical-device-problems/mdr-data-files"
)

# Files that cover all years (master records, problem codes and their term lists).
FIXED_FILES = [
    "mdrfoiThru2025.zip",  # master event records: event_type, dates, manufacturer
    "foidevproblem_thru2025.zip",  # report -> device problem code (hidden field)
    "deviceproblemcodes2025.zip",  # device problem code -> term
    "patientproblemcode_thru2025.zip",  # report -> patient problem code (hidden field)
    "patientproblemdata.zip",  # patient problem code -> term
    "patientthru2025.zip",  # patient records
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_rows(z: zipfile.ZipFile, member: str) -> int:
    """Data rows = physical lines minus the header line (MAUDE files are pipe-delimited with one header)."""
    n = 0
    with z.open(member) as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            n += chunk.count(b"\n")
    return max(n - 1, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2018-2025")
    ap.add_argument("--out", default="data/maude")
    args = ap.parse_args()

    y0, y1 = (int(x) for x in args.years.split("-"))
    files = FIXED_FILES + [f"{kind}{y}.zip" for y in range(y0, y1 + 1) for kind in ("device", "foitext")]

    out = Path(args.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}
    manifest.update({"dataset": "FDA MAUDE", "source_page": SOURCE_PAGE, "years": args.years})

    for name in files:
        dest = raw / name
        url = BASE + name
        prev = manifest["files"].get(name)
        if prev and "rows" in prev["members"][0] and dest.exists() and dest.stat().st_size == prev["zip_bytes"]:
            print(f"   {name} already done", flush=True)
            continue
        if not (prev and dest.exists() and dest.stat().st_size == prev["zip_bytes"]):
            print(f"-> {name}", flush=True)
            # -C - resumes a partial download; --fail stops on HTTP errors.
            subprocess.run(["curl", "-sSL", "--fail", "--retry", "5", "-C", "-", "-o", str(dest), url], check=True)
        with zipfile.ZipFile(dest) as z:  # also checks that the zip is complete
            members = [
                {"name": i.filename, "bytes": i.file_size, "rows": count_rows(z, i.filename)} for i in z.infolist()
            ]
        print(f"   {name}: {[(m['name'], m['rows']) for m in members]}", flush=True)
        if prev:  # keep the original download time
            manifest["files"][name] = {**prev, "members": members}
            manifest_path.write_text(json.dumps(manifest, indent=2))
            continue
        manifest["files"][name] = {
            "url": url,
            "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "zip_bytes": dest.stat().st_size,
            "sha256": sha256(dest),
            "members": members,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"done: {len(files)} files, manifest at {manifest_path}")


if __name__ == "__main__":
    main()
