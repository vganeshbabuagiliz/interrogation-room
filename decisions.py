"""Typed Decider 2B questions for Interrogation Room.

Each question is plain data (kind + instructions + options) so the same
definitions work with the HTTP adapter in decider_client.py or can be
translated to Decider.noul(...) / Decider.choice(...) if you prefer the SDK.

Kinds:
  noul   -> yes/no, returns P(yes) in 0..1
  choice -> one of N options, returns the winner + per-option probabilities
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Q:
    kind: str                      # "noul" | "choice"
    instructions: str              # the typed question
    options: dict = field(default_factory=dict)  # choice: option -> description; noul: true/false -> description
    # (sent to the server as `criteria`)


# ---- Decision 1: what is the detective doing? (Policy pattern) -------------
INTENT = Q(
    "choice",
    "What is the detective doing with this line?",
    {
        "small_talk": "chatting or building rapport, nothing about the case",
        "probe": "asking an open question about whereabouts, motives or relationships",
        "accuse": "directly accusing the suspect of involvement in the crime",
        "present_evidence": "confronting the suspect with a specific clue or contradiction",
    },
)

# ---- Decision 2: how close is the detective to the secret? -----------------
HEAT = Q(
    "noul",
    "Does the detective's line come close to the secret this suspect is hiding?",
    {
        "true": "the line touches the suspect's secret, alibi gap or lie",
        "false": "the line is unrelated to anything the suspect is hiding",
    },
)

# ---- Decision 3: how does the suspect answer? (the in-character choice) ----
STANCE = Q(
    "choice",
    "How should this suspect respond right now?",
    {
        "truthful": "answer honestly; nothing to hide here",
        "deflect": "dodge, change the subject or answer a different question",
        "lie": "repeat the suspect's prepared cover story",
        "crack": "pressure is too high; let part of the truth slip",
    },
)

# ---- Guard questions: run before the suspect's line is spoken --------------
GROUNDED = Q(
    "noul",
    "Is every factual claim in the statement found in the character's knowledge sheet or cover story?",
    {
        "true": "every claim traces back to the sheet or the prepared cover story",
        "false": "the statement invents a name, place, time or event that is not on the sheet",
    },
)

LEAKS_SECRET = Q(
    "noul",
    "Does the STATEMENT admit or describe the specific event in the SECRET (the same action, place and time)? "
    "A cover story that denies it, or a vague line, does not count.",
    {
        "true": "the statement admits or describes the secret event itself",
        "false": "the statement does not mention the secret event; it denies it, repeats the cover story, or is unrelated",
    },
)


# ---- Model routing: does this reply deserve the expensive model? -----------
NEEDS_FRONTIER = Q(
    "noul",
    "Does the suspect's reply need a rich, emotionally nuanced performance "
    "(a confrontation, a breakdown, a high-stakes moment)?",
    {
        "true": "confrontation, accusation, cracking under pressure, or a pivotal revelation",
        "false": "routine small talk or a simple factual answer",
    },
)


# ---- Context and memory: per-chunk questions are built dynamically ---------
def memory_relevance_q(chunk: str) -> Q:
    """One noul per memory chunk. Keep chunks short: Decider has a 4K window."""
    return Q(
        "noul",
        f"Is this memory relevant to what the detective just said?\nMEMORY: {chunk}",
        {"true": "the memory bears on the detective's line",
         "false": "the memory is unrelated to the detective's line"},
    )


def contradiction_q(chunk: str) -> Q:
    """Asked about the suspect's NEW statement (the state) against one old memory."""
    return Q(
        "noul",
        f"Does the statement contradict this earlier memory?\nMEMORY: {chunk}",
        {"true": "the statement and the memory cannot both be true",
         "false": "the statement is consistent with the memory or unrelated to it"},
    )


# ---- Tool selection: free-form detective action -> tool --------------------
TOOL_PICK = Q(
    "choice",
    "Which investigative action is the detective asking for?",
    {
        "question_suspect": "talk to or interrogate a suspect",
        "examine_evidence": "inspect a physical item or piece of evidence",
        "check_log": "read a log, record or document",
        "search_room": "search a room or location",
    },
)


def target_q(kind: str, targets: dict[str, str]) -> Q:
    """Choice over the concrete targets of one tool (suspects, items, logs, rooms)."""
    return Q("choice", f"Which {kind} does the detective mean?", dict(targets))
