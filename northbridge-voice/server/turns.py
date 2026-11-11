"""One voice conversation: turns a user utterance into a stream of reply text."""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Optional, Sequence

import questions
from speech import SpokenText
from wxo import WxoClient, WxoError

log = logging.getLogger("turns")

MAX_INPUT_CHARS = 8192
FALLBACK = (
    "Sorry, I'm having trouble reaching Northbridge right now. "
    "Could you try again in a moment?"
)
# ElevenLabs sometimes sends the same turn again: a pause mid-sentence, or
# the agent's own voice reaching the microphone and counting as speech.
# Turns at least this similar are treated as the same question.
SAME_TURN_SIMILARITY = 0.85
# A re-sent turn this soon after it was fully answered gets the same answer
# again, without asking wxO.
REPEAT_WINDOW = 12.0
# ElevenLabs can also re-send a *longer* version of a turn a moment after
# it's been answered. Within this window that's still a repeat; after it, a
# longer version is a new question ("ISA rates" then "ISA rates for under-18s").
LATE_RESEND_WINDOW = 4.0
# When ElevenLabs re-sends a turn, it drops whatever was just sent for the
# earlier copy. A filler line sent this recently can't have finished playing,
# so it is said again for the new copy.
RESAY_WINDOW = 2.5
# Fillers used when none are passed in (app.py passes FILLERS from .env).
ACKNOWLEDGEMENTS = ("Mm-hmm.", "Mhm.")

_END = object()


# ── questions for a slower specialist agent ──────────────────────────────
# Personal borrowing estimates go to the Mortgage Affordability Agent, which
# runs outside wxO and takes around ten seconds. For those, the assistant asks
# "That one might take a little longer to check, is that okay?" and ends its
# turn, while wxO carries on working. When the caller says "sure", hold music
# plays on the page until the answer is ready. The question is spotted from
# its wording straight away, or the moment wxO routes to the specialist.

_HOW_MUCH = re.compile(
    r"\bhow much (could|can|would|might|will) (i|we) (borrow|get|be (lent|offered))\b|"
    r"\bhow (big|large) (a|of a) mortgage\b|\b(can|could) (i|we) afford\b|"
    r"\bmaximum (mortgage|loan|amount)\b|\bmost (i|we) (could|can) borrow\b",
    re.IGNORECASE,
)
_BORROWING = re.compile(r"\b(borrow|afford|mortgage|lend)\w*", re.IGNORECASE)
_INCOME = re.compile(r"\b(income|salary|salaries|earn\w*|wages?|take[- ]home)\b", re.IGNORECASE)
_AMOUNT = re.compile(
    r"£\s?\d|\b\d+(\.\d+)?\s?(k|grand|thousand)\b|\b\d{1,3},\d{3}\b|\b\d{5,}\b|"
    r"\b(thousand|grand)\b",
    re.IGNORECASE,
)


_AGREE_PHRASES = re.compile(
    r"\b(no problem|no worries|not a problem|go ahead|carry on|i can wait|happy to wait|"
    r"(i )?don'?t mind|that'?s (fine|ok|okay|alright|all right|good)|of course|sounds good|that works)\b"
)
_AGREE_WORDS = {
    "yes", "yeah", "yep", "yup", "ya", "sure", "ok", "okay", "fine", "alright", "right", "cool",
    "perfect", "great", "absolutely", "definitely", "certainly", "please", "thanks", "thank", "you",
    "lovely", "brilliant", "good", "go", "ahead", "that", "that's", "thats", "is", "it", "s", "um",
    "uh", "er", "erm", "oh", "yes,", "wait", "i", "can", "no", "problem", "worries", "of", "course",
}
_STRONG_AGREE = {"yes", "yeah", "yep", "yup", "ya", "sure", "ok", "okay", "fine", "alright",
                 "absolutely", "definitely", "certainly", "cool", "perfect", "great", "lovely"}
_DECLINE = re.compile(
    r"^(no|nope|nah|not (now|really|today)|don'?t (worry|bother)|never ?mind|cancel|forget (it|that)|"
    r"i'?ll (leave|skip) it|leave it)\b"
)


def _words(text: str) -> list:
    return re.findall(r"[a-z']+", (text or "").lower().replace("’", "'"))


def is_go_ahead(text: str) -> bool:
    """The caller is happy to wait: "sure", "yeah that's fine", "no problem"."""
    t = " ".join(_words(text))
    if not t:
        return False
    if _AGREE_PHRASES.search(t):
        return True
    words = t.split()
    if words[0] in ("no", "nope", "nah", "not"):
        return False
    return len(words) <= 8 and all(w in _AGREE_WORDS for w in words) and any(w in _STRONG_AGREE for w in words)


def is_no_thanks(text: str) -> bool:
    """The caller would rather not wait: "no thanks", "don't worry about it"."""
    words = _words(text)
    return (bool(words) and len(words) <= 6 and bool(_DECLINE.search(" ".join(words)))
            and not is_go_ahead(text))


def looks_like_affordability(text: str) -> bool:
    """A personal borrowing estimate with the figures to work it out:
    "I earn £70k with £40k saved, how much could I borrow?". Questions about
    mortgage products ("first-time buyer mortgages") don't count, and nor does
    "how much could I borrow?" on its own, which the agent answers with a
    question first rather than routing."""
    t = text or ""
    if not _AMOUNT.search(t):
        return False
    return bool(_HOW_MUCH.search(t) or (_BORROWING.search(t) and _INCOME.search(t)))


_DETAILS = re.compile(r"\b(saved|savings|deposit|debts?|outgoings|income|salary|earn\w*|wages?)\b", re.IGNORECASE)


def gives_affordability_figures(text: str, last_agent_text: str) -> bool:
    """The caller's figures, given because the agent asked for them: it said
    "To work out how much you could borrow, what's your annual income?" and
    the caller replies "I earn 70k and I've got 40k saved". On its own that
    reply doesn't mention borrowing, so looks_like_affordability misses it."""
    last = last_agent_text or ""
    t = text or ""
    return bool("?" in last and _BORROWING.search(last) and _INCOME.search(last)
                and _AMOUNT.search(t) and _DETAILS.search(t))


@dataclass
class _Job:
    """One question being answered. Outlives a cancelled handler, so a
    re-sent copy of the same question carries on instead of starting over."""

    text: str
    norm: str
    started: float
    queue: asyncio.Queue
    producer: Optional[asyncio.Task] = None
    spoken: SpokenText = field(default_factory=SpokenText)
    sent: list = field(default_factory=list)   # real answer text sent so far
    filled: bool = False        # an acknowledgement has been spoken
    answered: bool = False
    tool_started: float = 0.0
    hold_lines: list = field(default_factory=list)  # "still on it" lines, in order
    hold_gap: Optional[float] = None  # pause before each one; None = the conversation's hold_after
    ack_due: float = 0.0        # when to say the acknowledgement, if the answer hasn't started
    filled_at: float = 0.0      # when the acknowledgement was spoken
    last_line: str = ""         # the most recent filler/holding line sent
    last_line_at: float = 0.0
    last_line_starts: float = 0.0  # roughly when it starts being heard
    last_line_ends: float = 0.0  # roughly when it finishes being spoken
    finished: bool = False
    finished_at: float = 0.0
    wants_specialist: bool = False  # the question looks like one for the specialist
    specialist: bool = False    # the caller has been asked to wait for the specialist
    go_ahead_norm: str = ""     # the caller's "sure", so a re-sent copy carries on
    streamed: bool = False      # the answer arrived word by word, not all at once

    def cancel(self) -> None:
        if self.producer and not self.producer.done():
            self.producer.cancel()


class Conversation:
    """Holds the wxO thread for one Speech Engine conversation.

    The thread lives in this object, which lives exactly as long as the
    WebSocket, so nothing accumulates on the server between conversations.

    While wxO works, a short filler line ("Hm...") plays when wxO starts
    searching, or if the answer hasn't started `acknowledge_after` seconds
    after the caller's turn ends (sooner for questions that look like they'll
    need a search). If it still hasn't started `still_thinking_after` seconds
    after that, one quieter line follows. Small talk gets no filler.

    Personal borrowing estimates go to the slower Mortgage Agent: the caller is
    asked whether they mind waiting, and hold music plays on their go-ahead.
    """

    def __init__(
        self,
        wxo: WxoClient,
        *,
        hold_after: float,
        quick_filler: bool = True,
        acknowledgements: Sequence[str] = (),
        still_thinking: Sequence[str] = (),
        still_thinking_after: float = 2.5,
        acknowledge_after: float = 1.5,
        early_filler_after: float = 0.7,
        specialist_ask: str = "",
        specialist_declined: str = "No problem. Is there anything else I can help with?",
        specialist_tools: Optional["re.Pattern[str]"] = None,
        on_phase: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.wxo = wxo
        self.thread_id: Optional[str] = None
        self.hold_after = hold_after
        self.quick_filler = quick_filler
        self.acknowledgements = [a for a in acknowledgements if a.strip()] or list(ACKNOWLEDGEMENTS)
        self._next_ack = 0  # position in the list, so each one is used in turn
        # A very quiet second acknowledgement if the answer is slow to start.
        self.still_thinking = [a for a in still_thinking if a.strip()]
        self.still_thinking_after = still_thinking_after
        self.acknowledge_after = acknowledge_after
        self.early_filler_after = early_filler_after
        # For the slower specialist: ask whether the caller minds waiting.
        self.specialist_ask = specialist_ask.strip()
        self.specialist_declined = specialist_declined.strip()
        self.specialist_tools = specialist_tools
        self._waiting: Optional[_Job] = None  # asked to wait; needs the caller's go-ahead
        # Tells the page what's playing, so its caption and orb don't have to
        # guess from sound levels: "filler", "ask", "music", "hold", "answer".
        self.on_phase = on_phase
        self._next_still = 0
        self.conversation_id: Optional[str] = None
        self._job: Optional[_Job] = None
        # The assistant's last answer: tells a mortgage follow-up ("I earn 70k")
        # from figures given for something else.
        self._last_agent_text = ""
        self._stream_noted = False  # logged whether wxO streams, once per conversation

    def _wants_specialist(self, user_text: str) -> bool:
        return bool(self.specialist_ask) and (
            looks_like_affordability(user_text) or gives_affordability_figures(user_text, self._last_agent_text))

    @property
    def cid(self) -> str:
        return (self.conversation_id or "-")[:14]

    def close(self) -> None:
        if self._job:
            self._job.cancel()
            self._job = None

    def was_interrupted(self, user_text: str) -> bool:
        """The previous answer was still coming through when a different
        question arrived. Re-sends of the same question never count."""
        job = self._job
        return bool(job and job.sent and not job.finished and not _same_turn(user_text, job.norm))

    async def reply(self, user_text: str, history: Optional[Sequence] = None) -> AsyncIterator[str]:
        """Yield speakable reply text for TTS."""
        user_text = user_text.strip()[:MAX_INPUT_CHARS]
        now = time.monotonic()
        job = self._job

        waiting = self._waiting
        if waiting is not None and (waiting is not job or job.finished):
            self._waiting = waiting = None
        if waiting is not None:
            if is_go_ahead(user_text):
                # "Sure": hold music on the page until the answer is ready.
                self._waiting = None
                job.go_ahead_norm = _normalise(user_text)
                job.last_line = ""
                log.info("[%s] caller is happy to wait (+%.0f ms)", self.cid, _ms(job.started))
                if not (job.producer and job.producer.done()):
                    self._phase("music")
                async for chunk in self._run(job):
                    yield chunk
                return
            if _same_turn(user_text, job.norm) and not _adds_words(user_text, job.norm):
                # The question itself, re-sent while we wait for the go-ahead.
                rest = _unheard(job, now)
                if rest:
                    log.info("[%s] saying again: %s", self.cid, rest)
                    _mark_spoken(job, rest, now)
                    yield _line(rest)
                return
            self._waiting = None
            if is_no_thanks(user_text):
                log.info("[%s] caller doesn't want to wait", self.cid)
                job.cancel()
                job.finished, job.finished_at = True, now
                self._phase("answer")
                yield _line(self.specialist_declined)
                return
            # Anything else is a new question: handled below, dropping this one.
        elif (job and not job.finished and job.go_ahead_norm
              and _same_turn(user_text, job.go_ahead_norm, allow_longer=False)):
            log.info("[%s] go-ahead re-sent: carrying on", self.cid)
            async for chunk in self._run(job):
                yield chunk
            return

        grew = bool(job and not job.finished and not job.answered and _adds_words(user_text, job.norm))
        if job and not job.finished and _same_turn(user_text, job.norm) and not grew:
            log.info("[%s] same question re-sent: carrying on where we were", self.cid)
            rest = _unheard(job, now) if not job.answered else ""
            if rest:
                # ElevenLabs dropped it along with the earlier copy of the turn:
                # pick up from the phrase it was cut off in, not from the top.
                log.info("[%s] saying again: %s", self.cid, rest)
                _mark_spoken(job, rest, now)
                yield _line(rest)
            async for chunk in self._run(job):
                yield chunk
            return
        just_answered = bool(job and job.finished and now - job.finished_at < LATE_RESEND_WINDOW)
        if job and job.finished and _same_turn(user_text, job.norm, allow_longer=just_answered):
            if job.sent and now - job.finished_at < REPEAT_WINDOW:
                log.info("[%s] same question re-sent: replaying the answer", self.cid)
                self._phase("answer")
                yield "".join(job.sent)
                return

        if grew:
            # The caller hadn't finished: ElevenLabs sent part of the question,
            # then the whole of it. Nothing has been answered yet, so ask wxO
            # the full question. Whatever filler was said still stands.
            log.info("[%s] question grew before any answer: asking the full question", self.cid)
            old = job
            old.cancel()
            job = _Job(text=user_text, norm=_normalise(user_text), started=now, queue=asyncio.Queue())
            for name in ("filled", "filled_at", "hold_lines", "hold_gap", "ack_due", "last_line", "last_line_at",
                         "last_line_starts", "last_line_ends", "wants_specialist", "specialist"):
                setattr(job, name, getattr(old, name))
            self._job = job
            job.producer = asyncio.create_task(self._produce(job))
            rest = _unheard(old, now)
            if rest:
                log.info("[%s] saying again: %s", self.cid, rest)
                _mark_spoken(job, rest, now)
                yield _line(rest)
            if not job.specialist and self._wants_specialist(user_text):
                job.wants_specialist = True
                yield self._ask_to_wait(job)
                return
            async for chunk in self._run(job):
                yield chunk
            return

        interrupted = self.was_interrupted(user_text)
        if interrupted:
            log.info("[%s] caller interrupted the agent", self.cid)
        if job:
            if job.sent and not job.finished:
                self._last_agent_text = "".join(job.sent).strip()
            job.cancel()

        job = _Job(text=user_text, norm=_normalise(user_text), started=now, queue=asyncio.Queue())
        self._job = job
        job.producer = asyncio.create_task(self._produce(job))

        if self._wants_specialist(user_text):
            # A question for the slower specialist: ask whether they mind
            # waiting, and end the turn. wxO keeps working meanwhile.
            job.wants_specialist = True
            yield self._ask_to_wait(job)
            return
        if self.quick_filler and not questions.is_small_talk(user_text):
            # A filler line when wxO starts searching (or, as a backstop, if
            # nothing has come back after `acknowledge_after` seconds).
            # Questions that look like they'll need a search get it sooner,
            # without waiting for wxO to decide.
            wait = self.acknowledge_after
            if self.early_filler_after > 0 and questions.likely_needs_lookup(user_text):
                wait = min(wait, self.early_filler_after)
            job.ack_due = now + wait

        async for chunk in self._run(job):
            yield chunk

    async def _run(self, job: _Job) -> AsyncIterator[str]:
        """Speak whatever the job produces. Safe to resume after a cancel."""
        try:
            while True:
                now = time.monotonic()
                # The next "still on it" line follows the previous line with a
                # short natural pause, for as long as there are lines left.
                gap = self.hold_after if job.hold_gap is None else job.hold_gap
                due = job.last_line_ends + gap if job.hold_lines and not job.answered and job.filled else None
                if job.ack_due and not job.answered:
                    due = job.ack_due
                wait = max(0.0, due - now) if due else None

                try:
                    item = await asyncio.wait_for(job.queue.get(), wait)
                except asyncio.TimeoutError:
                    if job.ack_due and not job.answered:
                        job.ack_due = 0.0
                        yield self._acknowledge(job)
                    elif job.hold_lines and not job.answered:
                        line = job.hold_lines.pop(0)
                        log.info("[%s] still looking: %s", self.cid, line)
                        _mark_spoken(job, line, time.monotonic())
                        self._phase("hold")
                        yield _line(line)
                    continue

                if item is _END:
                    break
                kind, value = item

                if kind == "thread":
                    if value != self.thread_id:
                        self.thread_id = value
                        log.info("[%s] wxO thread %s", self.cid, value)
                elif kind == "tool":
                    job.tool_started = time.monotonic()
                    log.info("[%s] tool call: %s (+%.0f ms)", self.cid, value or "?", _ms(job.started))
                    if self._is_specialist(value) and not job.specialist and not job.answered:
                        # Routed to the slower specialist: ask whether they
                        # mind waiting (even after a short filler) and end
                        # the turn. The answer waits for their go-ahead.
                        yield self._ask_to_wait(job)
                        return
                    elif job.ack_due and not job.answered and not job.filled:
                        job.ack_due = 0.0
                        yield self._acknowledge(job)
                elif kind == "tool_done":
                    job.tool_started = 0.0
                    log.info("[%s] tool returned (+%.0f ms)", self.cid, _ms(job.started))
                elif kind == "text" or (kind == "final_text" and not job.answered):
                    # final_text: an agent that doesn't stream sends its whole
                    # reply once, at the end. Speak it unless deltas already did.
                    job.tool_started = 0.0
                    job.ack_due = 0.0
                    if kind == "text":
                        job.streamed = True
                    text = job.spoken.feed(value)
                    if text:
                        if not job.answered:
                            log.info("[%s] first reply text (+%.0f ms)", self.cid, _ms(job.started))
                            self._phase("answer")
                        job.answered = True
                        job.sent.append(text)
                        yield text
                elif kind == "error":
                    job.sent.append(FALLBACK)
                    self._phase("answer")
                    yield _line(FALLBACK)
                    break

            tail = job.spoken.flush()
            if tail:
                job.sent.append(tail)
                yield tail
            job.finished = True
            job.finished_at = time.monotonic()
            if job.sent:
                self._last_agent_text = "".join(job.sent).strip()
            log.info("[%s] turn finished (+%.0f ms)", self.cid, _ms(job.started))
            if job.sent and not self._stream_noted:
                self._stream_noted = True
                if job.streamed:
                    log.info("[%s] wxO is streaming replies", self.cid)
                else:
                    log.warning("[%s] wxO sent the whole reply at once (not streaming): answers start "
                                "later, and the mortgage hand-off is only spotted from the caller's words. "
                                "Check the agent's model in wxO.", self.cid)
            if job.sent:
                said = " ".join("".join(job.sent).split())
                log.info("[%s] agent said: %s", self.cid, said if len(said) <= 200 else said[:200] + "…")
        except (asyncio.CancelledError, GeneratorExit):
            # The SDK cancels us when a new turn arrives. Leave the wxO request
            # running: if that turn is this same question re-sent, we carry on.
            log.info("[%s] turn paused (+%.0f ms)", self.cid, _ms(job.started))
            raise

    def _phase(self, phase: str) -> None:
        if self.on_phase:
            try:
                self.on_phase(phase)
            except Exception:  # the page is a nice-to-have; never break a turn
                log.debug("phase callback failed", exc_info=True)

    def _is_specialist(self, tool_name: str) -> bool:
        return bool(self.specialist_ask and self.specialist_tools and tool_name
                    and self.specialist_tools.search(tool_name))

    def _ask_to_wait(self, job: _Job) -> str:
        """Ask whether the caller minds waiting for the specialist. The turn
        ends after this; their reply decides what happens next."""
        line = self.specialist_ask
        job.specialist = True
        job.hold_lines = []
        job.ack_due = 0.0
        now = time.monotonic()
        job.filled, job.filled_at = True, now
        _mark_spoken(job, line, now)
        self._waiting = job
        log.info("[%s] asking to wait for the specialist: %s (+%.0f ms)", self.cid, line, _ms(job.started))
        self._phase("ask")
        return _line(line)

    def _acknowledge(self, job: _Job) -> str:
        """Say the acknowledgement now, and line up the whisper in case the
        answer is slow to follow."""
        ack = self._pick_acknowledgement()
        if self.still_thinking and self.still_thinking_after > 0:
            job.hold_lines = [self.still_thinking[self._next_still % len(self.still_thinking)]]
            job.hold_gap = self.still_thinking_after
            self._next_still += 1
        now = time.monotonic()
        job.filled, job.filled_at = True, now
        _mark_spoken(job, ack, now)
        log.info("[%s] acknowledgement: %s (+%.0f ms)", self.cid, ack, _ms(job.started))
        self._phase("filler")
        return _line(ack)

    def _pick_acknowledgement(self) -> str:
        """The next acknowledgement in the list, starting again from the first
        once every one has been used."""
        ack = self.acknowledgements[self._next_ack % len(self.acknowledgements)]
        self._next_ack += 1
        return ack

    async def _produce(self, job: _Job) -> None:
        attempts = 2 if self.thread_id else 1
        try:
            for attempt in range(attempts):
                try:
                    async for event in self.wxo.stream(job.text, self.thread_id):
                        if event.kind == "done":
                            break
                        await job.queue.put((event.kind, event.value))
                    return
                except WxoError as e:
                    if attempt + 1 < attempts:
                        # A thread can expire on the wxO side. Start a fresh
                        # one rather than failing the caller.
                        log.warning("[%s] %s; retrying on a new thread", self.cid, e)
                        self.thread_id = None
                        continue
                    raise
        except asyncio.CancelledError:
            raise
        except Exception as e:  # network errors, IAM failures, bad responses
            log.error("[%s] wxO request failed: %s", self.cid, e)
            await job.queue.put(("error", str(e)))
        finally:
            job.queue.put_nowait(_END)


_HESITATIONS = re.compile(r"\b(um+|uh+|erm*|er|hmm+|ah+)\b")


def _normalise(text: str) -> str:
    t = _HESITATIONS.sub(" ", text.lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Words that don't change what's being asked.
_FILLER_WORDS = {
    "a", "an", "the", "and", "or", "so", "but", "like", "yeah", "yes", "okay", "ok", "well",
    "please", "just", "actually", "right", "then", "that", "this", "it", "is", "to", "of",
    "for", "on", "in", "me", "i", "you", "can", "could", "would", "about", "with",
    # question scaffolding: the end of a sentence, not a new subject
    "what", "where", "when", "which", "who", "how", "why", "tell", "know", "are", "do",
    "does", "did", "there", "any", "anything", "get", "go", "want", "wanna", "need",
    "help", "info", "information", "more", "bit", "little", "we", "my", "your", "be",
    "will", "should", "if", "am", "was", "were", "have", "has", "they", "them", "those",
    "these", "some",
}
# A re-send must add at least this many real words to count as a fuller question.
MIN_NEW_WORDS = 1


def _stem(word: str) -> str:
    """Rough stem so "account"/"accounts" and "save"/"saving" match."""
    for suffix in ("ing", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _adds_words(text: str, previous_normalised: str) -> bool:
    """The new transcript adds something real to the one being worked on:
    "ISAs" → "ISAs, what's the rate and how much can I put in". Repeats and
    small wording changes ("account" / "accounts") don't count."""
    if not previous_normalised:
        return False
    before = {_stem(w) for w in previous_normalised.split()}
    added = [w for w in _normalise(text).split() if w not in _FILLER_WORDS and _stem(w) not in before]
    return len(added) >= MIN_NEW_WORDS


def _same_turn(text: str, previous_normalised: str, allow_longer: bool = True) -> bool:
    """The same question again: identical, nearly identical, or a shorter
    version of it. With allow_longer, also a longer version (the caller kept
    talking before we'd answered); once answered, a longer one is new."""
    if not previous_normalised:
        return False
    now = _normalise(text)
    if not now:
        return False
    if now in previous_normalised or (allow_longer and previous_normalised in now):
        return True
    if _same_subject(now, previous_normalised):
        return True
    return difflib.SequenceMatcher(None, now, previous_normalised).ratio() >= SAME_TURN_SIMILARITY


def _same_subject(now: str, previous_normalised: str) -> bool:
    """Every subject word in the new transcript was already in the question,
    and there's at least one: "who do I contact about my mortgage application"
    vs "how do I contact someone about my mortgage application". Small talk ("yes")
    has no subject words, so it never matches."""
    words = [w for w in now.split() if w not in _FILLER_WORDS]
    before = {_stem(w) for w in previous_normalised.split()}
    return bool(words) and all(_stem(w) in before for w in words)


# Roughly how long a line takes to be heard: the voice starting, then
# speech at a relaxed ~150 words a minute.
VOICE_START_SECONDS = 0.35
WORDS_PER_SECOND = 2.5


def _speech_seconds(text: str) -> float:
    return VOICE_START_SECONDS + len(text.split()) / WORDS_PER_SECOND


def _mark_spoken(job: "_Job", line: str, at: float) -> None:
    """Note a line was sent. Lines are spoken one after another, so one sent
    while another is still playing starts when that one ends."""
    starts = max(at, job.last_line_ends)
    job.last_line, job.last_line_at = line, at
    job.last_line_starts = starts
    job.last_line_ends = starts + _speech_seconds(line)


_PHRASE_END = re.compile(r"(?<=[,.;:!?…])\s+")
_CUE = re.compile(r"^\s*(\[[^\]]*\])\s*")


def _unheard(job: "_Job", now: float) -> str:
    """What's left to say of the last filler line when ElevenLabs re-sends the
    turn and drops its audio: the rest of it, from the start of the phrase it
    was cut off in. Nothing once it has been heard in full, except that a
    line sent a moment ago may not have played at all, so it's said again."""
    line = job.last_line
    if not line:
        return ""
    if now >= job.last_line_ends:
        return line if now - job.last_line_at < RESAY_WINDOW else ""
    heard = int(max(0.0, now - job.last_line_starts - VOICE_START_SECONDS) * WORDS_PER_SECOND)
    cue = _CUE.match(line)
    body = line[cue.end():] if cue else line
    phrases = [p for p in _PHRASE_END.split(body) if p.strip()]
    words = 0
    for i, phrase in enumerate(phrases):
        words += len(phrase.split())
        if heard < words:
            if i == 0:
                return line
            rest = " ".join(phrases[i:])
            return f"{cue.group(1)} {rest}" if cue else rest
    return ""


# ElevenLabs speaks a reply in pieces, splitting at punctuation, and holds
# back the last piece until more text arrives: "Let me just check that with
# our mortgage specialist," then a pause, then "it might take a little
# longer." A zero-width space after each line is that "more text", so the
# whole line is spoken straight away. It's silent and invisible.
SPEAK_NOW = "\u200b"


def _line(text: str) -> str:
    return " " + text + " " + SPEAK_NOW


def _ms(since: float) -> float:
    return (time.monotonic() - since) * 1000
