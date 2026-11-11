"""Parsing for the watsonx Orchestrate v2 chat/completions SSE stream.

Pure functions, no I/O, so they can be tested against captured streams.

The stream is read defensively: wxO has shipped more than one event shape
for chat/completions, so text, tool activity and the thread id are each
looked for in every place they have been seen rather than in one fixed path.
Unknown events are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional


@dataclass(frozen=True)
class WxoEvent:
    """One meaningful thing that happened in the stream.

    kind is one of:
      "thread" — value is the thread id to reuse on the next turn
      "text"   — value is a chunk of the agent's spoken reply
      "tool"      — value is the tool name; the agent is off doing work and
                    will be silent for a while
      "tool_done" — the tool returned; reply text usually follows
      "final_text" — the whole reply once more, at the end; only used for an
                    agent whose model doesn't stream
      "done"      — the stream finished
    """

    kind: str
    value: str = ""


def iter_sse_data(lines: Iterable[str]) -> Iterator[str]:
    """Yield the data payload of each SSE event from raw text lines.

    Multi-line data fields are joined with newlines, per the SSE spec.
    """
    buf: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if buf:
                yield "\n".join(buf)
                buf = []
            continue
        if line.startswith(":"):
            continue  # comment / keep-alive
        if line.startswith("data:"):
            buf.append(line[5:].lstrip(" "))
        # "event:", "id:" and "retry:" lines carry nothing we need: the
        # event type is repeated inside the JSON payload.
    if buf:
        yield "\n".join(buf)


def parse_payload(data: str) -> list[WxoEvent]:
    """Turn one SSE data payload into zero or more events."""
    data = data.strip()
    if not data:
        return []
    if data == "[DONE]":
        return [WxoEvent("done")]
    try:
        obj = json.loads(data)
    except ValueError:
        return []
    if not isinstance(obj, dict):
        return []

    events: list[WxoEvent] = []

    thread_id = _find_key(obj, "thread_id")
    if isinstance(thread_id, str) and thread_id:
        events.append(WxoEvent("thread", thread_id))

    kind = str(obj.get("object") or obj.get("event") or "")
    if kind.endswith("completed"):
        # A completed message repeats the whole reply. The main agent's words
        # have already arrived as deltas, so it is reported separately as
        # "final_text": useful only for an agent that doesn't stream deltas.
        final = _completed_text(obj)
        if final:
            events.append(WxoEvent("final_text", final))
        if _is_done(obj):
            events.append(WxoEvent("done"))
        return events

    step = _step(obj)
    if step is not None:
        step_type = str(step.get("type", ""))
        if step_type == "tool_calls":
            calls = step.get("tool_calls") or [{}]
            name = calls[0].get("name", "") if isinstance(calls[0], dict) else ""
            events.append(WxoEvent("tool", name))
        elif step_type == "tool_response":
            events.append(WxoEvent("tool_done", str(step.get("name", ""))))
        # Other step types (planning, reasoning) are never spoken.
        return events

    text = _text(obj)
    if text:
        events.append(WxoEvent("text", text))

    if _is_done(obj):
        events.append(WxoEvent("done"))
    return events


# ── internals ────────────────────────────────────────────────────────────


def _find_key(obj: Any, key: str, depth: int = 0) -> Any:
    """Depth-limited search for the first value stored under *key*."""
    if depth > 5:
        return None
    if isinstance(obj, dict):
        if key in obj and obj[key] not in (None, "", [], {}):
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key, depth + 1)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(obj, list):
        for v in obj[:8]:
            found = _find_key(v, key, depth + 1)
            if found not in (None, "", [], {}):
                return found
    return None


def _step(obj: dict) -> Optional[dict]:
    """Return step_details if this is a run-step event (tool call, tool result)."""
    choices = obj.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        delta = choices[0].get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("step_details"), dict):
            return delta["step_details"]
    data = obj.get("data")
    if isinstance(data, dict):
        delta = data.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("step_details"), dict):
            return delta["step_details"]
    return None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, dict):  # {"text": {"value": "..."}}
                    t = t.get("value")
                if isinstance(t, str) and item.get("type", "text") in ("text", "output_text"):
                    parts.append(t)
        return "".join(parts)
    return ""


def _text(obj: dict) -> str:
    """Extract assistant reply text from the shapes wxO has used."""
    # OpenAI-style: {"choices": [{"delta": {"role": "assistant", "content": "..."}}]}
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        # Only deltas: a final "message" repeats the whole reply.
        delta = choices[0].get("delta") or {}
        if isinstance(delta, dict) and delta.get("role", "assistant") == "assistant":
            return _content_to_text(delta.get("content"))
        return ""

    # Event-style: {"event": "message.delta", "data": {"delta": {"content": [...]}}}
    inner = obj.get("data") if isinstance(obj.get("data"), dict) else obj
    event = str(obj.get("event") or obj.get("object") or obj.get("type") or "")
    if "delta" in event or "delta" in inner:
        delta = inner.get("delta")
        if isinstance(delta, dict):
            if delta.get("role", "assistant") != "assistant":
                return ""
            return _content_to_text(delta.get("content"))
        if isinstance(delta, str):
            return delta
    return ""


def _completed_text(obj: dict) -> str:
    data = obj.get("data")
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
        return ""
    content = message.get("content")
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("response_type", "text") == "text" and isinstance(item.get("text"), str)
        )
    return content if isinstance(content, str) else ""


def _is_done(obj: dict) -> bool:
    event = str(obj.get("event") or obj.get("object") or obj.get("type") or "")
    # "thread.message.completed" is deliberately not here: it repeats the full
    # reply, and a run can in principle produce more than one message. The
    # HTTP stream closing is the real end of the turn.
    if event in ("done", "run.completed", "thread.run.completed"):
        return True
    choices = obj.get("choices")
    if isinstance(choices, list) and choices and choices[0].get("finish_reason") == "stop":
        return True
    return False
