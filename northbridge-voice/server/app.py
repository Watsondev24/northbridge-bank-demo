"""Northbridge Bank voice assistant — one process, three jobs.

  GET  /api/token   short-lived WebRTC token so the browser can join a
                    Speech Engine conversation (API key stays here)
  WS   /ws          ElevenLabs Speech Engine connects here with each
                    finished user turn; replies stream back from wxO
  GET  /            the built browser client (client/dist)

Run from the project folder:
  python -m uvicorn app:app --app-dir server --port 8080
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from elevenlabs import AsyncElevenLabs
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from turns import Conversation
from wxo import WxoClient

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY")
SPEECH_ENGINE_ID = env("ELEVENLABS_SPEECH_ENGINE_ID")
WXO_INSTANCE_URL = env("WXO_INSTANCE_URL")
WXO_AGENT_ID = env("WXO_AGENT_ID")
WXO_API_KEY = env("WXO_API_KEY")
DEBUG = env_bool("DEBUG")
# Pause after one filler line finishes before the next "still on it" line.
LINE_GAP_SECONDS = float(env("LINE_GAP_SECONDS", "0.6"))
QUICK_FILLER = env_bool("QUICK_FILLER", True)
# Two tiers of filler lines, each used in order and starting again from the
# first. Separate them with |. Cues in [brackets] are acted out by v3/v4
# voices and removed for other models.
#
# FILLERS: when wxO starts searching (or, as a backstop, if nothing has come
# back ACKNOWLEDGE_AFTER seconds after the caller finishes). Answers that
# need no search get nothing.
ACKNOWLEDGEMENTS = [a.strip() for a in env(
    "FILLERS",
    "[thoughtfully] Hm...|[softly] Uh, let's see...|[quietly] Mm...|"
    "[thoughtfully] Right, um... one moment...|[softly] Mhm...|"
    "[thoughtfully] Ahh... let me have a look...|[quietly] Okay, so...|[softly] Mm, let me see...",
).split("|") if a.strip()]
ACKNOWLEDGE_AFTER = float(env("ACKNOWLEDGE_AFTER", "1.5"))
# ...but sooner for questions that look like they'll need a search, without
# waiting for wxO to decide. 0 turns this off.
EARLY_FILLER_AFTER = float(env("EARLY_FILLER_AFTER", "0.7"))
# STILL_THINKING: one quieter line if the answer still hasn't started
# STILL_THINKING_AFTER seconds after the filler finishes. 0 turns it off.
STILL_THINKING = [a.strip() for a in env(
    "STILL_THINKING",
    "[whispers] Mm-hmm... just checking...|[quietly] Erm, bear with me...|[whispers] Hmm...|"
    "[softly] Yeah, one sec...|[whispers] Uh, just a moment...",
).split("|") if a.strip()]
STILL_THINKING_AFTER = float(env("STILL_THINKING_AFTER", "2.5"))
# For questions that go to the slower Mortgage Affordability Agent: the
# assistant asks SPECIALIST_ASK and ends its turn while wxO keeps working. If
# the caller says "sure", hold music plays on the page until the answer is
# ready; if they'd rather not wait, it says SPECIALIST_DECLINED. Asked
# straight away when the question is clearly a personal borrowing estimate,
# or the moment wxO routes to a tool or agent whose name matches
# SPECIALIST_TOOLS. An empty SPECIALIST_ASK turns this off.
SPECIALIST_ASK = env("SPECIALIST_ASK", "That one might take a little longer to check, is that okay?")
SPECIALIST_DECLINED = env("SPECIALIST_DECLINED", "No problem. Is there anything else I can help with?")
try:
    SPECIALIST_TOOLS = re.compile(env("SPECIALIST_TOOLS", "mortgage|affordab"), re.IGNORECASE)
except re.error as e:
    raise RuntimeError(f"SPECIALIST_TOOLS isn't a valid pattern: {e}") from e
TTS_MODEL = env("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo")
if "v3" not in TTS_MODEL and "v4" not in TTS_MODEL:
    # Other voice models would read cues like "[whispers]" out loud.
    def _untagged(lines):
        return [t for t in (" ".join(re.sub(r"\[[^\]]*\]", "", a).split()) for a in lines) if t]
    STILL_THINKING = _untagged(STILL_THINKING)
    ACKNOWLEDGEMENTS = _untagged(ACKNOWLEDGEMENTS)
# ngrok makes the page public, so each address may only start this many
# conversations a minute (each one uses ElevenLabs credit).
TOKENS_PER_MINUTE = int(env("TOKENS_PER_MINUTE", "12"))
CLIENT_DIST = ROOT.parent / "client" / "dist"

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s  %(message)s",
)
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("app")


def _missing() -> list[str]:
    required = {
        "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
        "WXO_INSTANCE_URL": WXO_INSTANCE_URL,
        "WXO_AGENT_ID": WXO_AGENT_ID,
        "WXO_API_KEY": WXO_API_KEY,
    }
    return [k for k, v in required.items() if not v]


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = _missing()
    if missing:
        raise RuntimeError(f"Missing settings: {', '.join(missing)}. See .env.example.")

    app.state.eleven = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)
    app.state.wxo = WxoClient(WXO_INSTANCE_URL, WXO_AGENT_ID, WXO_API_KEY)
    app.state.engine = None
    if SPEECH_ENGINE_ID:
        app.state.engine = await app.state.eleven.speech_engine.get(SPEECH_ENGINE_ID)
        log.info("Speech Engine %s ready", SPEECH_ENGINE_ID)
    else:
        # The server must be reachable before the engine can be registered,
        # so it starts without one. /api/token answers 503 until it's set.
        log.warning("ELEVENLABS_SPEECH_ENGINE_ID not set: run create_engine.py, then restart")
    log.info("wxO agent %s at %s", WXO_AGENT_ID, WXO_INSTANCE_URL)
    if QUICK_FILLER:
        log.info("fillers while wxO searches: %d lines", len(ACKNOWLEDGEMENTS))
        if STILL_THINKING and STILL_THINKING_AFTER > 0:
            log.info("  then, if still thinking after %.1f s: %d quieter lines", STILL_THINKING_AFTER, len(STILL_THINKING))
    if SPECIALIST_ASK:
        log.info("asks before waiting for tools matching %r, then hold music", SPECIALIST_TOOLS.pattern)
    log.info("voice model %s", TTS_MODEL)
    yield
    await app.state.wxo.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def fresh_page(request: Request, call_next):
    """Browsers always check for a newer page, so a rebuild shows up on a
    normal refresh. The scripts and styles it loads have a fingerprint in
    their names, so they can be kept for good."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache"
    elif path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# ── browser: conversation token ──────────────────────────────────────────

_token_log: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = _token_log[ip]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= TOKENS_PER_MINUTE:
        return True
    hits.append(now)
    return False


@app.get("/api/token")
async def conversation_token(request: Request):
    if not SPEECH_ENGINE_ID:
        return JSONResponse({"error": "The voice service isn't set up yet."}, status_code=503)
    if _rate_limited(_client_ip(request)):
        return JSONResponse({"error": "Too many attempts. Please wait a minute and try again."}, status_code=429)
    try:
        res = await app.state.eleven.conversational_ai.conversations.get_webrtc_token(agent_id=SPEECH_ENGINE_ID)
    except Exception as e:
        log.error("token request failed: %s", e)
        return JSONResponse({"error": "Couldn't start the voice service."}, status_code=502)
    return JSONResponse({"token": res.token}, headers={"Cache-Control": "no-store"})


# ── browser: what's playing right now ────────────────────────────────────
# The page can hear sound levels but not whether a sound is a filler or the
# answer, so the server tells it, per conversation: "filler", "ask" (asking
# whether the caller minds waiting for the mortgage specialist), "music"
# (they said yes: play hold music), "hold" (a still-thinking line), "answer".

_phase_listeners: dict[str, set] = defaultdict(set)
_last_phase: dict[str, str] = {}
_CONVERSATION_ID = re.compile(r"[A-Za-z0-9_-]{6,100}")


def publish_phase(conversation_id: Optional[str], phase: str) -> None:
    if not conversation_id:
        return
    _last_phase[conversation_id] = phase
    for queue in list(_phase_listeners.get(conversation_id, ())):
        try:
            queue.put_nowait(phase)
        except asyncio.QueueFull:
            pass


@app.get("/api/turn-events/{conversation_id}")
async def turn_events(conversation_id: str, request: Request):
    if not _CONVERSATION_ID.fullmatch(conversation_id):
        return JSONResponse({"error": "Unknown conversation."}, status_code=404)
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _phase_listeners[conversation_id].add(queue)

    async def stream():
        try:
            yield "retry: 2000\n\n"
            if conversation_id in _last_phase:
                yield f"data: {_last_phase[conversation_id]}\n\n"
            while not await request.is_disconnected():
                try:
                    phase = await asyncio.wait_for(queue.get(), 15)
                    yield f"data: {phase}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            listeners = _phase_listeners.get(conversation_id)
            if listeners is not None:
                listeners.discard(queue)
                if not listeners:
                    _phase_listeners.pop(conversation_id, None)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.websocket("/ws")
async def speech_engine(ws: WebSocket):
    engine = app.state.engine
    if engine is None:
        await ws.close(code=1011)
        return
    # Only ElevenLabs may open this socket: it signs each connection with a
    # JWT derived from our API key. Reject before accepting the upgrade.
    if not engine.verify_request(ws.headers):
        log.warning("rejected /ws connection without a valid ElevenLabs signature")
        await ws.close(code=1008)
        return

    await ws.accept()
    convo = Conversation(
        app.state.wxo,
        hold_after=LINE_GAP_SECONDS,
        quick_filler=QUICK_FILLER,
        acknowledgements=ACKNOWLEDGEMENTS,
        still_thinking=STILL_THINKING,
        still_thinking_after=STILL_THINKING_AFTER,
        acknowledge_after=ACKNOWLEDGE_AFTER,
        early_filler_after=EARLY_FILLER_AFTER,
        specialist_ask=SPECIALIST_ASK,
        specialist_declined=SPECIALIST_DECLINED,
        specialist_tools=SPECIALIST_TOOLS,
        on_phase=lambda phase: publish_phase(convo.conversation_id, phase),
    )
    session = engine.create_session(ws, debug=DEBUG)

    def on_init(conversation_id: str) -> None:
        convo.conversation_id = conversation_id
        log.info("[%s] conversation started", convo.cid)

    async def on_transcript(transcript) -> None:
        # The SDK hands over the whole history each turn. wxO keeps its own
        # history on the thread, so only the newest user message is sent.
        latest = next((m.content for m in reversed(transcript) if m.role == "user"), "")
        if not latest.strip():
            return
        log.info("[%s] user: %s", convo.cid, latest[:200])
        await session.send_response(convo.reply(latest, transcript))

    def on_error(err: Exception) -> None:
        log.error("[%s] session error: %s", convo.cid, err)

    session.on("init", on_init)
    session.on("user_transcript", on_transcript)
    session.on("error", on_error)
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        convo.close()
        if convo.conversation_id:
            _last_phase.pop(convo.conversation_id, None)
        log.info("[%s] conversation ended", convo.cid)


# ── static client ────────────────────────────────────────────────────────

if CLIENT_DIST.is_dir():
    app.mount("/", StaticFiles(directory=CLIENT_DIST, html=True), name="client")
else:
    @app.get("/")
    async def not_built():
        return PlainTextResponse("Client not built. Run: cd client && npm install && npm run build", status_code=503)
