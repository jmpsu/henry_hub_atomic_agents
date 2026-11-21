"""Local Ollama intelligence layer shared by every agent.

Configuration (explicit; every value can be overridden by environment variable, see CONFIG below):
- Model routing: each task kind maps to a local model (reasoning/extraction -> qwen3:4b, embeddings -> nomic-embed-text),
  a token budget and a timeout. Generations enforce a JSON schema, send /no_think with think=false and temperature 0.
- Transient failures (connection refused, HTTP 5xx) are retried once; timeouts are not retried (the call is expensive).
- `status()` checks that the configured models are actually installed, not merely that the daemon answers.
- Every call is recorded in `llm_calls` (agent, task, model, prompt version, prompt sha256, latency, ok, error, fallback),
  so a finding can always be traced to the exact model invocation - or the deterministic fallback - that produced it.
- Fallback: `json(..., fallback=fn)` returns fn() when the model fails or its answer fails `validate`; the call is logged
  with fallback=1 and `last_source` says which path produced the answer.
- Guards: `numbers_grounded()` rejects model text that contains numbers absent from the evidence it was given, so the model
  cannot invent market observations; numbers shown to users always come from the database.
Runs only against the local Ollama daemon (127.0.0.1:11434 by default). No external AI service.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger("agents.llm")


def _env(name: str, default):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return type(default)(v)


OLLAMA = _env("HH_OLLAMA_URL", "http://127.0.0.1:11434")
REASONING_MODEL = _env("HH_REASONING_MODEL", "qwen3:4b")
EMBED_MODEL = _env("HH_EMBED_MODEL", "nomic-embed-text")
CONFIG = {  # task kind -> model, num_predict, timeout seconds
    "extract": {"model": REASONING_MODEL, "num_predict": _env("HH_EXTRACT_TOKENS", 260), "timeout": _env("HH_EXTRACT_TIMEOUT", 90.0)},
    "classify": {"model": REASONING_MODEL, "num_predict": 120, "timeout": _env("HH_CLASSIFY_TIMEOUT", 60.0)},
    "interpret": {"model": REASONING_MODEL, "num_predict": 260, "timeout": _env("HH_INTERPRET_TIMEOUT", 90.0)},
    "investigate": {"model": REASONING_MODEL, "num_predict": 220, "timeout": _env("HH_INVESTIGATE_TIMEOUT", 90.0)},
    "triage": {"model": REASONING_MODEL, "num_predict": 120, "timeout": _env("HH_TRIAGE_TIMEOUT", 60.0)},
    "synthesize": {"model": REASONING_MODEL, "num_predict": _env("HH_SYNTH_TOKENS", 700), "timeout": _env("HH_SYNTH_TIMEOUT", 240.0)},
    "diagnose": {"model": REASONING_MODEL, "num_predict": 200, "timeout": _env("HH_DIAGNOSE_TIMEOUT", 60.0)},
    "embed": {"model": EMBED_MODEL, "num_predict": 0, "timeout": _env("HH_EMBED_TIMEOUT", 30.0)},
}
ROUTES = {k: (v["model"], v["num_predict"]) for k, v in CONFIG.items()}   # kept for callers of the earlier interface
NUM_CTX = _env("HH_NUM_CTX", 4096)
RETRIES = _env("HH_LLM_RETRIES", 1)


class ModelUnavailable(RuntimeError):
    pass


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS llm_calls(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, agent TEXT, task TEXT, model TEXT, "
                 "prompt_sha256 TEXT, ms INTEGER, ok INTEGER, error TEXT)")
    have = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
    for col, decl in (("prompt_version", "TEXT"), ("fallback", "INTEGER DEFAULT 0")):
        if col not in have:                                  # additive migration; existing rows keep their values
            conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {col} {decl}")


def status(client: httpx.Client | None = None) -> dict:
    """Which configured models are installed. ok only when the daemon answers AND every configured model is present."""
    need = sorted({v["model"] for v in CONFIG.values()})
    try:
        r = (client or httpx.Client(timeout=5)).get(f"{OLLAMA}/api/tags", timeout=5)
        r.raise_for_status()
        names = {m["name"] for m in r.json().get("models", [])}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "daemon": False, "error": f"{type(e).__name__}: {e}"[:200], "required": need, "missing": need}
    present = lambda m: m in names or f"{m}:latest" in names
    missing = [m for m in need if not present(m)]
    return {"ok": not missing, "daemon": True, "required": need, "missing": missing, "url": OLLAMA}


class LLM:
    def __init__(self, conn: sqlite3.Connection, agent: str, client: httpx.Client | None = None, available: bool = True):
        self.conn, self.agent = conn, agent
        self.client = client or httpx.Client()
        self.available = available          # False: skip the model entirely and use fallbacks (daemon down / model missing)
        self.last_source = None             # "model" | "fallback" for the most recent json() call
        ensure(conn)

    def _log(self, task, model, prompt, t0, ok, err=None, version="", fallback=False):
        self.conn.execute("INSERT INTO llm_calls(at,agent,task,model,prompt_sha256,ms,ok,error,prompt_version,fallback) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), self.agent, task, model,
                           hashlib.sha256(prompt.encode()).hexdigest(), int((time.time() - t0) * 1000), int(ok), (err or "")[:300], version,
                           int(fallback)))
        self.conn.commit()
        if not ok:
            log.warning("llm %s/%s %s failed: %s%s", self.agent, task, model, err, " (fallback used)" if fallback else "")

    def _post(self, path: str, body: dict, timeout: float) -> dict:
        last = None
        for attempt in range(RETRIES + 1):
            try:
                r = self.client.post(f"{OLLAMA}{path}", json=body, timeout=timeout)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r.json()
            except httpx.TimeoutException:
                raise                                        # never retry a timeout: it already cost the full budget
            except (httpx.ConnectError, httpx.HTTPStatusError, httpx.RemoteProtocolError) as e:
                last = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    raise
                if attempt < RETRIES:
                    time.sleep(1.5)
        raise last

    def json(self, task: str, prompt: str, schema: dict, fallback=None, validate=None, version: str = "") -> dict:
        """Schema-constrained generation. validate(out) -> error string or None. On any failure: fallback() if given, else raise."""
        cfg = CONFIG[task]
        model = cfg["model"]
        prompt = prompt.rstrip() + " /no_think"
        t0 = time.time()
        try:
            if not self.available:
                raise ModelUnavailable(f"{model} unavailable (status check failed)")
            data = self._post("/api/generate", {"model": model, "prompt": prompt, "format": schema, "stream": False, "think": False,
                                                "keep_alive": -1, "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": cfg["num_predict"]}},
                              cfg["timeout"])
            text = data.get("response", "")
            if not text.strip():
                raise ValueError("empty model response")
            if data.get("done_reason") == "length":
                raise ValueError(f"model output truncated at num_predict={cfg['num_predict']} tokens")
            out = json.loads(text)
            missing = [k for k in schema.get("required", []) if k not in out]
            if missing:
                raise ValueError(f"model output missing required fields {missing}")
            err = validate(out) if validate else None
            if err:
                raise ValueError(f"model output failed validation: {err}")
            self._log(task, model, prompt, t0, True, version=version)
            self.last_source = "model"
            return out
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if fallback is None:
                self._log(task, model, prompt, t0, False, msg, version)
                self.last_source = None
                raise
            self._log(task, model, prompt, t0, False, msg, version, fallback=True)
            self.last_source = "fallback"
            return fallback()

    def embed(self, text: str) -> list:
        cfg = CONFIG["embed"]
        t0 = time.time()
        try:
            if not self.available:
                raise ModelUnavailable(f"{cfg['model']} unavailable (status check failed)")
            v = self._post("/api/embeddings", {"model": cfg["model"], "prompt": text}, cfg["timeout"])["embedding"]
            if not v:
                raise ValueError("empty embedding")
            self._log("embed", cfg["model"], text, t0, True)
            return v
        except Exception as e:  # noqa: BLE001
            self._log("embed", cfg["model"], text, t0, False, f"{type(e).__name__}: {e}")
            raise


_NUM = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:[.,]\d+)?")


def numbers_grounded(text: str, evidence: str, ignore=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)) -> list:
    """Numbers in `text` that do not appear in `evidence`. A number counts as given when its absolute value equals an evidence
    number's absolute value, allowing the model to round to the precision it wrote (6.72 for -6.720, 84.5 for 84.47); small
    counting numbers 0-10 are allowed. An empty list means every number the model wrote was given to it."""
    have = []
    for n in _NUM.findall(evidence):
        try:
            have.append(abs(float(n.replace(",", ""))))
        except ValueError:
            pass
    bad = []
    for n in _NUM.findall(text):
        k = n.replace(",", "").lstrip("+")
        try:
            v = abs(float(k))
        except ValueError:
            bad.append(n)
            continue
        if v in ignore:
            continue
        d = len(k.split(".")[1]) if "." in k else 0
        if any(abs(round(h, d) - v) < 1e-9 for h in have):
            continue
        bad.append(n)
    return bad
