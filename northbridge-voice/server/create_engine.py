"""Register (or re-point) the ElevenLabs Speech Engine for this server.

Usage, from the project folder:

    python server/create_engine.py https://xxxx.ngrok-free.app

It takes your server's public https URL and tells ElevenLabs to send
conversations to wss://<that host>/ws. On first run it creates the engine and
prints the ID to put in ELEVENLABS_SPEECH_ENGINE_ID. If that variable is
already set, it updates the existing engine instead, so the ID never changes.

Optional settings read from .env:
    ELEVENLABS_VOICE_ID   voice for the agent (default: ElevenLabs' default)
    ELEVENLABS_TTS_MODEL  voice model (default: eleven_v4_turbo, which
                          can whisper, hum and sigh on cue)
    ENGINE_LANGUAGE       spoken language code (default: en)
    TURN_EAGERNESS        patient | normal | eager: how soon a turn counts as finished
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from elevenlabs import AsyncElevenLabs

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MAX_DURATION_SECONDS = 600  # longest a single call may last


def ws_url_from(arg: str) -> str:
    u = urlparse(arg if "://" in arg else f"https://{arg}")
    if not u.netloc:
        sys.exit(f"Not a URL: {arg}")
    if u.hostname in ("localhost", "127.0.0.1"):
        sys.exit("ElevenLabs can't reach localhost. Use your ngrok https URL.")
    return f"wss://{u.netloc}/ws"


async def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        sys.exit("Set ELEVENLABS_API_KEY in .env first.")

    ws_url = ws_url_from(sys.argv[1])
    client = AsyncElevenLabs(api_key=api_key)
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    language = os.getenv("ENGINE_LANGUAGE", "en").strip() or "en"
    existing = os.getenv("ELEVENLABS_SPEECH_ENGINE_ID", "").strip()

    settings = dict(
        speech_engine={"ws_url": ws_url, "request_headers": {}},
        language=language,
        conversation={"max_duration_seconds": MAX_DURATION_SECONDS},
    )
    tts = {"model_id": os.getenv("ELEVENLABS_TTS_MODEL", "").strip() or "eleven_v4_turbo"}
    if voice_id:
        tts["voice_id"] = voice_id
    settings["tts"] = tts

    # How quickly ElevenLabs decides the caller has finished speaking:
    # patient | normal | eager. Eager answers sooner but may cut in on
    # people who pause mid-sentence.
    eagerness = os.getenv("TURN_EAGERNESS", "").strip()
    if eagerness:
        settings["turn"] = {"turn_eagerness": eagerness}

    if existing:
        await client.speech_engine.update(existing, **settings)
        print(f"Updated Speech Engine {existing}")
        print(f"  conversations now go to {ws_url}")
        print(f"  voice model {tts['model_id']}")
        if eagerness:
            print(f"  turn eagerness {eagerness}")
        return

    engine = await client.speech_engine.create(name="Northbridge Bank voice assistant", **settings)
    print(f"Created Speech Engine: {engine.engine_id}")
    print(f"  conversations go to {ws_url}")
    print()
    print("Add this line to .env, then restart the server:")
    print(f"  ELEVENLABS_SPEECH_ENGINE_ID={engine.engine_id}")


if __name__ == "__main__":
    asyncio.run(main())
