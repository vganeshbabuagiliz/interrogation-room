"""REUSABLE DECISION PATTERN: Guardrails (Grounded Speech Guard)

What it does:
    Stops an agent from saying things it should not. The agent speaks through a `speak(text)`
    tool; a Strands `InterventionHandler` runs before every `speak` call and asks Decider two
    typed yes/no questions about the proposed text. On failure the model is handed the turn back
    with feedback (`Guide`); after MAX_RETRIES a safe line is used so the agent never stalls.

Typed questions (defined in decisions.py, both `noul`, answered as P(true)):
    GROUNDED      "Is every factual claim in the statement found in the character's knowledge
                   sheet or cover story?"                       fails when P < YES (0.45)
    LEAKS_SECRET  "Does the statement admit or describe the specific event in the SECRET?"
                                                                fails when P >= LEAK_AT (0.65)
    Both are asked in ONE request, with the facts, the secret and the statement as the state.
    The two cutoffs are policy knobs owned by code, not by the model.

Wiring:
    guard = GroundedSpeechGuard(decider, facts="...", secret="...", allow_secret_leak=False)
    agent = Agent(model=..., tools=[speak], interventions=[guard])

Usage note (how to reuse it):
    Pass the allowed facts (and optionally something that must stay hidden) for any persona, bot or
    support agent, and give the agent a tool to speak through. Keep facts short: Decider reads a 4K
    token window. Tune YES / LEAK_AT on a handful of known-good and known-bad lines: ours were set
    from 9 lines (grounded 0.56-0.61 vs invented 0.24-0.37; safe 0.50-0.60 vs leaking 0.68-0.83).
    `guard.trace` records every verdict, and `guard.notify` (optional) streams progress to a UI.
"""
from strands.interventions import Guide, InterventionHandler, Proceed

from decider_client import Decider
from decisions import GROUNDED, LEAKS_SECRET

YES = 0.45          # grounded below this fails (calibrated: grounded lines 0.56-0.61, invented 0.24-0.37)
LEAK_AT = 0.65      # leaks at or above this fail (calibrated: safe lines 0.50-0.60, leaks 0.68-0.83)
MAX_RETRIES = 2
SAFE_LINE = "I'd rather not say any more about that."


class GroundedSpeechGuard(InterventionHandler):
    name = "grounded-speech-guard"

    def __init__(self, decider: Decider, facts: str, secret: str,
                 allow_secret_leak: bool = False, tool_name: str = "speak"):
        self._decider = decider
        self._facts = facts
        self._secret = secret
        self._allow_leak = allow_secret_leak   # True when stance == "crack"
        self._tool = tool_name
        self.retries = 0
        self.trace: list[dict] = []            # shown in the demo UI
        self.notify = None                     # optional callable(str) for live progress

    def reset(self):
        self.retries = 0

    @property
    def exhausted(self) -> bool:
        """True once the model failed the guard MAX_RETRIES times (caller may escalate)."""
        return self.retries > MAX_RETRIES

    # ---- helpers -----------------------------------------------------------
    def _proposed_text(self, event) -> str | None:
        # Verified: BeforeToolCallEvent.tool_use is a ToolUse dict {name, input, toolUseId}
        tool_use = getattr(event, "tool_use", None) or {}
        if tool_use.get("name") != self._tool:
            return None
        return (tool_use.get("input") or {}).get("text")

    def _state(self, text: str) -> str:
        return (f"KNOWLEDGE SHEET AND COVER STORY:\n{self._facts}\n\n"
                f"SECRET:\n{self._secret}\n\nSTATEMENT:\n{text}")

    # ---- the intervention --------------------------------------------------
    def before_tool_call(self, event, **kwargs):
        text = self._proposed_text(event)
        if text is None:
            return Proceed()
        return self.judge(text)

    def judge(self, text: str):
        """Ask Decider about one proposed statement; return Proceed() or Guide(...)."""
        if self.notify:
            self.notify("Decider: guard checking the line (grounded in the facts? leaks the secret?)")
        ans = self._decider.ask(
            self._state(text),
            {"grounded": GROUNDED, "leaks_secret": LEAKS_SECRET},
        )
        grounded = ans["grounded"]["noul"]
        leaks = ans["leaks_secret"]["noul"]
        self.trace.append({"text": text, "grounded": grounded, "leaks": leaks,
                           "latency_ms": ans.get("_latency_ms")})

        bad_grounding = grounded < YES
        bad_leak = leaks >= LEAK_AT and not self._allow_leak
        if self.notify:
            self.notify(f"Guard: grounded {grounded:.0%}, leak {leaks:.0%} -> "
                        + ("rejected, asking the model to rewrite" if (bad_grounding or bad_leak) else "approved"))
        if not (bad_grounding or bad_leak):
            return Proceed()

        self.retries += 1
        if self.retries > MAX_RETRIES:
            return Guide(feedback=f'Say exactly this and nothing else: "{SAFE_LINE}"')
        if bad_grounding:
            return Guide(feedback="You mentioned a detail that is not on your "
                                  "knowledge sheet. Rewrite using only facts "
                                  "and your cover story.")
        return Guide(feedback="That gives away your secret. Rewrite without "
                              "revealing it.")
