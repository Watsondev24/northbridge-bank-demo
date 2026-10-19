"""Demo-only v3 language guardrail: warn once, block subsequent matching text.

Stores strike counts in a local SQLite database. Supply an explicit, distinct
conversation_id in request.context to keep conversations isolated.
"""
import os
import re
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any, Dict
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Language Guardrail v3", version="3.0.0")
DB_PATH = Path(os.environ.get("GUARDRAIL_DB_PATH", str(Path.home() / ".northbridge_guardrail_strikes.sqlite3")))
_LOCK = Lock()
PATTERN = re.compile(r"\bsilly\b", re.IGNORECASE)
WARNING = "Please keep the conversation respectful. I'll continue helping with your request."
BLOCK = "This conversation has been stopped after repeated inappropriate language."

class Request(BaseModel):
    payload: Dict[str, Any]
    context: Dict[str, Any]

def _conversation_id(data: Request):
    # Avoid sharing strikes between distinct sessions: no global/default key.
    for source in (data.context, data.payload):
        for key in ("conversation_id", "conversationId", "session_id", "sessionId"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None

def _latest_text(payload):
    messages = payload.get("messages") or []
    if not messages or not isinstance(messages[-1], dict):
        return ""
    content = messages[-1].get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text", "") if isinstance(content.get("text", ""), str) else ""
    return ""

def _strike(cid):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, sqlite3.connect(DB_PATH) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS strikes (conversation_id TEXT PRIMARY KEY, count INTEGER NOT NULL, pending_warning INTEGER NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO strikes VALUES (?, 0, 0)", (cid,))
        connection.execute("UPDATE strikes SET count = count + 1 WHERE conversation_id = ?", (cid,))
        count = connection.execute("SELECT count FROM strikes WHERE conversation_id = ?", (cid,)).fetchone()[0]
        if count == 1:
            connection.execute("UPDATE strikes SET pending_warning = 1 WHERE conversation_id = ?", (cid,))
        return count

def _consume_warning(cid):
    with _LOCK, sqlite3.connect(DB_PATH) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS strikes (conversation_id TEXT PRIMARY KEY, count INTEGER NOT NULL, pending_warning INTEGER NOT NULL)")
        row = connection.execute("SELECT pending_warning FROM strikes WHERE conversation_id = ?", (cid,)).fetchone()
        if not row or row[0] != 1:
            return False
        connection.execute("UPDATE strikes SET pending_warning = 0 WHERE conversation_id = ?", (cid,))
        return True

@app.post("/agent_pre_invoke")
def agent_pre_invoke(data: Request):
    if not PATTERN.search(_latest_text(data.payload)):
        return {"continue_processing": True}
    cid = _conversation_id(data)
    if not cid:
        # Fail open rather than allow one conversation to block another.
        # A distinct conversation identifier is needed for persistent strikes.
        return {"continue_processing": True}
    if _strike(cid) > 1:
        return {"continue_processing": False, "message": BLOCK}
    return {"continue_processing": True}

@app.post("/agent_post_invoke")
def agent_post_invoke(data: Request):
    cid = _conversation_id(data)
    if not cid or not _consume_warning(cid):
        return {"continue_processing": True}
    # Example payload adaptation; verify the deployed wxO post-invoke shape.
    import copy
    modified = copy.deepcopy(data.payload)
    messages = modified.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
        content = messages[-1].get("content")
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            content["text"] += "\n\n" + WARNING
        elif isinstance(content, str):
            messages[-1]["content"] = content + "\n\n" + WARNING
        else:
            return {"continue_processing": True}
        return {"continue_processing": True, "modified_payload": modified}
    return {"continue_processing": True}
