"""Tool selection: Decider routes the detective's free-form action to a tool.

Pattern: a typed `choice` over the tools, plus a typed `choice` over each tool's
targets, in ONE request (same state). If the tool confidence is below
CONFIDENT, nothing runs; the sergeant asks "Did you mean X or Y?" instead of
guessing. The tools themselves are plain functions over the case file.
"""
from cases import CASE
from decisions import TOOL_PICK, target_q

CONFIDENT = 0.5      # policy knob owned by code
TARGET_KIND = {"examine_evidence": "evidence", "check_log": "logs", "search_room": "rooms"}
LABEL = {"question_suspect": "question a suspect", "examine_evidence": "examine evidence",
         "check_log": "check a log", "search_room": "search a room"}


class Notebook:
    def __init__(self):
        self.findings: list[dict] = []

    def add(self, kind: str, key: str, finding: str, suspect: str | None) -> bool:
        if any(f["key"] == key for f in self.findings):
            return False
        self.findings.append({"kind": kind, "key": key, "finding": finding, "suspect": suspect})
        return True


def route_action(decider, suspects: dict, text: str, force: str | None = None) -> dict:
    """Return {"tool", "confidence", "target", "clarify"?, "result"?, "finding"?}."""
    qs = {"tool": TOOL_PICK,
          "target_suspect": target_q("suspect", {s.id: s.name for s in suspects.values()})}
    for tool, kind in TARGET_KIND.items():
        qs[f"target_{kind}"] = target_q(kind, {k: v[0] for k, v in CASE[kind].items()})
    a = decider.ask(f"Detective says: {text}", qs)

    tool, conf = a["tool"]["choice"], a["tool"]["confidence"]
    if force:                      # the player picked from the Sergeant's options
        tool, conf = force, 1.0
    out = {"tool": tool, "confidence": conf, "latency_ms": a.get("_latency_ms"),
           "probs": a["tool"]["probs"], "suspect": a["target_suspect"]["choice"],
           "suspect_confidence": a["target_suspect"]["confidence"]}

    if conf < CONFIDENT:
        top2 = sorted(out["probs"], key=out["probs"].get, reverse=True)[:2]
        out["options"] = top2
        out["clarify"] = (f"Sergeant: \"Did you mean to {LABEL[top2[0]]} or {LABEL[top2[1]]}, "
                          f"Detective?\"")
        out["tool"] = None
        return out

    if tool in TARGET_KIND:
        kind = TARGET_KIND[tool]
        key = a[f"target_{kind}"]["choice"]
        desc, finding, suspect = CASE[kind][key]
        out.update(target=key, target_confidence=a[f"target_{kind}"]["confidence"],
                   kind=kind, finding=finding, finding_suspect=suspect)
    return out
