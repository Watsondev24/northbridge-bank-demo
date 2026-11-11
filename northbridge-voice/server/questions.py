"""What kind of thing the caller just said, to decide whether a filler line
("Hm...", "Let me have a look...") should play while wxO works on the answer.
"""

from __future__ import annotations

import re

GREETING_CUE = "ORB_CLICKED"


# ── small talk ───────────────────────────────────────────────────────────
# Thanks, greetings, goodbyes and yes/no get a quick reply, so no filler
# line is played for them.

# An utterance made only of these words is small talk ("yes please",
# "okay lovely, thanks"). One real word ("ISA") and it isn't.
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
