"""Run an LLM fact extractor over the pilot MAUDE split, with per-report caching and a run manifest.

Backends
  --backend openai   model gpt-6.1-sol (default), strict JSON schema. Key: file named by $CUBERAG_KEY_FILE.
  --backend hf       local transformers model from the HF cache (e.g. Qwen/Qwen3-4B), GPU if available.

Modes
  --dry-run          no model calls: count calls still needed (cache misses) and estimate tokens.
  --limit N          process only the first N reports of the split (smoke test).

Outputs (in --out-dir, default data/extract/<backend>_<model>/):
  cache/<report id>.json   one reply per report, keyed by (prompt hash, model, text hash)
  facts_<split>.jsonl      the extractions (contract in cuberag/extract/base.py)
  manifest.json            prompt hash, model, dates, counts, token usage, status

The split is the pilot split (scripts/run_small_eval.py: seed 0, 40% train / 60% eval).
Only the report narrative is sent to the model.
Exit code 2 = stopped on a quota/billing error (fail fast); rerun after fixing it, the cache resumes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cuberag.extract.base import Extraction, ReportText, write_facts  # noqa: E402
from cuberag.extract.prompt import (PROMPT_VERSION, prompt_hash, system_prompt, text_hash,  # noqa: E402
                                    user_prompt)

DATA = ROOT / "data/raw/maude_frn_2020_2024.jsonl"


def pilot_leaves() -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_small_eval import GROUPS
    return sorted({l for ls in GROUPS.values() for l in ls})


def split_rows(rows: list[dict], seed: int = 0) -> tuple[list[dict], list[dict]]:
    """Identical to run_small_eval.py: the first draw of default_rng(seed) is the permutation."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(rows))
    ntr = int(0.4 * len(rows))
    return [rows[i] for i in perm[:ntr]], [rows[i] for i in perm[ntr:]]


def cache_key(phash: str, model: str, text: str) -> str:
    return f"{phash}:{model}:{text_hash(text)}"


def read_cache(path: Path, key: str) -> dict | None:
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return d if d.get("key") == key else None


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["openai", "hf"], required=True)
    ap.add_argument("--model", default=None, help="default: gpt-6.1-sol (openai), Qwen/Qwen3-4B (hf)")
    ap.add_argument("--split", choices=["eval", "train", "all"], default="eval")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--max-chars", type=int, default=6000, help="truncate a narrative to this many characters")
    ap.add_argument("--reasoning-effort", default="low", help="openai only; 'none' to omit the parameter")
    ap.add_argument("--workers", type=int, default=4, help="openai: concurrent requests")
    ap.add_argument("--batch-size", type=int, default=4, help="hf: reports per generate() call")
    ap.add_argument("--max-new-tokens", type=int, default=400, help="hf only")
    ap.add_argument("--retry-errors", action="store_true", help="redo cached replies that failed to parse")
    ap.add_argument("--est-output-tokens", type=int, default=150,
                    help="dry run: visible output tokens per call (reasoning tokens come on top)")
    ap.add_argument("--price-in", type=float, default=None, help="dry run: USD per 1M input tokens")
    ap.add_argument("--price-out", type=float, default=None, help="dry run: USD per 1M output tokens")
    args = ap.parse_args()
    model = args.model or ("gpt-6.1-sol" if args.backend == "openai" else "Qwen/Qwen3-4B")
    out = Path(args.out_dir) if args.out_dir else ROOT / "data/extract" / safe(f"{args.backend}_{model}")
    (out / "cache").mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8")]
    train, ev = split_rows(rows)
    sel = {"eval": ev, "train": train, "all": train + ev}[args.split]
    if args.limit is not None:
        sel = sel[:args.limit]
    concepts = pilot_leaves()
    phash = prompt_hash(concepts, args.max_chars)
    keys = {r["id"]: cache_key(phash, model, r["text"]) for r in sel}

    def cached(r):
        d = read_cache(out / "cache" / f"{safe(r['id'])}.json", keys[r["id"]])
        if d is not None and args.retry_errors and d.get("error"):
            return None
        return d

    todo = [r for r in sel if cached(r) is None]
    print(f"backend={args.backend} model={model} split={args.split} reports={len(sel)} "
          f"cached={len(sel) - len(todo)} to_call={len(todo)} prompt_hash={phash} concepts={len(concepts)}")

    if args.dry_run:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        sys_tok = len(enc.encode(system_prompt(concepts)))
        per = np.array([sys_tok + len(enc.encode(user_prompt(r["text"], args.max_chars))) + 12 for r in todo] or [0])
        tin, tout = int(per.sum()), args.est_output_tokens * len(todo)
        est = {"calls": len(todo), "input_tokens": tin, "input_tokens_per_call_mean": float(per.mean()),
               "input_tokens_per_call_max": int(per.max()), "system_prompt_tokens": sys_tok,
               "output_tokens_est": tout, "tokenizer": "o200k_base (approximation for the target model)",
               "note": "reasoning tokens are billed as output and are not included"}
        if args.price_in is not None and args.price_out is not None:
            est["usd_est"] = round(tin / 1e6 * args.price_in + tout / 1e6 * args.price_out, 2)
        print(json.dumps(est, indent=1))
        (out / f"dry_run_{args.split}{'' if args.limit is None else f'_limit{args.limit}'}.json").write_text(
            json.dumps({"model": model, "prompt_hash": phash, "date": dt.datetime.now().isoformat(timespec="seconds"),
                        **est}, indent=1))
        return

    if args.backend == "openai":
        from cuberag.extract.openai_backend import OpenAIExtractor, QuotaExceeded
        eff = None if args.reasoning_effort == "none" else args.reasoning_effort
        backend = OpenAIExtractor(concepts, model, args.max_chars, eff)
    else:
        from cuberag.extract.hf_backend import HFExtractor
        QuotaExceeded = ()  # noqa: N806
        backend = HFExtractor(concepts, model, args.max_chars, args.max_new_tokens)

    started = dt.datetime.now().isoformat(timespec="seconds")
    status, n_err, usage_tot = "complete", 0, {"input": 0, "output": 0, "reasoning": 0}
    t0 = time.time()

    def save(r, exts: list[Extraction], meta: dict) -> None:
        d = {"key": keys[r["id"]], "id": r["id"], "model": model, "prompt_hash": phash,
             "date": dt.datetime.now().isoformat(timespec="seconds"),
             "extractions": [e.to_json() for e in exts], **meta}
        (out / "cache" / f"{safe(r['id'])}.json").write_text(json.dumps(d), encoding="utf-8")
        for k in usage_tot:
            usage_tot[k] += int(meta.get("usage", {}).get(k, 0) or 0)

    done = 0
    try:
        if args.backend == "openai":
            with ThreadPoolExecutor(args.workers) as pool:
                futs = {pool.submit(backend.extract_one, ReportText(r["id"], r["text"])): r for r in todo}
                for f in as_completed(futs):
                    r = futs[f]
                    try:
                        exts, meta = f.result()
                    except QuotaExceeded as e:
                        status = "stopped_quota"
                        print("STOP:", e, file=sys.stderr)
                        for g in futs:
                            g.cancel()
                        break
                    except Exception as e:  # noqa: BLE001  (parse/validation errors: record and go on)
                        exts, meta = [], {"error": f"{type(e).__name__}: {e}"[:500]}
                    n_err += bool(meta.get("error"))
                    save(r, exts, meta)
                    done += 1
                    if done % 50 == 0:
                        print(f"  {done}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
        else:
            todo.sort(key=lambda r: len(r["text"]))  # less padding per batch; results are per report
            for i in range(0, len(todo), args.batch_size):
                batch = todo[i:i + args.batch_size]
                for r, (exts, meta) in zip(batch, backend.extract_batch([ReportText(r["id"], r["text"]) for r in batch])):
                    n_err += bool(meta.get("error"))
                    save(r, exts, meta)
                    done += 1
                if (i // args.batch_size) % 10 == 0:
                    el = time.time() - t0
                    print(f"  {done}/{len(todo)}  {el:.0f}s  ({el / max(done, 1):.2f}s/report)", flush=True)
    except KeyboardInterrupt:
        status = "interrupted"

    # facts file over every report of the selection that has a cached reply
    exts, missing, errors = [], 0, 0
    for r in sel:
        d = read_cache(out / "cache" / f"{safe(r['id'])}.json", keys[r["id"]])
        if d is None:
            missing += 1
            continue
        errors += bool(d.get("error"))
        exts += [Extraction(e["id"], e["concept"], e["q"], e.get("span"), e.get("span_found", False))
                 for e in d["extractions"]]
    tag = args.split if args.limit is None else f"{args.split}_limit{args.limit}"
    n_facts = write_facts(out / f"facts_{tag}.jsonl", exts)
    man = {"backend": args.backend, "model": model, "prompt_version": PROMPT_VERSION, "prompt_hash": phash,
           "concepts": concepts, "max_chars": args.max_chars, "split": args.split, "limit": args.limit,
           "reasoning_effort": args.reasoning_effort if args.backend == "openai" else None,
           "started": started, "finished": dt.datetime.now().isoformat(timespec="seconds"),
           "seconds": round(time.time() - t0, 1), "status": status, "reports": len(sel),
           "calls_this_run": done, "reports_missing": missing, "reports_with_error": errors,
           "facts": n_facts, "span_found_rate": (sum(e.span_found for e in exts) / max(len(exts), 1)),
           "usage_this_run": usage_tot, "facts_file": f"facts_{tag}.jsonl",
           "data_sent": "report narrative only"}
    (out / f"manifest_{tag}.json").write_text(json.dumps(man, indent=1))
    print(json.dumps({k: v for k, v in man.items() if k != "concepts"}, indent=1))
    if status == "stopped_quota":
        sys.exit(2)


if __name__ == "__main__":
    main()
