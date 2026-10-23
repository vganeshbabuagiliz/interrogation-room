"""Benchmarks. Run against the REAL long-running `strands-decider serve` and real Bedrock.

  python bench.py latency   # Decider warm p50/p95 vs Bedrock for the same decision
  python bench.py routing   # auto routing vs always-strong baseline over scripted turns

Refuses to run in MOCK mode: mock numbers are not measurements.
Costs use the illustrative per-1M-token prices below. They are NOT current AWS prices:
edit PRICES to your region's real rates before quoting any cost figure.
"""
import json
import os
import statistics
import sys
import time

if os.environ.get("MOCK") == "1":
    sys.exit("MOCK=1 is set: refusing to benchmark heuristics. Unset it and start `strands-decider serve`.")

import game as G
from cases import SUSPECTS
from decider_client import Decider
from decisions import INTENT

PRICES = {"fast": (1.00, 5.00), "strong": (3.00, 15.00)}   # ILLUSTRATIVE USD per 1M (in, out) tokens

SCRIPT = [
    "Nice manor. How long have you worked here?",
    "Where were you between 10 and 11 last night?",
    "Who else was in the house that evening?",
    "Tell me about Mr. Ashworth.",
    "The boiler log shows nobody was in that room after 10:30.",
    "You were in the study. You argued about your wages, and you killed him.",
    "Your boots left coal dust on the study carpet. Explain that.",
    "Thank you, that will be all for now.",
]


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def latency(n: int = 50):
    d = Decider()
    state = f"Detective says: {SCRIPT[4]}\nSuspect's secret: {SUSPECTS['marcus'].secret}"
    d.ask(state, {"intent": INTENT})                        # warm-up, discarded
    d.calls.clear()
    for _ in range(n):
        d.ask(state, {"intent": INTENT})
    server = [c["server_ms"] for c in d.calls]
    wall = [c["wall_ms"] for c in d.calls]
    res = {"n": n, "decider_server_ms": {"p50": pct(server, .5), "p95": pct(server, .95)},
           "decider_wall_ms": {"p50": pct(wall, .5), "p95": pct(wall, .95)}}

    # Same decision made by a Bedrock LLM (classification prompt), for comparison.
    try:
        import boto3
        br = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION"))
        prompt = (f"{state}\nClassify the detective's line as one of: {', '.join(INTENT.options)}. "
                  "Answer with the label only.")
        ms = []
        for _ in range(min(n, 20)):
            t0 = time.perf_counter()
            br.converse(modelId=G.FAST_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}],
                        inferenceConfig={"maxTokens": 10, "temperature": 0})
            ms.append((time.perf_counter() - t0) * 1000)
        res["bedrock_fast_model_ms"] = {"model": G.FAST_MODEL, "n": len(ms), "p50": pct(ms, .5), "p95": pct(ms, .95)}
    except Exception as e:                                  # report, never invent
        res["bedrock_fast_model_ms"] = f"not measured: {e}"
    print(json.dumps(res, indent=2))


def run_script(routing: str):
    G.ALWAYS = routing
    g = G.Game()
    rows = []
    for line in SCRIPT:
        t0 = time.perf_counter()
        r = g.take_turn(SUSPECTS["marcus"], line)
        rows.append({"tier": r["tier"], "turn_ms": (time.perf_counter() - t0) * 1000,
                     "bedrock_ms": r["bedrock"]["ms"], "in": r["bedrock"]["in_tokens"],
                     "out": r["bedrock"]["out_tokens"], "escalated": r["escalated"]})
    return rows


def cost(rows, force_tier=None):
    total = 0.0
    for r in rows:
        pin, pout = PRICES[force_tier or r["tier"]]
        total += r["in"] / 1e6 * pin + r["out"] / 1e6 * pout
    return total


def routing():
    auto, strong = run_script("auto"), run_script("strong")
    fast_share = sum(r["tier"] == "fast" for r in auto) / len(auto)
    out = {
        "turns": len(SCRIPT),
        "share_on_fast_model": round(fast_share, 2),
        "escalations": sum(r["escalated"] for r in auto),
        "auto": {"mean_turn_ms": statistics.mean(r["turn_ms"] for r in auto),
                 "mean_bedrock_ms": statistics.mean(r["bedrock_ms"] for r in auto),
                 "est_cost_usd_ILLUSTRATIVE": cost(auto)},
        "always_strong": {"mean_turn_ms": statistics.mean(r["turn_ms"] for r in strong),
                          "mean_bedrock_ms": statistics.mean(r["bedrock_ms"] for r in strong),
                          "est_cost_usd_ILLUSTRATIVE": cost(strong, "strong")},
        "note": "prices in bench.py are illustrative; latency numbers are measured on this run only",
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    {"latency": latency, "routing": routing}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
