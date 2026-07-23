from __future__ import annotations

import json
import threading
import logging
import os
import time

from .hashing import content_hash

log = logging.getLogger("tenderengine.llm")


class StubProvider:
    name = "stub"
    available = True

    def generate(self, model, system, messages, max_tokens):
        last = messages[-1]["content"] if messages else ""
        if isinstance(last, list):
            last = " ".join(p.get("text", "") for p in last if isinstance(p, dict))
        return {"text": "STUB_RESPONSE: " + str(last)[:500],
                "input_tokens": 0, "output_tokens": 0}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self):
        self._client = None
        self.available = False
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=key)
            self.available = True
        except Exception:
            self.available = False

    def generate(self, model, system, messages, max_tokens):
        resp = self._client.messages.create(
            model=model, max_tokens=max_tokens, system=system or "", messages=messages)
        text = "".join(getattr(b, "text", "") for b in resp.content
                       if getattr(b, "type", "") == "text")
        return {"text": text, "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens}


def select_provider(store):
    pref = store.get("llm.provider", "auto")
    if pref == "stub":
        return StubProvider()
    ap = AnthropicProvider()
    if pref == "anthropic":
        return ap
    return ap if ap.available else StubProvider()


_CTX = threading.local()


def set_context(tender_id=None, site_id=None):
    _CTX.tender_id = tender_id
    _CTX.site_id = site_id


def get_context():
    return (getattr(_CTX, "tender_id", None), getattr(_CTX, "site_id", None))


class LLMGateway:
    def __init__(self, store, conn, provider=None):
        self.store = store
        self.conn = conn
        self.provider = provider or select_provider(store)
        self.model_override = {}

    def model_for(self, stage):
        if stage in self.model_override:
            return self.model_override[stage]
        models = self.store.get("llm.models", {})
        return models.get(stage) or models.get("default") or "claude-haiku-4-5-20251001"

    def _price(self, model, itok, otok):
        pricing = self.store.get("llm.pricing", {})
        p = pricing.get(model) or {}
        return (itok / 1e6) * float(p.get("in", 0)) + (otok / 1e6) * float(p.get("out", 0))

    def complete(self, stage, system, messages, max_tokens=1024, prefill=None):
        model = self.model_for(stage)
        cache_on = self.store.get("llm.cache_enabled", True)
        key = content_hash({"model": model, "system": system,
                            "messages": messages, "max_tokens": max_tokens,
                            "prefill": prefill})

        if cache_on:
            row = self.conn.execute(
                "SELECT response_json, input_tokens, output_tokens FROM llm_cache "
                "WHERE cache_key = ?", (key,)).fetchone()
            if row:
                data = json.loads(row["response_json"])
                if str(data.get("text", "")).startswith("STUB_RESPONSE:") \
                        and self.provider.name != "stub":
                    self.conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (key,))
                    self.conn.commit()
                else:
                    self._record(stage, model, row["input_tokens"],
                                 row["output_tokens"], 0.0, True)
                    return {"text": data["text"], "model": model,
                            "input_tokens": row["input_tokens"],
                            "output_tokens": row["output_tokens"],
                            "cost": 0.0, "cached": True, "provider": self.provider.name}

        call_messages = messages
        if prefill:
            call_messages = list(messages) + [{"role": "assistant", "content": prefill}]
        if messages and isinstance(messages[-1].get("content"), str) \
                and not messages[-1]["content"].strip():
            raise ValueError("empty prompt content — nothing to send to the model")
        try:
            out = self.provider.generate(model, system, call_messages, max_tokens)
        except Exception as exc:
            fallback = (self.store.get("llm.models", {}) or {}).get("default")
            if fallback and fallback != model and "model" in str(exc).lower():
                log.warning("model %s rejected (%s); retrying with %s", model, exc, fallback)
                model = fallback
                out = self.provider.generate(model, system, call_messages, max_tokens)
            else:
                raise
        text = out["text"]
        if prefill and not text.lstrip().startswith(prefill.strip()[:1]):
            text = prefill + text
        cost = self._price(model, out["input_tokens"], out["output_tokens"])

        if cache_on and self.provider.name != "stub":
            self.conn.execute(
                "INSERT OR REPLACE INTO llm_cache(cache_key, model, response_json, "
                "input_tokens, output_tokens, created_at) VALUES(?,?,?,?,?,?)",
                (key, model, json.dumps({"text": text}, ensure_ascii=False),
                 out["input_tokens"], out["output_tokens"], time.time()))
            self.conn.commit()

        self._record(stage, model, out["input_tokens"], out["output_tokens"], cost, False)
        return {"text": text, "model": model,
                "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
                "cost": cost, "cached": False, "provider": self.provider.name}

    def _record(self, stage, model, itok, otok, cost, cached):
        try:
            tender_id, site_id = get_context()
            self.conn.execute(
                "INSERT INTO llm_spend(ts, stage, model, provider, input_tokens, "
                "output_tokens, cost, cached, tender_id, site_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (time.time(), stage, model, self.provider.name, itok or 0, otok or 0,
                 float(cost or 0), 1 if cached else 0, tender_id, site_id))
            self.conn.commit()
        except Exception:
            log.debug("llm_spend record failed", exc_info=True)

    def expects_real_but_stub(self):
        return self.store.get("llm.provider", "auto") != "stub" and self.provider.name == "stub"
