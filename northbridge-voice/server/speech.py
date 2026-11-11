"""Make streamed agent text fit to be spoken.

The agent writes for a chat window: bold, bullet lists, links. Read aloud,
that becomes "asterisk asterisk" or a URL spelled out. This cleans the text
as it streams, holding back at most one word so speech isn't delayed.
"""

from __future__ import annotations

import re

_URL = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_DROP = set("*`#")
_BULLETS = set("-•*")
_ENDS_SENTENCE = set(".!?:;,")


class SpokenText:
    def __init__(self, url_phrase: str = "the Northbridge website") -> None:
        self.url_phrase = url_phrase
        self._line_start = True
        self._pending_newlines = 0
        self._pending_space = False
        self._last_char = ""
        self._link_state = ""  # "", "text", "after", "url"
        self._link_text: list[str] = []
        self._word = ""

    def feed(self, chunk: str) -> str:
        """Clean one streamed chunk; returns text that is safe to speak now."""
        out: list[str] = []
        for ch in chunk:
            self._char(ch, out)
        return self._words("".join(out), final=False)

    def flush(self) -> str:
        """Return anything held back at the end of the reply."""
        out: list[str] = []
        if self._link_state in ("text", "after"):
            out.append("".join(self._link_text))
        self._link_state = ""
        return self._words("".join(out), final=True)

    # ── character stage: markdown structure ──────────────────────────

    def _char(self, ch: str, out: list[str]) -> None:
        state = self._link_state
        if state == "text":
            if ch == "]":
                self._link_state = "after"
            else:
                self._link_text.append(ch)
            return
        if state == "after":
            self._link_state = ""
            if ch == "(":
                self._link_state = "url"
                self._emit_text("".join(self._link_text), out)
                self._link_text = []
                return
            self._emit_text("".join(self._link_text), out)
            self._link_text = []
            # fall through and handle ch normally
        elif state == "url":
            if ch == ")":
                self._link_state = ""
            return

        if ch == "\n":
            self._pending_newlines += 1
            self._line_start = True
            return
        if ch == "[":
            self._link_state = "text"
            self._link_text = []
            return
        if ch in _DROP:
            if self._line_start and ch == "*":
                return
            return
        if self._line_start:
            if ch in (" ", "\t", " ", " "):
                return
            if ch in _BULLETS:
                return
        self._emit_text(ch, out)

    def _emit_text(self, text: str, out: list[str]) -> None:
        for ch in text:
            if ch in _DROP:
                continue
            if ch in (" ", "\t"):
                # Held until the next visible character, so trailing spaces
                # before a line break don't pile up.
                self._pending_space = True
                continue
            if self._pending_newlines:
                # A line break becomes a spoken pause: add a full stop if the
                # line didn't end with punctuation (list items usually don't).
                if self._last_char and self._last_char not in _ENDS_SENTENCE:
                    out.append(".")
                if self._last_char:
                    out.append(" ")
                self._pending_newlines = 0
            elif self._pending_space and self._last_char:
                out.append(" ")
            self._pending_space = False
            self._line_start = False
            out.append(ch)
            self._last_char = ch

    # ── word stage: URLs ─────────────────────────────────────────────

    def _words(self, text: str, final: bool) -> str:
        buf = self._word + text
        if final:
            self._word = ""
            return self._clean_words(buf)
        cut = max(buf.rfind(" "), buf.rfind("\t"))
        if cut < 0:
            self._word = buf
            return ""
        self._word = buf[cut + 1:]
        return self._clean_words(buf[: cut + 1])

    def _clean_words(self, text: str) -> str:
        if "://" not in text and "www." not in text.lower():
            return re.sub(r" {2,}", " ", text)
        parts = re.split(r"(\s+)", text)
        cleaned = []
        for p in parts:
            core = p.rstrip(".,;:!?)")
            if core and _URL.match(core):
                cleaned.append(self.url_phrase + p[len(core):])
            else:
                cleaned.append(p)
        return re.sub(r" {2,}", " ", "".join(cleaned))
