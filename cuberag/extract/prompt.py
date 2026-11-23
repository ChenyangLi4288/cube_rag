"""Prompt, JSON schema and output parsing shared by the LLM backends.

Only the report narrative is sent to a model: no id, date, manufacturer or hidden code.
The prompt hash (sha256 of the system prompt + schema + concept list) identifies a prompt version
in the cache and the run manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Sequence

from .base import Extraction

PROMPT_VERSION = "1"

# Short reading hints for the FDA device-problem terms of the pilot lattice. They are our own
# paraphrases, NOT the official FDA/IMDRF definitions (STUDENT_START task 4 replaces them).
CONCEPT_HINTS = {
    "Battery Problem": "battery fails, drains, swells, will not charge or hold charge",
    "Break": "a part is broken, snapped or fractured",
    "Calibration Problem": "device is out of calibration or calibration is inaccurate",
    "Circuit Failure": "a circuit board or electronic circuit failed",
    "Complete Loss of Power": "the device lost all power or would not power on",
    "Contamination": "fluid ingress or foreign material/contaminant in or on the device",
    "Corroded": "corrosion or rust on a part (e.g. contacts, pins)",
    "Crack": "a crack in the housing, door, case or another part",
    "Defective Alarm": "an alarm that should sound does not, or the alarm itself is defective",
    "Deformation Due to Compressive Stress": "a part is bent, crushed or deformed",
    "Device Alarm System": "the device alarmed (alarm, alert or error code during use)",
    "Device Sensing Problem": "a sensor (air-in-line, pressure, door, occlusion sensor) malfunctions",
    "Display Difficult to Read": "display is dim, faded, flickering or hard to read",
    "Display or Visual Feedback Problem": "display shows wrong or garbled information or visual feedback fails",
    "Electrical /Electronic Property Problem": "electrical or electronic malfunction not otherwise specified",
    "Excess Flow or Over-Infusion": "more fluid/drug delivered than programmed (over-infusion, free flow)",
    "Failure to Align": "parts do not align or seat (e.g. cassette, door, channel)",
    "Failure to Calibrate": "the device fails its calibration procedure",
    "Failure to Infuse": "the pump did not infuse at all",
    "Failure to Read Input Signal": "keys/buttons or input do not respond; device does not read an input",
    "Failure to Sense": "the device fails to detect a condition it should detect",
    "False Alarm": "an alarm occurs without a real alarm condition (nuisance or false alarm)",
    "Filling Problem": "problem filling or priming the reservoir, set or line",
    "Fluid/Blood Leak": "fluid or blood leaks from the device or set",
    "Improper Flow or Infusion": "flow or infusion is improper or wrong (rate, sequence, programming)",
    "Inaccurate Delivery": "delivered amount is inaccurate",
    "Infusion or Flow Problem": "an unspecified problem with infusion or flow",
    "Insufficient Flow or Under Infusion": "less delivered than programmed (under-infusion, delay)",
    "Mechanical Problem": "an unspecified mechanical malfunction",
    "Mechanics Altered": "mechanical parts are altered, loose or displaced",
    "Misassembled": "the device or a part was assembled incorrectly",
    "Naturally Worn": "a part is worn from normal use",
    "No Display/Image": "the display is blank or shows nothing",
    "Obstruction of Flow": "occlusion or obstruction of flow (occlusion alarm with a real blockage)",
    "Peeled/Delaminated": "a label, coating or layer is peeling or delaminated",
    "Physical Resistance/Sticking": "a part sticks, jams or resists movement (keys, door, plunger)",
    "Pressure Problem": "pressure is abnormal or pressure readings are wrong",
    "Volume Accuracy Problem": "the delivered or measured volume is not accurate",
}

SYSTEM = """You code FDA MAUDE medical-device adverse-event reports for infusion pumps.
You receive one report narrative. Decide which of the listed FDA device-problem terms the report
describes for the device. For each term that applies (and only those), return:
- "concept": the term, copied exactly from the list;
- "probability": your probability (0 to 1) that a careful FDA coder would assign this term;
- "evidence": a short verbatim quote (at most 30 words) from the report that supports the term.
Use only the report text. Include a term with a low probability if it is plausible but uncertain.
Omit terms that clearly do not apply. Return an empty list if none apply.

Terms (with reading hints):
{terms}"""


def term_block(concepts: Sequence[str]) -> str:
    return "\n".join(f"- {c}: {CONCEPT_HINTS.get(c, '')}".rstrip(": ") for c in concepts)


def system_prompt(concepts: Sequence[str]) -> str:
    return SYSTEM.format(terms=term_block(concepts))


def user_prompt(text: str, max_chars: int) -> str:
    t = text if len(text) <= max_chars else text[:max_chars] + " [...]"
    return f"Report:\n\"\"\"\n{t}\n\"\"\""


def json_schema(concepts: Sequence[str]) -> dict:
    """Strict JSON schema (OpenAI structured outputs: every field required, no extra fields)."""
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string", "enum": list(concepts)},
                        "probability": {"type": "number"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["concept", "probability", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


def prompt_hash(concepts: Sequence[str], max_chars: int) -> str:
    blob = json.dumps({"v": PROMPT_VERSION, "system": system_prompt(concepts), "schema": json_schema(concepts),
                       "max_chars": max_chars}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _extract_json(raw: str) -> dict:
    """Parse a model reply. Strict for API output; tolerant (first {...} block) for local models."""
    raw = raw.strip()
    raw = re.sub(r"^<think>.*?</think>", "", raw, flags=re.S).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError("no JSON object in model output")


def parse_output(raw: str, rid: str, text: str, concepts: Sequence[str]) -> list[Extraction]:
    """Validate a reply against the contract. Unknown concepts are dropped; q is clipped to [0, 1];
    duplicate concepts keep the max q (D3) and the first span; spans are checked against the text."""
    obj = _extract_json(raw)
    items = obj.get("findings", []) if isinstance(obj, dict) else []
    allowed = {c.lower(): c for c in concepts}
    ntext = _norm(text)
    best: dict[str, Extraction] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        c = allowed.get(str(it.get("concept", "")).strip().lower())
        if c is None:
            continue
        try:
            q = float(it.get("probability", 0.0))
        except (TypeError, ValueError):
            continue
        q = min(max(q, 0.0), 1.0)
        span = it.get("evidence")
        span = str(span) if span else None
        found = bool(span) and _norm(span) in ntext
        if c not in best or q > best[c].q:
            prev = best.get(c)
            best[c] = Extraction(rid, c, q, prev.span if prev and prev.span else span,
                                 prev.span_found if prev and prev.span else found)
    return list(best.values())
