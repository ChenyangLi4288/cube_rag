"""Fetch a small public MAUDE sample (product code FRN, infusion pumps) from openFDA.

Public, de-identified FDA data. Writes data/raw/maude_frn_<years>.jsonl and a manifest.
Only fields needed by the small-scale test are kept. Hidden (ground-truth) fields are
`product_problems` and `event_type`; the method never sees them (see scripts/run_small_eval.py).

Usage: python scripts/fetch_maude.py --years 2020 2021 2022 2023 2024 --per-year 1000
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.fda.gov/device/event.json"
ROOT = Path(__file__).resolve().parents[1]


def fetch(search: str, limit: int, skip: int) -> list[dict]:
    q = urllib.parse.urlencode({"search": search, "limit": limit, "skip": skip})
    with urllib.request.urlopen(f"{API}?{q}", timeout=120) as resp:
        return json.load(resp)["results"]


def slim(rec: dict) -> dict | None:
    texts = [t.get("text", "") for t in rec.get("mdr_text", []) if t.get("text")]
    if not texts:
        return None
    dev = (rec.get("device") or [{}])[0]
    return {
        "id": rec.get("mdr_report_key"),
        "date_received": rec.get("date_received"),
        "manufacturer": (dev.get("manufacturer_d_name") or "NA").upper().strip(),
        "brand": dev.get("brand_name") or "NA",
        "text": "\n".join(texts),
        # hidden fields: ground truth only
        "hidden_product_problems": rec.get("product_problems") or [],
        "hidden_event_type": rec.get("event_type") or "NA",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2020, 2021, 2022, 2023, 2024])
    ap.add_argument("--per-year", type=int, default=1000)
    ap.add_argument("--product-code", default="FRN")
    args = ap.parse_args()

    out_dir = ROOT / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{args.product_code.lower()}_{min(args.years)}_{max(args.years)}"
    out = out_dir / f"maude_{tag}.jsonl"
    rows, queries = [], []
    for y in args.years:
        # spread the sample across the year: one page per quarter
        for qs, qe in [("0101", "0331"), ("0401", "0630"), ("0701", "0930"), ("1001", "1231")]:
            search = (f"device.device_report_product_code:{args.product_code} "
                      f"AND date_received:[{y}{qs} TO {y}{qe}]")
            n = args.per_year // 4
            res = fetch(search, n, 0)
            queries.append({"search": search, "limit": n, "returned": len(res)})
            rows += [s for s in map(slim, res) if s]
            time.sleep(0.5)
    seen, uniq = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            uniq.append(r)
    with out.open("w", encoding="utf-8") as fh:
        for r in uniq:
            fh.write(json.dumps(r) + "\n")
    manifest = {
        "source": API,
        "retrieved": dt.datetime.now().isoformat(timespec="seconds"),
        "file": out.name,
        "rows": len(uniq),
        "queries": queries,
        "hidden_fields": ["hidden_product_problems", "hidden_event_type"],
    }
    (out_dir / f"maude_{tag}.manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(uniq)} reports to {out}")


if __name__ == "__main__":
    main()
