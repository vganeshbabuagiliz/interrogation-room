"""Web UI backend: `python server.py` then open http://localhost:8000.

Every turn returns the full decision trace (intent, heat, stance, confidence,
nerves, model tier, guard verdicts, recalled memories, contradictions, latency)
so the page can show Decider working live.

Sharing it publicly (all optional, set in .env or the environment):
  ACCESS_CODE        if set, every request needs HTTP Basic auth with this as the password (any username)
  MAX_TURNS_PER_HOUR per visitor (default 40);  MAX_TURNS_PER_DAY across everyone (default 400)
  MAX_CONCURRENT     turns running at once (default 3)
Each visitor gets their own game (cookie `sid`), so suspects' memories do not mix.
"""
import base64
import hashlib
import hmac
import json
import os
import queue
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque

import uvicorn
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

import decider_client  # noqa: F401  (loads .env before the settings below are read)
from cases import SUSPECTS
from game import Game

ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
MAX_PER_HOUR = int(os.environ.get("MAX_TURNS_PER_HOUR", "40"))
MAX_PER_DAY = int(os.environ.get("MAX_TURNS_PER_DAY", "400"))
MAX_SESSIONS = 100
busy = threading.BoundedSemaphore(int(os.environ.get("MAX_CONCURRENT", "3")))

app = FastAPI(title="Interrogation Room")
sessions: "OrderedDict[str, Game]" = OrderedDict()
turn_log: dict[str, deque] = defaultdict(deque)     # sid -> timestamps of recent turns
day_log: deque = deque()                            # timestamps of every turn in the last 24 h
lock = threading.Lock()


class Line(BaseModel):
    text: str
    suspect: str = "marcus"
    use_decider: bool = True
    force_tool: str | None = None


def _game(sid: str) -> Game:
    with lock:
        if sid not in sessions:
            sessions[sid] = Game()
            while len(sessions) > MAX_SESSIONS:
                sessions.popitem(last=False)
        sessions.move_to_end(sid)
        return sessions[sid]


def _allowed(sid: str) -> str | None:
    """None if this visitor may start a turn now, else the reason (a message for the UI)."""
    now = time.time()
    with lock:
        mine = turn_log[sid]
        while mine and now - mine[0] > 3600:
            mine.popleft()
        while day_log and now - day_log[0] > 86400:
            day_log.popleft()
        if len(mine) >= MAX_PER_HOUR:
            return f"Turn limit reached ({MAX_PER_HOUR} an hour per visitor). Please try again later."
        if len(day_log) >= MAX_PER_DAY:
            return "The demo has reached its daily turn limit. Please try again tomorrow."
        mine.append(now)
        day_log.append(now)
    return None


def _token() -> str:
    return hmac.new(ACCESS_CODE.encode(), b"interrogation-room-login", hashlib.sha256).hexdigest()


LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Interrogation Room: access code</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0e1013;color:#e9e7e2;font:15px/1.5 system-ui,sans-serif}
form{width:min(360px,88vw);padding:28px;background:#15181d;border:1px solid #2a2f37;border-radius:12px}
h1{margin:0 0 4px;font:700 22px Georgia,serif}p{margin:0 0 16px;color:#8e949e;font-size:13px}
input{width:100%;box-sizing:border-box;height:42px;padding:0 12px;border-radius:8px;border:1px solid #2a2f37;background:#1c2026;color:inherit;font:inherit}
input:focus{outline:1px solid #e0a63a;border-color:#e0a63a}
button{margin-top:12px;width:100%;height:42px;border:0;border-radius:8px;background:#e0a63a;color:#14161a;font-weight:700;font-size:15px;cursor:pointer}
.err{color:#e5584b;font-size:13px;margin:10px 0 0}
</style></head><body><form method="post" action="/login"><h1>Interrogation Room</h1>
<p>Enter the access code from the submission notes to start the demo.</p>
<input name="code" type="password" placeholder="Access code" autocomplete="off" autofocus required>
<button>Enter</button>__ERR__</form></body></html>"""


def _json_line(payload: dict, status: int) -> Response:
    return Response(json.dumps(payload) + "\n", status_code=status, media_type="application/x-ndjson")


@app.middleware("http")
async def guard(request: Request, call_next):
    if ACCESS_CODE and request.url.path != "/login":
        ok = hmac.compare_digest(request.cookies.get("ac", ""), _token())
        header = request.headers.get("authorization", "")
        if not ok and header.lower().startswith("basic "):
            try:
                given = base64.b64decode(header[6:]).decode().partition(":")[2]
                ok = hmac.compare_digest(given, ACCESS_CODE)
            except Exception:
                ok = False
        if not ok:
            if request.method == "GET" and request.url.path == "/":
                return HTMLResponse(LOGIN_PAGE.replace("__ERR__", ""), status_code=401)
            return Response(json.dumps({"error": "Access code required. Reload the page and enter it."}) + "\n",
                            status_code=401, media_type="application/x-ndjson")
    sid = request.cookies.get("sid") or secrets.token_urlsafe(16)
    request.state.sid = sid
    response = await call_next(request)
    if request.cookies.get("sid") != sid:
        response.set_cookie("sid", sid, httponly=True, samesite="lax", max_age=7 * 86400)
    return response


@app.post("/login")
async def login(request: Request):
    code = parse_qs((await request.body()).decode()).get("code", [""])[0].strip()
    if ACCESS_CODE and hmac.compare_digest(code, ACCESS_CODE):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("ac", _token(), httponly=True, samesite="lax", max_age=7 * 86400)
        return resp
    return HTMLResponse(LOGIN_PAGE.replace("__ERR__", '<div class="err">That code is not right.</div>'), status_code=401)


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "ui", "index.html"))


@app.get("/api/state")
def state(request: Request):
    game = _game(request.state.sid)
    return {
        "mock": bool(getattr(game.decider, "mock", False)),
        "suspects": [{"id": s.id, "name": s.name} for s in SUSPECTS.values()],
        "notebook": game.notebook.findings,
    }


@app.post("/api/act")
def act(line: Line, request: Request):
    why = _allowed(request.state.sid)
    if why:
        return Response(json.dumps({"error": why}), status_code=429, media_type="application/json")
    game = _game(request.state.sid)
    turn = game.act(line.text, line.suspect if line.suspect in SUSPECTS else "marcus", line.use_decider, line.force_tool)
    turn["notebook"] = game.notebook.findings
    return turn


@app.post("/api/act_stream")
def act_stream(line: Line, request: Request):
    """Like /api/act, but streams newline-delimited JSON: {"step": ...} while working, then {"result": ...}."""
    why = _allowed(request.state.sid)
    if why:
        return _json_line({"error": why}, 429)
    if not busy.acquire(blocking=False):
        return _json_line({"error": "The demo is busy with other visitors. Please try again in a moment."}, 503)
    q: queue.Queue = queue.Queue()
    g = _game(request.state.sid)
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
            busy.release()
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while (item := q.get()) is not None:
            yield json.dumps(item) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/reset")
def reset(request: Request):
    with lock:
        sessions[request.state.sid] = Game()
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
