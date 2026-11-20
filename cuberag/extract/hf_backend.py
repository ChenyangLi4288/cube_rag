"""Local backend: a Hugging Face instruct model run with transformers (offline, from the HF cache).

No constrained decoding: the reply is parsed leniently (first JSON object) and validated against the
same contract as the API backend. A reply that does not parse counts as an error (no facts).
Greedy decoding, so a run is deterministic for a fixed model and prompt.
"""
from __future__ import annotations

import os
from typing import Sequence

from .base import Extraction, ReportText
from .prompt import parse_output, system_prompt, user_prompt

FORMAT_HINT = ('\nAnswer with JSON only, in this form: {"findings": [{"concept": "<term>", "probability": 0.0, '
               '"evidence": "<quote>"}]}')


class HFExtractor:
    def __init__(self, concepts: Sequence[str], model: str = "Qwen/Qwen3-4B", max_chars: int = 6000,
                 max_new_tokens: int = 400, dtype: str = "bfloat16", device: str = "cuda"):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.concepts = list(concepts)
        self.model_id = model
        self.max_chars = max_chars
        self.max_new_tokens = max_new_tokens
        self.name = f"hf:{model}"
        self.tok = AutoTokenizer.from_pretrained(model, padding_side="left")
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(model, dtype=getattr(torch, dtype), device_map=device)
        self.model.eval()
        self._sys = system_prompt(self.concepts) + FORMAT_HINT

    def _prompt(self, text: str) -> str:
        msgs = [{"role": "system", "content": self._sys}, {"role": "user", "content": user_prompt(text, self.max_chars)}]
        kw = {"enable_thinking": False} if "qwen3" in self.model_id.lower() else {}
        return self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, **kw)

    def extract_batch(self, reports: Sequence[ReportText]):
        prompts = [self._prompt(r.text) for r in reports]
        enc = self.tok(prompts, return_tensors="pt", padding=True).to(self.model.device)
        with self.torch.inference_mode():
            out = self.model.generate(**enc, max_new_tokens=self.max_new_tokens, do_sample=False,
                                      pad_token_id=self.tok.pad_token_id)
        res = []
        n_in = enc["input_ids"].shape[1]
        for i, r in enumerate(reports):
            gen = out[i, n_in:]
            raw = self.tok.decode(gen, skip_special_tokens=True)
            usage = {"input": int(enc["attention_mask"][i].sum()), "output": int((gen != self.tok.pad_token_id).sum())}
            try:
                exts, err = parse_output(raw, r.rid, r.text, self.concepts), None
            except ValueError as e:
                exts, err = [], str(e)
            res.append((exts, {"raw": raw, "usage": usage, "error": err}))
        return res
