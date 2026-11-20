"""OpenAI backend (chat completions, strict JSON-schema output).

The API key is read from the file named by the env var CUBERAG_KEY_FILE (either the raw key, or a
KEY=value line). The key is never printed or logged. Only the report narrative is sent.
A quota/billing error raises QuotaExceeded immediately (fail fast; the runner stops the run).
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Sequence

from .base import Extraction, ReportText
from .prompt import json_schema, parse_output, system_prompt, user_prompt

QUOTA_CODES = {"insufficient_quota", "project_spend_limit_exceeded", "billing_hard_limit_reached"}


class QuotaExceeded(RuntimeError):
    pass


def load_key(env: str = "CUBERAG_KEY_FILE") -> str:
    path = os.environ.get(env)
    if not path:
        raise SystemExit(f"set {env} to the path of a file that holds the API key")
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"{env} does not point to a file")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            line = line.split("=", 1)[1].strip()
        line = line.strip("'\"")
        if line:
            return line
    raise SystemExit(f"no key found in the file named by {env}")


def is_quota_error(e: Exception) -> bool:
    codes = {getattr(e, "code", None), getattr(e, "type", None)}
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        codes |= {body.get("code"), body.get("type")}
    return bool(codes & QUOTA_CODES) or any(c in str(e) for c in QUOTA_CODES)


class OpenAIExtractor:
    def __init__(self, concepts: Sequence[str], model: str = "gpt-6.1-sol", max_chars: int = 6000,
                 reasoning_effort: str | None = "low", max_retries: int = 6, timeout: float = 120.0):
        import openai  # imported here so that --dry-run does not need the package

        self.openai = openai
        self.client = openai.OpenAI(api_key=load_key(), timeout=timeout, max_retries=0)
        self.concepts = list(concepts)
        self.model = model
        self.max_chars = max_chars
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        self.name = f"openai:{model}"
        self._sys = system_prompt(self.concepts)
        self._fmt = {"type": "json_schema",
                     "json_schema": {"name": "device_problems", "schema": json_schema(self.concepts), "strict": True}}

    def _call(self, text: str):
        kw = dict(model=self.model, response_format=self._fmt,
                  messages=[{"role": "system", "content": self._sys},
                            {"role": "user", "content": user_prompt(text, self.max_chars)}])
        if self.reasoning_effort:
            kw["reasoning_effort"] = self.reasoning_effort
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                return self.client.chat.completions.create(**kw)
            except Exception as e:  # noqa: BLE001
                if is_quota_error(e):
                    raise QuotaExceeded(type(e).__name__ + ": quota or billing limit reached") from None
                retryable = isinstance(e, (self.openai.RateLimitError, self.openai.APIConnectionError,
                                           self.openai.APITimeoutError, self.openai.InternalServerError))
                if not retryable or attempt == self.max_retries:
                    raise
                time.sleep(delay + random.random())
                delay = min(delay * 2, 60)

    def extract_one(self, r: ReportText) -> tuple[list[Extraction], dict]:
        resp = self._call(r.text)
        raw = resp.choices[0].message.content or ""
        u = resp.usage
        usage = {"input": getattr(u, "prompt_tokens", 0), "output": getattr(u, "completion_tokens", 0)}
        det = getattr(u, "completion_tokens_details", None)
        if det is not None and getattr(det, "reasoning_tokens", None) is not None:
            usage["reasoning"] = det.reasoning_tokens
        return parse_output(raw, r.rid, r.text, self.concepts), {"raw": raw, "usage": usage,
                                                                  "model_reported": resp.model}

    def extract_batch(self, reports: Sequence[ReportText]):
        return [self.extract_one(r) for r in reports]
