"""Interrogation Room: the game engine.

Per detective line (all Decider calls hit one long-running `strands-decider serve`):
  0. tool selection: free-form action -> tool (or "did you mean...?")         [Decider]
  1. ONE request: intent + heat + needs_frontier + memory relevance           [Decider]
  2. Code: pressure = f(intent, heat); model tier = f(needs_frontier)
  3. stance (+ confidence)                                                    [Decider]
  4. Code: nervousness = 0.6*heat + 0.4*(1 - stance confidence)
  5. Bedrock (fast or strong tier) writes the line through a `speak` tool
  6. GroundedSpeechGuard gates the line                                       [Decider]
     if the fast model fails the guard repeatedly, escalate once to the strong model
  7. contradiction check of the spoken line against the suspect's memory      [Decider]
"""
import os
import time
from dataclasses import dataclass, field

from cases import CASE, SUSPECTS, Suspect
from decider_client import make_decider
from decisions import HEAT, INTENT, NEEDS_FRONTIER, STANCE
from guards import SAFE_LINE, GroundedSpeechGuard
from memory import SuspectMemory
from tools import Notebook, route_action

FAST_MODEL = os.environ.get("BEDROCK_MODEL_FAST") or os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")        # check your region's ID
STRONG_MODEL = os.environ.get("BEDROCK_MODEL_STRONG", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
FRONTIER_AT = 0.5        # policy knob: needs_frontier >= this -> strong tier
ESCALATE = os.environ.get("ESCALATE_ON_GUARD_FAIL", "1") == "1"
ALWAYS = os.environ.get("ROUTING", "auto")      # auto | fast | strong (benchmark baselines)
MOCK = os.environ.get("MOCK") == "1"


def pressure_label(intent: str, heat: float) -> str:
    base = {"small_talk": 0.0, "probe": 0.3, "accuse": 0.6, "present_evidence": 0.8}[intent]
    p = 0.5 * base + 0.5 * heat
    return "high" if p > 0.6 else "medium" if p > 0.3 else "low"


def nervousness(heat: float, stance_conf: float) -> float:
    """Calibrated confidence as a story signal: unsure stance + hot topic = shaky voice."""
    return round(0.6 * heat + 0.4 * (1.0 - stance_conf), 2)


def nerves_cue(n: float) -> str:
    if n > 0.7:
        return "Visibly rattled: stammer, trailing off, over-explaining."
    if n > 0.4:
        return "Uneasy: pauses, slightly too many details."
    return "Calm and composed."


def tier_for(needs_frontier: float) -> str:
    if ALWAYS in ("fast", "strong"):
        return ALWAYS
    return "strong" if needs_frontier >= FRONTIER_AT else "fast"


def _write_line(model_id: str, suspect: Suspect, stance: str, nerves: float,
                recalled: list[dict], line: str, guard: GroundedSpeechGuard) -> dict:
    """One Bedrock generation through the guarded `speak` tool (or the offline mock)."""
    spoken: list[str] = []
    t0 = time.perf_counter()

    if MOCK:
        # Offline path: same guard, canned line. Not a Bedrock measurement.
        text = suspect.mock_lines[stance]
        v = guard.judge(text)
        spoken.append(text if type(v).__name__ == "Proceed" else SAFE_LINE)
        return {"text": spoken[-1], "ms": 0.0, "in_tokens": 0, "out_tokens": 0}

    from strands import Agent, tool

    @tool
    def speak(text: str) -> str:
        """Say this line aloud to the detective."""
        spoken.append(text)
        return "spoken"

    memory_block = ""
    if recalled:
        memory_block = "Relevant things you remember: " + " | ".join(r["text"] for r in recalled) + "\n"
    agent = Agent(
        model=model_id, tools=[speak], interventions=[guard], callback_handler=None,
        system_prompt=(
            f"You are {suspect.name}, a suspect in an interrogation. {suspect.persona}\n"
            f"Only use facts from this sheet: {suspect.facts}\n{memory_block}"
            f"Your stance this turn: {stance}. Demeanour: {nerves_cue(nerves)}\n"
            "Reply with one or two sentences by calling the speak tool. Never narrate."
        ),
    )
    result = agent(f"The detective says: {line}")
    usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None) or {}
    return {"text": spoken[-1] if spoken else "...", "ms": (time.perf_counter() - t0) * 1000,
            "in_tokens": usage.get("inputTokens", 0), "out_tokens": usage.get("outputTokens", 0)}


@dataclass
class Game:
    decider: object = field(default_factory=make_decider)
    memories: dict = field(default_factory=dict)
    notebook: Notebook = field(default_factory=Notebook)
    history: list = field(default_factory=list)
    notify: object = None          # optional callable(str): live progress steps for the UI

    def emit(self, msg: str):
        if self.notify:
            self.notify(msg)

    def __post_init__(self):
        for s in SUSPECTS.values():
            m = SuspectMemory()
            for t in s.seed_memories:
                m.add(t, "said")
            self.memories[s.id] = m

    # ---- one detective line -------------------------------------------------
    def act(self, text: str, suspect_id: str, use_decider: bool = True, force_tool: str | None = None) -> dict:
        """Entry point: route the free-form line, then run the matching tool."""
        if not use_decider:
            turn = {"input": text, "route": {"tool": None}, **self.baseline_turn(SUSPECTS[suspect_id], text)}
            self.history.append(turn)
            return turn
        if force_tool == "question_suspect":   # a follow-up button or the Sergeant's option: no routing needed
            turn = {"input": text, "route": {"tool": "question_suspect", "confidence": 1.0}}
            turn.update(self.take_turn(SUSPECTS[suspect_id], text))
            self.history.append(turn)
            return turn
        self.emit("Decider: working out what the detective is doing (question, evidence, log or room)")
        r = route_action(self.decider, SUSPECTS, text, force_tool)
        self.emit(f"Decider: routed to {r['tool'] or 'unclear'}"
                  + (f" ({r['confidence']:.0%})" if r.get("confidence") is not None else ""))
        turn = {"input": text, "route": {k: r.get(k) for k in
                ("tool", "confidence", "probs", "target", "clarify", "latency_ms")}}
        if r.get("clarify"):
            turn["narration"] = r["clarify"]
            labels = {"examine_evidence": "Examine evidence", "check_log": "Check a log", "search_room": "Search a room"}
            turn["options"] = [{"label": f"Say it to {SUSPECTS[suspect_id].name}", "tool": "question_suspect"}] + \
                [{"label": labels[t], "tool": t} for t in r["options"] if t in labels]
        elif r["tool"] == "question_suspect":
            who = suspect_id if force_tool or r["suspect_confidence"] < 0.5 else r["suspect"]
            turn.update(self.take_turn(SUSPECTS[who], text))
        else:
            new = self.notebook.add(r["kind"], r["target"], r["finding"], r["finding_suspect"])
            turn["narration"] = r["finding"]
            turn["new_clue"] = new
            if new:
                for m in self.memories.values():      # suspects learn what the detective knows
                    m.add("The detective found: " + r["finding"], "clue")
        self.history.append(turn)
        return turn

    def followups(self, suspect: Suspect, reply: str) -> list[dict]:
        """Cross-questions to offer after a reply: no extra model calls, built from the case file and the notebook."""
        asked = {h.get("input") for h in self.history}
        first = suspect.name.split()[0]
        out = []
        for label, text in suspect.followups:
            if text not in asked:
                out.append({"label": label, "text": text, "suspect": suspect.id})
            if len(out) == 2:
                break
        for f in self.notebook.findings:
            text = f"{first}, we found this: {f['finding']} Explain it."
            if f["suspect"] == suspect.id and text not in asked:
                out.append({"label": "Confront: " + f["key"].replace("_", " "), "text": text, "suspect": suspect.id})
                break
        snippet = reply if len(reply) <= 110 else reply[:107].rstrip() + "..."
        for other in [o for o in SUSPECTS.values() if o.id != suspect.id][:2]:
            out.append({"label": f"Ask {other.name} about this", "suspect": other.id,
                        "text": f'{other.name.split()[0]}, {suspect.name} told me: "{snippet}" Is that true?'})
        return out

    def baseline_turn(self, suspect: Suspect, line: str) -> dict:
        """Comparison mode: one LLM call does everything. No Decider, no guard, no memory, no routing."""
        t0 = time.perf_counter()
        if MOCK:
            text, in_t, out_t = suspect.mock_lines["lie"], 0, 0
        else:
            from strands import Agent
            agent = Agent(model=STRONG_MODEL, callback_handler=None, system_prompt=(
                f"You are {suspect.name}, a suspect in an interrogation. {suspect.persona}\n"
                f"Your knowledge and cover story: {suspect.facts}\n"
                f"Your secret (hide it unless truly cornered): {suspect.secret}\n"
                "Reply in one or two sentences, in character. Never narrate."))
            result = agent(f"The detective says: {line}")
            text = str(result).strip()
            usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None) or {}
            in_t, out_t = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
        return {"suspect": suspect.id, "suspect_name": suspect.name, "reply": text, "baseline": True,
                "model": STRONG_MODEL, "tier": "strong (no routing)", "guard_trace": [], "recalled": [], "slips": [],
                "bedrock": {"ms": (time.perf_counter() - t0) * 1000, "in_tokens": in_t, "out_tokens": out_t}}

    def take_turn(self, suspect: Suspect, line: str) -> dict:
        mem = self.memories[suspect.id]

        self.emit(f"Decider: reading {suspect.name}'s state (intent, heat, model tier, relevant memories)")
        # 1. intent + heat + routing + memory relevance: one request, state encoded once
        qs = {"intent": INTENT, "heat": HEAT, "needs_frontier": NEEDS_FRONTIER,
              **mem.relevance_questions()}
        a = self.decider.ask(
            f"Detective says: {line}\nSuspect's secret: {suspect.secret}", qs)
        intent, heat = a["intent"]["choice"], a["heat"]["noul"]
        pressure = pressure_label(intent, heat)
        tier = tier_for(a["needs_frontier"]["noul"])
        recalled = mem.pick(a)
        self.emit(f"Decider: intent {intent}, heat {heat:.0%}, tier {tier}, {len(recalled)} memories recalled")
        self.emit("Decider: choosing the suspect's stance")

        # 3. stance
        s = self.decider.ask(
            f"Suspect is {'guilty' if suspect.guilty else 'innocent'}. "
            f"Detective intent: {intent}. Pressure on suspect: {pressure}.\n"
            f"Detective says: {line}",
            {"stance": STANCE},
        )
        stance, conf = s["stance"]["choice"], s["stance"]["confidence"]
        nerves = nervousness(heat, conf)
        self.emit(f"Decider: stance {stance} ({conf:.0%}), nervousness {nerves:.0%}")

        # 5/6. Bedrock speaks through a guarded tool; escalate once if the fast tier keeps failing
        escalated = False
        model_id = STRONG_MODEL if tier == "strong" else FAST_MODEL
        guard = GroundedSpeechGuard(self.decider, suspect.facts, suspect.secret,
                                    allow_secret_leak=(stance == "crack"))
        guard.notify = self.emit
        self.emit(f"Bedrock: {suspect.name} is writing a reply ({tier} model)")
        out = _write_line(model_id, suspect, stance, nerves, recalled, line, guard)
        if ESCALATE and tier == "fast" and guard.exhausted:
            escalated, tier, model_id = True, "strong", STRONG_MODEL
            guard = GroundedSpeechGuard(self.decider, suspect.facts, suspect.secret,
                                        allow_secret_leak=(stance == "crack"))
            guard.notify = self.emit
            self.emit("Bedrock: fast model kept failing the guard, escalating to the strong model")
            out2 = _write_line(model_id, suspect, stance, nerves, recalled, line, guard)
            out = {**out2, "ms": out["ms"] + out2["ms"],
                   "in_tokens": out["in_tokens"] + out2["in_tokens"],
                   "out_tokens": out["out_tokens"] + out2["out_tokens"]}

        self.emit({"reply": {"suspect": suspect.id, "suspect_name": suspect.name, "reply": out["text"],
                             "stance": stance, "nervousness": nerves}})
        # 7. consistency: does the new line contradict what this suspect said/learned before?
        self.emit("Decider: checking the reply against what they said before")
        slips = mem.contradictions(self.decider, out["text"])
        mem.add(f"I said to the detective: {out['text']}", "said")
        for other_id, other in self.memories.items():      # gossip: other suspects "hear" it
            if other_id != suspect.id:
                other.add(f"{suspect.name} told the detective: {out['text']}", "heard")

        return {
            "suspect": suspect.id, "suspect_name": suspect.name, "reply": out["text"],
            "intent": intent, "heat": heat, "pressure": pressure,
            "stance": stance, "stance_confidence": conf, "nervousness": nerves,
            "needs_frontier": a["needs_frontier"]["noul"], "tier": tier, "model": model_id,
            "escalated": escalated, "recalled": recalled, "slips": slips,
            "guard_trace": guard.trace, "followups": self.followups(suspect, out["text"]),
            "bedrock": {k: out[k] for k in ("ms", "in_tokens", "out_tokens")},
        }


if __name__ == "__main__":
    g = Game()
    m = SUSPECTS["marcus"]
    for q in ["Nice manor. How long have you worked here?",
              "Where were you between 10 and 11 last night?",
              "The boiler log shows nobody was in that room after 10:30."]:
        r = g.take_turn(m, q)
        print(f"\nDETECTIVE: {q}\n{m.name}: {r['reply']}")
        print(f"  [{r['intent']} | heat {r['heat']:.2f} | {r['stance']} "
              f"@{r['stance_confidence']:.2f} | nerves {r['nervousness']} | {r['tier']}]")
