"""Web UI backend: `python server.py` then open http://localhost:8000.

Every turn returns the full decision trace (intent, heat, stance, confidence,
nerves, model tier, guard verdicts, recalled memories, contradictions, latency)
so the page can show Decider working live. This is the demo-video centrepiece.
"""
import json
import os
import queue
import threading

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from cases import SUSPECTS
from game import Game

app = FastAPI(title="Interrogation Room")
game = Game()


class Line(BaseModel):
    text: str
    suspect: str = "marcus"
    use_decider: bool = True
    force_tool: str | None = None


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "ui", "index.html"))


@app.get("/api/state")
def state():
    return {
        "mock": bool(getattr(game.decider, "mock", False)),
        "suspects": [{"id": s.id, "name": s.name} for s in SUSPECTS.values()],
        "notebook": game.notebook.findings,
    }


@app.post("/api/act")
def act(line: Line):
    turn = game.act(line.text, line.suspect if line.suspect in SUSPECTS else "marcus", line.use_decider, line.force_tool)
    turn["notebook"] = game.notebook.findings
    return turn


@app.post("/api/act_stream")
def act_stream(line: Line):
    """Like /api/act, but streams newline-delimited JSON: {"step": ...} while working, then {"result": ...}."""
    q: queue.Queue = queue.Queue()
    g = game
    suspect = line.suspect if line.suspect in SUSPECTS else "marcus"

    def work():
        g.notify = lambda m: q.put(m if isinstance(m, dict) else {"step": m})
        try:
            if not line.use_decider:
                g.emit("Bedrock: one strong model call does everything (no Decider)")
            turn = g.act(line.text, suspect, line.use_decider, line.force_tool)
            turn["notebook"] = g.notebook.findings
            q.put({"result": turn})
        except Exception as e:  # shown in the UI instead of a silent spinner
            q.put({"error": f"{type(e).__name__}: {e}"})
        finally:
            g.notify = None
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while (item := q.get()) is not None:
            yield json.dumps(item) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/reset")
def reset():
    global game
    game = Game()
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
