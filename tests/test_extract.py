"""Extractor contract, prompt content, key loading and quota fail-fast (no network; a fake key in a temp file)."""
import json

import pytest

from cuberag.extract import json_schema, parse_output, prompt_hash, system_prompt, user_prompt
from cuberag.extract.openai_backend import QuotaExceeded, is_quota_error, load_key

CONCEPTS = ["Crack", "Break", "False Alarm"]
TEXT = "The pump door had a CRACK near the hinge.  A false alarm sounded twice."


def test_parse_output_contract():
    raw = json.dumps({"findings": [
        {"concept": "Crack", "probability": 0.9, "evidence": "door had a crack"},
        {"concept": "crack", "probability": 0.95, "evidence": "not in text"},  # duplicate: q = max, first span
        {"concept": "False Alarm", "probability": 1.7, "evidence": "A false  alarm sounded"},  # clipped
        {"concept": "Unknown term", "probability": 0.5, "evidence": "x"},  # dropped
    ]})
    out = {e.concept: e for e in parse_output(raw, "r1", TEXT, CONCEPTS)}
    assert set(out) == {"Crack", "False Alarm"}
    assert out["Crack"].q == 0.95 and out["Crack"].span == "door had a crack" and out["Crack"].span_found
    assert out["False Alarm"].q == 1.0 and out["False Alarm"].span_found
    assert all(e.report_id == "r1" for e in out.values())


def test_parse_output_lenient_for_local_models():
    raw = '<think>\n</think>\nSure: {"findings": [{"concept": "Break", "probability": 0.4, "evidence": "zzz"}]} ok'
    (e,) = parse_output(raw, "r2", TEXT, CONCEPTS)
    assert e.concept == "Break" and e.q == 0.4 and not e.span_found
    with pytest.raises(ValueError):
        parse_output("no json here", "r3", TEXT, CONCEPTS)


def test_prompt_sends_only_report_text_and_schema_is_strict():
    u = user_prompt(TEXT, 30)
    assert TEXT[:30] in u and "[...]" in u and "r1" not in u
    s = json_schema(CONCEPTS)
    item = s["properties"]["findings"]["items"]
    assert item["additionalProperties"] is False and set(item["required"]) == {"concept", "probability", "evidence"}
    assert item["properties"]["concept"]["enum"] == CONCEPTS
    assert all(c in system_prompt(CONCEPTS) for c in CONCEPTS)
    assert prompt_hash(CONCEPTS, 6000) != prompt_hash(CONCEPTS, 5000)


def test_load_key_formats(tmp_path, monkeypatch):
    f = tmp_path / "k"
    f.write_text("# comment\nOPENAI_API_KEY='sk-test-123'\n")
    monkeypatch.setenv("CUBERAG_KEY_FILE", str(f))
    assert load_key() == "sk-test-123"
    f.write_text("sk-raw-456\n")
    assert load_key() == "sk-raw-456"
    monkeypatch.delenv("CUBERAG_KEY_FILE")
    with pytest.raises(SystemExit):
        load_key()


def test_quota_error_fails_fast(tmp_path, monkeypatch):
    pytest.importorskip("openai")
    from cuberag.extract.base import ReportText
    from cuberag.extract.openai_backend import OpenAIExtractor

    f = tmp_path / "k"
    f.write_text("sk-test")
    monkeypatch.setenv("CUBERAG_KEY_FILE", str(f))
    ex = OpenAIExtractor(CONCEPTS)
    calls = []

    class Quota(Exception):
        code = "insufficient_quota"

    def create(**kw):
        calls.append(kw)
        raise Quota("You exceeded your current quota")

    ex.client = type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": staticmethod(create)})})})
    with pytest.raises(QuotaExceeded):
        ex.extract_one(ReportText("r1", TEXT))
    assert len(calls) == 1  # no retries on a quota error
    sent = calls[0]["messages"]
    assert sent[1]["content"] == user_prompt(TEXT, ex.max_chars)
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert is_quota_error(Quota("x")) and not is_quota_error(ValueError("rate limit"))
