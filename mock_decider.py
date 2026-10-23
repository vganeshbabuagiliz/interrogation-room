"""Offline stand-in for Decider so the UI and pipeline can run without a GPU.

Keyword heuristics only. NOT Decider, NOT a measurement: latencies it reports are
fake (0.0) and benchmarks refuse to run against it.
"""
import re

from decisions import Q

_STOP = set("the a an and or of to in at on for with was were is are be been that this it he she they "
            "you your i me my his her their from by as not no do did does what where when why who how "
            "about said say says last night".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9:]+", text.lower()) if w not in _STOP and len(w) > 2}


def _times(text: str) -> set[str]:
    return set(re.findall(r"\d{1,2}(?::\d{2})?\s?(?:am|pm)?", text.lower().replace(" pm", "pm").replace(" am", "am")))


def _line(state: str) -> str:
    m = re.search(r"Detective says: (.*)", state)
    return m.group(1) if m else state


def _secret(state: str) -> str:
    m = re.search(r"Suspect's secret: (.*)", state)
    return m.group(1) if m else ""


def _choice(name, probs):
    best = max(probs, key=probs.get)
    n = len(probs)
    conf = (n * probs[best] - 1) / (n - 1)
    return {"choice": best, "confidence": round(conf, 3), "probs": probs}


def _norm(d):
    s = sum(d.values())
    return {k: v / s for k, v in d.items()}


class MockDecider:
    mock = True

    def __init__(self):
        self.calls = []

    def _intent(self, line: str):
        l = line.lower()
        if re.search(r"log|evidence|found|fingerprint|proves|shows|footage|receipt|contradict", l):
            return _norm({"small_talk": .02, "probe": .08, "accuse": .2, "present_evidence": .7})
        if re.search(r"you (killed|did it|murdered|are lying|lied)|guilty|confess|murder", l):
            return _norm({"small_talk": .02, "probe": .08, "accuse": .8, "present_evidence": .1})
        if "?" in l or re.search(r"\b(where|when|why|who|what|how)\b", l):
            return _norm({"small_talk": .1, "probe": .75, "accuse": .08, "present_evidence": .07})
        return _norm({"small_talk": .8, "probe": .1, "accuse": .05, "present_evidence": .05})

    def _heat(self, line: str, secret: str) -> float:
        overlap = len(_words(line) & _words(secret))
        bump = 0.3 if _times(line) & _times(secret) else 0.0
        return round(min(0.97, 0.05 + 0.2 * overlap + bump), 3)

    def ask(self, state: str, questions: dict[str, Q]) -> dict:
        out = {}
        line, secret = _line(state), _secret(state)
        for name, q in questions.items():
            if name == "intent":
                out[name] = _choice(name, self._intent(line))
            elif name == "heat":
                out[name] = {"noul": self._heat(line, secret)}
            elif name == "needs_frontier":
                heat = self._heat(line, secret)
                intent = max((p := self._intent(line)), key=p.get)
                out[name] = {"noul": 0.85 if intent in ("accuse", "present_evidence") or heat > 0.5 else 0.15}
            elif name == "stance":
                guilty = "Suspect is guilty" in state
                pr = re.search(r"Pressure on suspect: (\w+)", state)
                pr = pr.group(1) if pr else "low"
                table = {
                    "high": {"truthful": .05, "deflect": .2, "lie": .25, "crack": .5} if guilty
                            else {"truthful": .8, "deflect": .1, "lie": .05, "crack": .05},
                    "medium": {"truthful": .1, "deflect": .4, "lie": .45, "crack": .05} if guilty
                              else {"truthful": .7, "deflect": .2, "lie": .05, "crack": .05},
                    "low": {"truthful": .7, "deflect": .15, "lie": .13, "crack": .02},
                }
                out[name] = _choice(name, _norm(table[pr]))
            elif name in ("grounded", "leaks_secret"):
                m = re.search(r"KNOWLEDGE SHEET AND COVER STORY:\n(.*?)\n\nSECRET:\n(.*?)\n\nSTATEMENT:\n(.*)", state, re.S)
                facts, sec, text = m.groups() if m else ("", "", state)
                if name == "grounded":
                    caps = set(re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]+", text))
                    known = (facts + " " + sec).lower()
                    unknown = [c for c in caps if c.lower() not in known]
                    nums = [t for t in _times(text) if t.strip() and t not in _times(facts + " " + sec)]
                    out[name] = {"noul": 0.1 if (unknown or nums) else 0.92}
                else:
                    ov = len(_words(text) & (_words(sec) - _words(facts)))
                    out[name] = {"noul": 0.9 if ov >= 3 else 0.08}
            elif name.startswith("mem_"):
                mem = q.instructions.split("MEMORY:", 1)[-1]
                ov = len(_words(line) & _words(mem))
                out[name] = {"noul": round(min(0.95, 0.1 + 0.3 * ov), 3)}
            elif name.startswith("contra_"):
                mem = q.instructions.split("MEMORY:", 1)[-1]
                shared = len(_words(state) & _words(mem) - _times(state) - _times(mem))
                differ = _times(state) and _times(mem) and not (_times(state) & _times(mem))
                out[name] = {"noul": 0.88 if shared >= 1 and differ else 0.06}
            elif name == "tool":
                l = line.lower()
                probs = {"question_suspect": .1, "examine_evidence": .1, "check_log": .1, "search_room": .1}
                if re.match(r"\s*(check|read|open)\b", l) and re.search(r"log|record|ledger|report", l): probs["check_log"] = .8
                elif re.match(r"\s*(search|look (in|around))\b", l): probs["search_room"] = .8
                elif re.match(r"\s*(examine|inspect|look at)\b", l): probs["examine_evidence"] = .8
                elif re.search(r"\b(you|your|ask|question|talk|interrogate|how long)\b|\?", l): probs["question_suspect"] = .8
                elif len(l.split()) < 3: pass
                else: probs["question_suspect"] = .35; probs["examine_evidence"] = .3
                out[name] = _choice(name, _norm(probs))
            elif name.startswith("target_"):
                l = line.lower()
                probs = {}
                for opt, desc in q.options.items():
                    key = _words(opt.replace("_", " ") + " " + (desc or ""))
                    probs[opt] = 0.05 + len(key & _words(l))
                out[name] = _choice(name, _norm(probs))
            else:
                out[name] = {"noul": 0.5}
        out["_latency_ms"] = 0.0
        self.calls.append({"n_questions": len(questions), "server_ms": 0.0, "wall_ms": 0.0})
        return out
