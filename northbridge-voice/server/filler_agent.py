"""Helpers around the filler agent (WXO_FILLER_AGENT_ID).

The filler agent writes every line spoken while the main agent works. This
module doesn't write any lines itself. It decides when to ask the filler
agent, builds what it's sent, and checks its reply before it's spoken.
"""

from __future__ import annotations

import random
import re
from typing import Iterable, Optional

GREETING_CUE = "ORB_CLICKED"


# ── when to ask ───────────────────────────────────────────────────────────
# Thanks, greetings, goodbyes and yes/no get a quick reply from the main
# agent, so the filler agent isn't asked at all.

# An utterance made only of these words is small talk ("yes please",
# "okay lovely, thanks"). One real word ("parking") and it isn't.
_SMALL_TALK_WORDS = {
    "ok", "okay", "right", "alright", "thanks", "thank", "you", "very", "much", "cheers", "ta",
    "lovely", "great", "perfect", "brilliant", "cool", "nice", "fab", "awesome", "sure", "fine",
    "bye", "goodbye", "see", "ya", "later", "no", "nope", "yes", "yeah", "yep", "aye", "please",
    "hi", "hello", "hiya", "hey", "good", "morning", "afternoon", "evening", "that", "that's",
    "thats", "all", "it", "everything", "so", "um", "uh", "er", "erm", "hmm", "oh", "ah",
    "well", "then", "just", "a", "lot", "again", "too", "now", "for", "the", "help", "there",
}


# Thanks, compliments and goodbyes, wherever they appear in the sentence.
_COURTESY = re.compile(
    r"\b(thanks?|thank you|cheers|appreciate|grateful|helpful|brilliant|lovely|perfect|wonderful|"
    r"amazing|great|fantastic|bye|goodbye|see you|take care|have a (good|nice|lovely))\b",
    re.IGNORECASE,
)
# Anything that asks for something.
_ASKS = re.compile(
    r"\?|\b(what|where|when|which|who|whom|why|how|is there|are there|"
    r"tell me|i need|i want|i'd like|looking for)\b",
    re.IGNORECASE,
)


def is_small_talk(text: str) -> bool:
    """Thanks, greetings, goodbyes, yes/no: the reply will be quick."""
    t = text.strip()
    if not t or t == GREETING_CUE:
        return True
    words = re.findall(r"[a-z']+", t.lower())
    if words and all(w in _SMALL_TALK_WORDS for w in words):
        return True
    return bool(_COURTESY.search(t)) and not _ASKS.search(t)


# Questions answered without looking anything up: about the assistant itself,
# or about something it has just said.
_NO_LOOKUP = re.compile(
    r"\b(what|how) (can|could|do|would) you (help|do)\b|\bwho (are you|am i (speaking|talking) to)\b|"
    r"\bwhat are you\b|\bare you (a|an) (robot|bot|ai|human|real|person)\b|\bwhat'?s your name\b|"
    r"\btranslat|\bin (french|spanish|german|polish|urdu|punjabi|arabic|hindi|chinese|italian|portuguese|romanian)\b|"
    r"\b(say|repeat) (that|it)\b|\bwhat did you (just )?say\b|\bsay again\b|\bslower\b|"
    r"\b(can you|could you) (repeat|explain that)\b",
    re.IGNORECASE,
)


def likely_needs_lookup(text: str) -> bool:
    """A guess, before wxO has decided, that this question will need a search.
    Used to start the filler early instead of waiting for the search to begin."""
    t = text.strip()
    if is_small_talk(t) or _NO_LOOKUP.search(t):
        return False
    return len(re.findall(r"[A-Za-z']+", t)) >= 4


# ── what it's sent ────────────────────────────────────────────────────────
# The filler agent starts fresh every time, so it would settle into a
# favourite opening. Each turn it's told which word to start with, chosen
# so it never matches how a recent line began. It writes the rest itself.

OPENERS = (
    "Of course", "Sure", "Okay", "Right", "Ah", "Yes", "Alright",
    "Absolutely", "No problem", "Let me see", "Let's see", "I understand",
)


def pick_opener(recent_lines: Iterable[str], rng=random) -> str:
    """An opener none of the recent lines started with."""
    recent = [line for line in recent_lines if line.split()]
    used = {line.lower().split(",")[0].strip() for line in recent}
    used |= {" ".join(line.lower().split()[:2]).rstrip(",.!") for line in recent}
    used |= {line.lower().split()[0].rstrip(",.!") for line in recent}
    fresh = [o for o in OPENERS if o.lower() not in used]
    return rng.choice(fresh or list(OPENERS))


# What the filler agent is told when it writes a line in advance, before the
# caller has asked their next question.
NEXT_QUESTION = "[next question, not heard yet]"


def build_prompt(
    text: Optional[str], *, interrupted: bool, already_said: Iterable[str], assistant_said: str
) -> str:
    """Everything the filler agent sees for one turn. text=None asks for a
    line written in advance, to suit whatever the caller asks next."""
    already_said = list(already_said)
    lines = []
    if already_said:
        lines.append("ALREADY SAID: " + " / ".join(already_said))
    if not interrupted:
        lines.append("START WITH: " + pick_opener(already_said))
    if assistant_said:
        lines.append("ASSISTANT: " + _tail(assistant_said, 300))
    lines.append(("CALLER (interrupting): " if interrupted else "CALLER: ") + (text or NEXT_QUESTION))
    return "\n".join(lines)


# ── what's spoken ─────────────────────────────────────────────────────────


# The instant reaction is written before the question is known, so it must
# fit any question: a few words, no promise to look anything up.
MAX_REACTION_WORDS = 4


def parse_reaction(raw: str) -> Optional[str]:
    """The written-ahead reaction ("Sure.", "Okay, right."), or None."""
    line = clean_line((raw or "").split("|")[0])
    if not line or len(line.split()) > MAX_REACTION_WORDS:
        return None
    return line


def parse_reply(raw: str) -> tuple[Optional[str], list[str]]:
    """Split 'reaction | still on it | still on it' and check each part.
    Returns the reaction and up to two follow-up lines, in order."""
    parts = [clean_line(p) for p in (raw or "").split("|")]
    ack = parts[0] if parts else None
    follow_ups: list[str] = []
    for line in parts[1:3]:
        if line and line != ack and line not in follow_ups:
            follow_ups.append(line)
    return ack, follow_ups


def clean_line(raw: str) -> Optional[str]:
    """A line that's safe to speak, or None.

    Filler lines must never carry facts, so anything with digits, a
    question, anything long, or the agent's SKIP signal is dropped.
    """
    line = re.sub(r"[\[\]*_`#\"“”]", "", raw or "").strip()
    line = re.sub(r"\s+", " ", line)
    if not line or line.upper().startswith("SKIP"):
        return None
    if any(ch.isdigit() for ch in line) or "?" in line:
        return None
    if len(line) > 90 or len(line.split()) > 14:
        return None
    return line


def _tail(text: str, limit: int) -> str:
    """The last `limit` characters, starting at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    return "…" + cut[cut.find(" ") + 1:] if " " in cut else cut
