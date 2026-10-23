"""Memory relevance scorer: the second reusable Decider recipe.

Pattern: keep a list of short memory chunks. Each turn, ask Decider one noul
question per chunk ("is this relevant to the user's line?"), batched into the
same request as the other per-turn questions, then put only the relevant chunks
in the LLM prompt. A second batch asks whether a NEW statement contradicts any
earlier one, which keeps a character consistent (or lets the player catch a lie).

Caps: MAX_CHUNKS per call (Decider's window is 4K tokens), chunks truncated.
"""
from dataclasses import dataclass, field

from decisions import Q, contradiction_q, memory_relevance_q

MAX_CHUNKS = 8
CHUNK_CHARS = 160
RELEVANT = 0.5       # policy knobs owned by code
CONTRADICTS = 0.6
TOP_K = 3


@dataclass
class Chunk:
    text: str
    kind: str          # "said" | "clue" | "heard"


@dataclass
class SuspectMemory:
    chunks: list[Chunk] = field(default_factory=list)

    def add(self, text: str, kind: str):
        self.chunks.append(Chunk(text[:CHUNK_CHARS], kind))

    def window(self) -> list[tuple[int, Chunk]]:
        """The (at most MAX_CHUNKS) most recent chunks, with stable indexes."""
        start = max(0, len(self.chunks) - MAX_CHUNKS)
        return list(enumerate(self.chunks))[start:]

    # ---- relevance: questions are merged into the caller's Decider request ----
    def relevance_questions(self) -> dict[str, Q]:
        return {f"mem_{i}": memory_relevance_q(c.text) for i, c in self.window()}

    def pick(self, answers: dict) -> list[dict]:
        scored = []
        for i, c in self.window():
            a = answers.get(f"mem_{i}")
            if a is not None:
                scored.append({"text": c.text, "kind": c.kind, "p": a["noul"]})
        keep = sorted((s for s in scored if s["p"] >= RELEVANT), key=lambda s: -s["p"])
        return keep[:TOP_K]

    # ---- contradiction check ------------------------------------------------
    def contradiction_questions(self) -> dict[str, Q]:
        return {f"contra_{i}": contradiction_q(c.text)
                for i, c in self.window() if c.kind in ("said", "clue")}

    def contradictions(self, decider, statement: str) -> list[dict]:
        qs = self.contradiction_questions()
        if not qs:
            return []
        ans = decider.ask(f"Detective says: (n/a)\nSTATEMENT: {statement}", qs)
        hits = []
        for i, c in self.window():
            a = ans.get(f"contra_{i}")
            if a and a["noul"] >= CONTRADICTS:
                hits.append({"memory": c.text, "p": a["noul"]})
        return sorted(hits, key=lambda h: -h["p"])
