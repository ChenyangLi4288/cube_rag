"""Pluggable fact extractors (see base.py for the output contract). Backends are imported lazily."""
from .base import Extraction, Extractor, ReportText, load_facts, write_facts
from .prompt import json_schema, parse_output, prompt_hash, system_prompt, user_prompt
