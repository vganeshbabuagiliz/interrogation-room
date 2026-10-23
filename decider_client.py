"""Thin adapter around `strands-decider serve` (POST /v1/systemone).

All wire-format knowledge lives here. Verified against strands_decider/schema.py
(v0.2.0 package):

  request : {"state": ..., "model": ..., "questions": {name: question}}
    noul   -> {"type": "noul",   "instructions": str, "criteria": {"true": str, "false": str}}
    choice -> {"type": "choice", "instructions": str, "criteria": {option: description}}
  response: {"answers": {name: ...}, "usage": {...}, "latency_ms": float}
    noul   -> {"type": "noul",   "noul": P(true)}
    choice -> {"type": "choice", "choice": str, "probabilities": {...}, "confidence": 0..1}
"""
import os
import time

import requests

from decisions import Q


def _load_dotenv(path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")) -> None:
    """Minimal .env reader (KEY=VALUE lines); never overrides variables already set."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8").read().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))


_load_dotenv()

# DECIDER_MODE: local (strands-decider serve, POST /v1/systemone, no key) or
# ugmdu (AWS User Group Madurai hosted API, POST /v1/decide, Authorization: Bearer <DECIDER_API_KEY>).
# Both take the same body and return the same {"answers": ...} shape. Copied from the kit's decider_kit/client.py.
UGMDU_URL = "https://da25tnxy06gjk.cloudfront.net"
DECIDER_MODE = os.environ.get("DECIDER_MODE", "local")
DECIDER_URL = os.environ.get("DECIDER_URL", UGMDU_URL if DECIDER_MODE == "ugmdu" else "http://localhost:8099")
DECIDER_API_KEY = os.environ.get("DECIDER_API_KEY", "")
MODEL = os.environ.get("DECIDER_MODEL", "strands-decider-latest")
MAX_QUESTIONS = int(os.environ.get("DECIDER_MAX_QUESTIONS", "4"))   # hosted tier: 4 questions per request


class Decider:
    def __init__(self, url: str = DECIDER_URL, timeout: float = 30.0, api_key: str = DECIDER_API_KEY):
        self.hosted = DECIDER_MODE == "ugmdu" or bool(api_key)
        self.url = url.rstrip("/") + ("/v1/decide" if self.hosted else "/v1/systemone")
        self.headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = timeout
        self.mock = False
        self.calls: list[dict] = []      # {"n_questions", "server_ms", "wall_ms"} for benchmarks

    def ask(self, state: str, questions: dict[str, Q]) -> dict:
        """Like `_ask_one`, but splits into several requests when the hosted tier caps questions per request."""
        names = list(questions)
        if not self.hosted or len(names) <= MAX_QUESTIONS:
            return self._ask_one(state, questions)
        out: dict = {}
        latency = 0.0
        for i in range(0, len(names), MAX_QUESTIONS):
            part = self._ask_one(state, {n: questions[n] for n in names[i:i + MAX_QUESTIONS]})
            latency += part.pop("_latency_ms") or 0.0
            out.update(part)
        out["_latency_ms"] = latency
        return out

    def _ask_one(self, state: str, questions: dict[str, Q]) -> dict:
        """Ask several questions about one state in a single request.

        Returns {name: {"noul": p}} or {name: {"choice": str, "confidence": p,
        "probs": {...}}}, plus "_latency_ms" (server-side time for the whole call).
        """
        payload = {"state": state, "questions": {}}
        if not self.hosted:
            payload["model"] = MODEL
        for name, q in questions.items():
            spec = {"type": q.kind, "instructions": q.instructions}
            if q.options:
                spec["criteria"] = dict(q.options)
            payload["questions"][name] = spec

        t0 = time.perf_counter()
        resp = requests.post(self.url, json=payload, headers=self.headers, timeout=self.timeout)
        if resp.status_code in (401, 402, 429, 503):
            hint = {401: "check DECIDER_API_KEY", 402: "monthly quota used up",
                    429: "rate limited; retry shortly", 503: "server busy; retry"}[resp.status_code]
            raise RuntimeError(f"decider returned {resp.status_code} ({hint}): {resp.text[:200]}")
        resp.raise_for_status()
        wall_ms = (time.perf_counter() - t0) * 1000
        data = resp.json()

        out = {}
        for name, ans in data["answers"].items():
            if ans["type"] == "noul":
                out[name] = {"noul": float(ans["noul"])}
            else:
                out[name] = {
                    "choice": ans["choice"],
                    "confidence": float(ans.get("confidence", 0.0)),
                    "probs": ans.get("probabilities", {}),
                }
        out["_latency_ms"] = data.get("latency_ms")
        self.calls.append({"n_questions": len(questions),
                           "server_ms": data.get("latency_ms"), "wall_ms": wall_ms})
        return out


def make_decider():
    """Real server unless MOCK=1 (offline heuristics; for UI/dev only, never for benchmarks)."""
    if os.environ.get("MOCK") == "1":
        from mock_decider import MockDecider
        return MockDecider()
    return Decider()
