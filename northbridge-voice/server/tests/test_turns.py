"""Tests for the turn logic. They replay a wxO stream in the format the
Northbridge Bank Agent sends (tests/fixtures/savings_accounts.sse), so no
network or keys are needed.

Run from the server folder:  python -m unittest discover tests
"""

import asyncio
import time
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# wxo.py imports httpx at module level; these tests never touch the network.
sys.modules.setdefault("httpx", types.ModuleType("httpx"))

from questions import is_small_talk  # noqa: E402
from speech import SpokenText  # noqa: E402
from sse import WxoEvent, iter_sse_data, parse_payload  # noqa: E402
from turns import Conversation  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "savings_accounts.sse"
THREAD = "00000000-0000-4000-8000-000000000001"
ACK = "Mm, let me see..."


def fixture_events():
    events = []
    with FIXTURE.open(encoding="utf-8") as f:
        for data in iter_sse_data(f):
            events.extend(parse_payload(data))
    return events


class FakeWxo:
    """Replays the recorded stream, pausing where the knowledge base search does."""

    def __init__(self, events, tool_seconds=0.0):
        self.events = events
        self.tool_seconds = tool_seconds
        self.calls = []
        self.closed = 0

    async def stream(self, text, thread_id):
        self.calls.append((text, thread_id))
        try:
            for e in self.events:
                yield e
                if e.kind == "tool":
                    await asyncio.sleep(self.tool_seconds)
        finally:
            self.closed += 1


class instant_speech:
    """Treat filler lines as spoken instantly, so short simulated searches
    are long enough for the follow-up lines."""

    def __enter__(self):
        import turns
        self.saved = turns.VOICE_START_SECONDS, turns.WORDS_PER_SECOND
        turns.VOICE_START_SECONDS, turns.WORDS_PER_SECOND = 0.0, 1000.0

    def __exit__(self, *exc):
        import turns
        turns.VOICE_START_SECONDS, turns.WORDS_PER_SECOND = self.saved


def collect(convo, text):
    async def go():
        return [c async for c in convo.reply(text)]
    return asyncio.run(go())


def chunks_of(chunks):
    return [c.replace("\u200b", "").strip() for c in chunks]


async def cut_off(convo, text, after_chunks):
    """Start answering `text`, then get cancelled after a few chunks, the
    way the SDK cancels a turn when the next transcript arrives."""
    gen = convo.reply(text)
    got = []
    if after_chunks:
        async for c in gen:
            got.append(c)
            if len(got) >= after_chunks:
                break
    else:
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
    await gen.aclose()
    return got


# ── stream parsing and speech clean-up ───────────────────────────────────


class ParseTests(unittest.TestCase):
    def test_kinds(self):
        events = fixture_events()
        kinds = [e.kind for e in events if e.kind != "thread"]
        self.assertEqual(kinds[:2], ["tool", "tool_done"])
        self.assertTrue(all(k == "text" for k in kinds[2:-1]))
        self.assertEqual(kinds[-1], "final_text")
        self.assertEqual(events[1].value, "northbridge_bank_products_and_services")

    def test_thread_id(self):
        self.assertEqual({e.value for e in fixture_events() if e.kind == "thread"}, {THREAD})

    def test_completed_message_not_repeated_as_text(self):
        text = "".join(e.value for e in fixture_events() if e.kind == "text")
        self.assertEqual(text.count("Sure thing!"), 1)


class SpokenTextTests(unittest.TestCase):
    def speak(self, chunks):
        s = SpokenText()
        return "".join(s.feed(c) for c in chunks) + s.flush()

    def test_markdown_removed(self):
        out = self.speak("".join(e.value for e in fixture_events() if e.kind == "text"))
        self.assertNotIn("*", out)
        self.assertNotIn("\n", out)
        self.assertIn("whenever you like. Fixed Rate Saver", out)

    def test_split_tokens(self):
        self.assertEqual(self.speak(["- **", "E", "asy Access", "**", " opens", "\n", "- next"]), "Easy Access opens. next")

    def test_links_and_urls(self):
        out = self.speak(["See [the savings page](https://northbridge.example/sa", "vings) or www.northbridge.example."])
        self.assertEqual(out, "See the savings page or the Northbridge website.")


# ── small talk ───────────────────────────────────────────────────────────


class SmallTalkTests(unittest.TestCase):
    def test_thanks_and_goodbyes(self):
        for t in ("thanks", "Thanks a lot. Bye now.",
                  "Thank you. That's, um, that's great. You've been really helpful today.",
                  "Okay, um, yeah, we can go back to English now. Thanks. Uh, you were really helpful. Thank you.",
                  "ORB_CLICKED"):
            self.assertTrue(is_small_talk(t), t)

    def test_questions(self):
        for t in ("thanks, and what's the ISA rate?", "What can you tell me about the Cash ISA?",
                  "How do I change or cancel a standing order?"):
            self.assertFalse(is_small_talk(t), t)

class ResendTests(unittest.TestCase):
    def test_resend_carries_on_instead_of_restarting(self):
        # from the logs: the same question arrived four times, each a second
        # after the filler line played
        wxo = FakeWxo(fixture_events(), tool_seconds=0.2)
        convo = Conversation(wxo, hold_after=0, acknowledgements=[ACK])

        async def go():
            first = await cut_off(convo, "And what documents do I need to open a current account?", 1)
            await cut_off(convo, "And what document do I need to open a current account?", 0)
            third = [c async for c in convo.reply("And what documents do I need to open a current account?")]
            return first, third

        first, third = asyncio.run(go())
        self.assertEqual(len(wxo.calls), 1)          # one search, not four
        self.assertEqual(chunks_of(first), [ACK])
        self.assertLessEqual(chunks_of(third).count(ACK), 1)  # re-said at most once per copy
        self.assertTrue("".join(third).rstrip().endswith("details on?"))

    def test_filler_dropped_by_a_resend_is_said_again(self):
        # from the logs: the filler line went out at +883 ms, the re-send came
        # 56 ms later and ElevenLabs dropped the line, leaving silence
        wxo = FakeWxo(fixture_events(), tool_seconds=0.3)
        convo = Conversation(wxo, hold_after=0, acknowledgements=[ACK])

        async def go():
            first = await cut_off(convo, "Okay, yeah, let's start with, uh, savings accounts.", 1)
            again = [c async for c in convo.reply("Okay, yeah, let's start with, uh, savings accounts.")]
            return first, again

        first, again = asyncio.run(go())
        self.assertEqual(chunks_of(first), [ACK])
        self.assertEqual(chunks_of(again)[0], ACK)            # said again
        self.assertEqual(chunks_of(again).count(ACK), 1)      # but only once
        self.assertEqual(len(wxo.calls), 1)

    def test_question_that_grows_before_any_answer_is_asked_in_full(self):
        # from the logs: the first half of the question went to wxO, then the
        # whole question arrived and was ignored
        wxo = FakeWxo(fixture_events(), tool_seconds=0.3)
        convo = Conversation(wxo, hold_after=0, acknowledgements=[ACK])

        async def go():
            await cut_off(convo, "Yeah, let's start with, uh, ISAs.", 1)
            return [c async for c in convo.reply(
                "Yeah, let's start with, uh, ISAs. What's the rate and how much can I put in?")]

        chunks = asyncio.run(go())
        self.assertEqual([c[0] for c in wxo.calls], [
            "Yeah, let's start with, uh, ISAs.",
            "Yeah, let's start with, uh, ISAs. What's the rate and how much can I put in?",
        ])
        self.assertLessEqual(chunks_of(chunks).count(ACK), 1)   # the filler isn't said twice
        self.assertTrue("".join(chunks).rstrip().endswith("details on?"))

    def test_flip_flopping_transcripts_are_one_question(self):
        # from the logs: ElevenLabs alternated between two versions of one
        # question, and each switch back started a new question
        wxo = FakeWxo(fixture_events(), tool_seconds=0.3)
        convo = Conversation(wxo, hold_after=0)

        async def go():
            await cut_off(convo, "Who would I contact about a mortgage application?", 1)
            await cut_off(convo, "How would I contact someone about a mortgage application or account?", 0)
            await cut_off(convo, "Who would I contact about a mortgage application?", 0)
            return [c async for c in convo.reply("How would I contact someone about a mortgage application or account?")]

        asyncio.run(go())
        self.assertLessEqual(len(wxo.calls), 2)       # first version, then the full one

    def test_small_talk_never_counts_as_the_same_question(self):
        import turns
        self.assertFalse(turns._same_turn("yes", turns._normalise("what ISAs do you have")))
        self.assertFalse(turns._same_turn("and ISAs?", turns._normalise("what savings accounts do you have")))

    def test_answer_already_under_way_is_not_restarted(self):
        wxo = FakeWxo(fixture_events(), tool_seconds=0)
        convo = Conversation(wxo, hold_after=0)

        async def go():
            await cut_off(convo, "what ISAs do you have", 8)   # answer text has started
            return [c async for c in convo.reply("what ISAs do you have and what are the rates")]

        asyncio.run(go())
        self.assertEqual(len(wxo.calls), 1)

    def test_longer_version_while_answering_carries_on(self):
        wxo = FakeWxo(fixture_events(), tool_seconds=0.2)
        convo = Conversation(wxo, hold_after=0)

        async def go():
            await cut_off(convo, "Okay. And, um, what do I need to bring to open an account in branch?", 1)
            return [c async for c in convo.reply(
                "Okay. And, um, what do I need to bring to open an account in branch? Can you help me with that?")]

        asyncio.run(go())
        self.assertEqual(len(wxo.calls), 1)

    def test_shorter_resend_after_answer_replays(self):
        wxo = FakeWxo(fixture_events())
        convo = Conversation(wxo, hold_after=0)
        collect(convo, "Yeah, let's start with, um, ISAs. Tell me a bit about the ISAs.")
        again = collect(convo, "Yeah, let's start with, um, ISAs.")
        self.assertEqual(len(wxo.calls), 1)
        self.assertIn("details on?", "".join(again))

    def test_longer_resend_just_after_answer_is_a_repeat(self):
        # from the logs: answered, then ElevenLabs re-sent the longer version
        # 1.5 s later and the agent answered all over again
        wxo = FakeWxo(fixture_events())
        convo = Conversation(wxo, hold_after=0)
        collect(convo, "Okay, let's start with saving with Northbridge.")
        again = collect(convo, "Okay, let's start with saving with Northbridge. What can you tell me about that?")
        self.assertEqual(len(wxo.calls), 1)
        self.assertIn("details on?", "".join(again))

    def test_longer_question_later_on_is_new(self):
        import turns
        wxo = FakeWxo(fixture_events())
        convo = Conversation(wxo, hold_after=0)
        old = turns.LATE_RESEND_WINDOW
        turns.LATE_RESEND_WINDOW = 0.0
        try:
            collect(convo, "ISAs")
            collect(convo, "ISAs for children under 18 opened by a parent")
        finally:
            turns.LATE_RESEND_WINDOW = old
        self.assertEqual(len(wxo.calls), 2)

    def test_resend_mid_answer_is_not_a_new_question(self):
        wxo = FakeWxo(fixture_events(), tool_seconds=0)
        convo = Conversation(wxo, hold_after=0)

        async def go():
            await cut_off(convo, "Hey, um, what can you help me with?", 6)
            return [c async for c in convo.reply("Hey. Um, what can you help me with?")]

        asyncio.run(go())
        self.assertEqual(len(wxo.calls), 1)

    def test_genuine_new_question_cancels_old_search(self):
        wxo = FakeWxo(fixture_events(), tool_seconds=0.5)
        convo = Conversation(wxo, hold_after=0)

        async def go():
            await cut_off(convo, "What savings accounts do you have?", 0)
            await asyncio.sleep(0.05)
            out = [c async for c in convo.reply("what's the overdraft fee")]
            await asyncio.sleep(0.05)
            return out

        asyncio.run(go())
        self.assertEqual(len(wxo.calls), 2)
        self.assertGreaterEqual(wxo.closed, 2)


# ── filler lines while wxO works ─────────────────────────────────────────


class FillerTests(unittest.TestCase):
    """A filler line ("Mm-hmm.") only if the answer is slow to start, then a
    whisper if it's slower still."""

    def convo(self, tool_seconds=0.3, **kw):
        kw.setdefault("acknowledgements", ["Mm-hmm."])
        kw.setdefault("acknowledge_after", 0.1)
        kw.setdefault("still_thinking", [])
        wxo = FakeWxo(fixture_events(), tool_seconds=tool_seconds)
        return wxo, Conversation(wxo, hold_after=0, **kw)

    def test_slow_answer_gets_mm_hmm_then_the_answer(self):
        _, convo = self.convo()
        chunks = chunks_of(collect(convo, "what ISAs do you have?"))
        self.assertEqual(chunks[:2], ["Mm-hmm.", "Sure"])

    def test_filler_waits_for_the_search_to_start(self):
        # from the logs: "What can you help me with?" took 0.7 s with no
        # search, and still got a filler under the old 0.6 s rule
        class SlowNoSearch(FakeWxo):
            async def stream(self, text, thread_id):
                await asyncio.sleep(0.3)        # slower than 0.6 s would be, scaled down
                for e in self.events:
                    if e.kind in ("thread", "text"):
                        yield e

        convo = Conversation(SlowNoSearch(fixture_events()), hold_after=0,
                             acknowledgements=["Mm-hmm."], acknowledge_after=1.0)
        self.assertEqual(chunks_of(collect(convo, "What can you help me with?"))[0], "Sure")

    def test_lookup_questions_get_the_filler_before_wxo_decides(self):
        # from the logs: the joint account question waited 1.5 s in silence
        # because wxO took 1.7 s to decide to search
        class SlowToDecide(FakeWxo):
            async def stream(self, text, thread_id):
                await asyncio.sleep(0.4)
                async for e in FakeWxo.stream(self, text, thread_id):
                    yield e

        convo = Conversation(SlowToDecide(fixture_events(), tool_seconds=0.1), hold_after=0,
                             acknowledgements=["Mm-hmm."], acknowledge_after=5.0, early_filler_after=0.1)
        chunks = chunks_of(collect(convo, "Can I open a joint savings account with my partner online?"))
        self.assertEqual(chunks[:2], ["Mm-hmm.", "Sure"])

    def test_which_questions_look_like_lookups(self):
        from questions import likely_needs_lookup
        for q in ("Can I open a joint savings account with my partner online?",
                  "what ISAs do you have and what are the rates?",
                  "how do I change or cancel a standing order?"):
            self.assertTrue(likely_needs_lookup(q), q)
        for q in ("What can you help me with?", "Hey, what can you do?", "Can you translate that in French?",
                  "Could you say that again?", "Thanks so much, bye", "yes please", "who am I speaking to?"):
            self.assertFalse(likely_needs_lookup(q), q)

    def test_search_starting_triggers_the_filler_straight_away(self):
        _, convo = self.convo(tool_seconds=0.3, acknowledge_after=5.0)   # backstop far away
        chunks = chunks_of(collect(convo, "what ISAs do you have?"))
        self.assertEqual(chunks[:2], ["Mm-hmm.", "Sure"])

    def test_phases_are_reported_for_the_page(self):
        phases = []
        wxo = FakeWxo(fixture_events(), tool_seconds=0.3)
        convo = Conversation(wxo, hold_after=0, acknowledgements=["Mm-hmm."], acknowledge_after=5.0,
                             still_thinking=["[whispers] Hmm..."], still_thinking_after=0.05,
                             on_phase=phases.append)
        with instant_speech():
            collect(convo, "what ISAs do you have?")
        self.assertEqual(phases, ["filler", "hold", "answer"])

    def test_quick_answer_gets_nothing_in_front(self):
        # from the logs: "What can you help me with?" was answered in 0.5 s,
        # with an unneeded "Mm-hmm" in front of it
        events = [e for e in fixture_events() if e.kind in ("thread", "text")]
        convo = Conversation(FakeWxo(events), hold_after=0, acknowledgements=["Mm-hmm."], acknowledge_after=0.2)
        self.assertEqual(chunks_of(collect(convo, "What can you help me with?"))[0], "Sure")

    def test_no_mm_hmm_for_thanks_or_the_greeting(self):
        for text in ("Thanks a lot, bye now.", "ORB_CLICKED"):
            _, convo = self.convo()
            self.assertNotEqual(chunks_of(collect(convo, text))[0], "Mm-hmm.", text)

    def test_mm_hmm_once_even_if_the_question_is_resent(self):
        import turns
        wxo, convo = self.convo(tool_seconds=0.4)

        async def go():
            await cut_off(convo, "what ISAs do you have", 1)
            await asyncio.sleep(1)          # long after it played
            return [c async for c in convo.reply("what ISAs do you have")]

        old = turns.RESAY_WINDOW
        turns.RESAY_WINDOW = 0.5
        try:
            again = chunks_of(asyncio.run(go()))
        finally:
            turns.RESAY_WINDOW = old
        self.assertNotIn("Mm-hmm.", again)

    def test_slow_answer_gets_one_whispered_mm_hmm(self):
        _, convo = self.convo(tool_seconds=0.5, still_thinking=["[whispers] Mm-hmm..."], still_thinking_after=0.1)
        with instant_speech():
            chunks = chunks_of(collect(convo, "what ISAs do you have?"))
        self.assertEqual(chunks[:3], ["Mm-hmm.", "[whispers] Mm-hmm...", "Sure"])

    def test_fairly_quick_answer_gets_no_whisper(self):
        _, convo = self.convo(tool_seconds=0.3, still_thinking=["[whispers] Mm-hmm..."], still_thinking_after=1.0)
        with instant_speech():
            chunks = chunks_of(collect(convo, "what ISAs do you have?"))
        self.assertEqual(chunks[:2], ["Mm-hmm.", "Sure"])

    def test_acknowledgements_and_whispers_are_used_in_order_then_start_again(self):
        _, convo = self.convo(tool_seconds=0.4,
                              acknowledgements=["Mm-hmm.", "[softly] Okay.", "Right."],
                              still_thinking=["[whispers] Mm-hmm...", "[whispers] Mhm..."],
                              still_thinking_after=0.05)
        questions = ["what ISAs do you have", "how much is the overdraft fee", "when is the branch open",
                     "how do I open a savings account"]
        with instant_speech():
            pairs = [tuple(chunks_of(collect(convo, q))[:2]) for q in questions]
        self.assertEqual(pairs, [
            ("Mm-hmm.", "[whispers] Mm-hmm..."),
            ("[softly] Okay.", "[whispers] Mhm..."),
            ("Right.", "[whispers] Mm-hmm..."),
            ("Mm-hmm.", "[whispers] Mhm..."),
        ])

    def test_second_turn_reuses_thread(self):
        wxo = FakeWxo(fixture_events())
        convo = Conversation(wxo, hold_after=0)
        collect(convo, "savings accounts?")
        collect(convo, "what's the overdraft fee")
        self.assertEqual([c[1] for c in wxo.calls], [None, THREAD])

    def test_failure_is_spoken_kindly(self):
        class Broken:
            async def stream(self, text, thread_id):
                raise RuntimeError("network down")
                yield  # pragma: no cover

        chunks = collect(Conversation(Broken(), hold_after=0, quick_filler=False), "hi")
        self.assertIn("trouble reaching", "".join(chunks))


    def test_non_streaming_agent_is_still_spoken(self):
        # Some agents send no deltas: just one completed message at the end.
        reply = "Hello, I'm the Northbridge assistant. How can I help?"
        wxo = FakeWxo([WxoEvent("thread", THREAD), WxoEvent("final_text", reply), WxoEvent("done")])
        chunks = collect(Conversation(wxo, hold_after=0, quick_filler=False), "ORB_CLICKED")
        self.assertIn("Northbridge assistant", "".join(chunks))

    def test_final_text_not_repeated_after_deltas(self):
        events = fixture_events()
        streamed = "".join(e.value for e in events if e.kind == "text")
        chunks = "".join(collect(Conversation(FakeWxo(events), hold_after=0, quick_filler=False), "hi"))
        self.assertEqual(chunks.count(streamed[:30]), 1)


def talk(convo, *turns):
    """Several turns of one conversation, in one event loop (as for real, so
    work left running between turns carries on). A number is a pause."""
    async def go():
        out = []
        for turn in turns:
            if isinstance(turn, (int, float)):
                await asyncio.sleep(turn)
            else:
                out.append(chunks_of([c async for c in convo.reply(turn)]))
        return out
    return asyncio.run(go())


ASK = "That one might take a little longer to check, is that okay?"
DECLINED = "No problem. Is there anything else I can help with?"
Q5 = "I earn 70k, I've got 40k saved and no debts. How much could I borrow?"


def routed_to(tool_name):
    """The recorded stream, but with wxO handing off to `tool_name`."""
    return [WxoEvent("tool", tool_name) if e.kind == "tool" else e for e in fixture_events()]


class SpecialistTests(unittest.TestCase):
    """Questions for the slower Mortgage Affordability Agent: ask whether the
    caller minds waiting, then hold music on their go-ahead."""

    def convo(self, events, tool_seconds=0.3, wait_before=0.0, phases=None, **kw):
        class Wxo(FakeWxo):
            async def stream(self, text, thread_id):
                await asyncio.sleep(wait_before)      # wxO deciding where to route
                async for e in FakeWxo.stream(self, text, thread_id):
                    yield e

        import re
        kw.setdefault("acknowledgements", ["Mm-hmm."])
        kw.setdefault("acknowledge_after", 5.0)
        kw.setdefault("early_filler_after", 0.1)
        kw.setdefault("specialist_ask", ASK)
        kw.setdefault("specialist_declined", DECLINED)
        kw.setdefault("specialist_tools", re.compile("mortgage|affordab", re.I))
        wxo = Wxo(events, tool_seconds=tool_seconds)
        convo = Conversation(wxo, hold_after=0, on_phase=(phases.append if phases is not None else None), **kw)
        return wxo, convo

    def test_which_questions_look_like_affordability(self):
        from turns import looks_like_affordability as yes
        for q in (Q5,
                  "£70k income, £40k saved, no debts, how much could I borrow?",
                  "So I earn 70,000 a year, and I've got 40,000 saved and no debt. How much could I borrow?",
                  "My salary is 55,000 pounds, what mortgage could I afford?",
                  "We earn seventy thousand between us, how big a mortgage could we get?",
                  "I make 45 grand a year, can I afford a mortgage?"):
            self.assertTrue(yes(q), q)
        for q in ("What mortgages do you have for first-time buyers?",
                  "What's the rate on the five year fix with a 10% deposit?",
                  "How much could I borrow?",                     # the agent asks for figures first
                  "I got a text saying I can borrow £5,000 instantly, is it a scam?",
                  "Can I get a mortgage with a £20,000 deposit?",
                  "What's the easy access saver rate?"):
            self.assertFalse(yes(q), q)

    def test_figures_given_after_the_agent_asks_for_them(self):
        asks_income = "To work out how much you could borrow, what's your annual income and how much have you saved?"
        events = [WxoEvent("thread", THREAD), WxoEvent("text", asks_income), WxoEvent("done")]
        wxo, convo = self.convo(events)
        first, second = talk(convo, "How much could I borrow?", "I earn 70k and I've got 40k saved, no debts.")
        self.assertNotIn(ASK, first)                    # the agent asks for figures first
        self.assertEqual(second, [ASK])                 # the figures go to the specialist

    def test_figures_after_a_product_answer_are_not_for_the_specialist(self):
        product = "We offer two and five year fixed mortgages. Would you like to hear the rates?"
        events = [WxoEvent("thread", THREAD), WxoEvent("text", product), WxoEvent("done")]
        wxo, convo = self.convo(events)
        _, second = talk(convo, "What mortgages do you have?", "I've got a £20,000 deposit.")
        self.assertNotIn(ASK, second)

    def test_hold_music_works_when_wxo_does_not_stream(self):
        # No deltas and no hand-off signal: the whole answer arrives at the end.
        phases = []
        answer = "Based on that, you could borrow up to £315,000."
        events = [WxoEvent("thread", THREAD), WxoEvent("final_text", answer), WxoEvent("done")]
        wxo, convo = self.convo(events, wait_before=0.3, phases=phases)
        first, second = talk(convo, Q5, "Sure.")
        self.assertEqual(first, [ASK])
        self.assertIn("£315,000", "".join(second))
        self.assertEqual(phases, ["ask", "music", "answer"])

    def test_go_ahead_and_no_thanks(self):
        from turns import is_go_ahead, is_no_thanks
        for t in ("Sure.", "Yeah, that's fine.", "Okay", "Yes please", "No problem", "Sure, go ahead.",
                  "That's okay", "Yeah sure", "I don't mind", "Of course"):
            self.assertTrue(is_go_ahead(t), t)
            self.assertFalse(is_no_thanks(t), t)
        for t in ("No thanks", "Nope", "Don't worry about it", "Never mind", "No, leave it"):
            self.assertTrue(is_no_thanks(t), t)
            self.assertFalse(is_go_ahead(t), t)
        for t in ("What's the ISA rate?", "Actually what about savings accounts?",
                  "No, but what's the easy access rate?"):
            self.assertFalse(is_go_ahead(t), t)

    def test_asks_then_ends_the_turn_while_wxo_works(self):
        phases = []
        wxo, convo = self.convo(routed_to("mortgage_affordability_agent"), tool_seconds=0.5, phases=phases)
        t0 = time.monotonic()
        [chunks] = talk(convo, Q5, 0.01)
        self.assertEqual(chunks, [ASK])                 # nothing else: the turn ends here
        self.assertLess(time.monotonic() - t0, 0.3)     # without waiting for the answer
        self.assertEqual(phases, ["ask"])
        self.assertEqual(len(wxo.calls), 1)             # wxO was asked straight away

    def test_sure_plays_hold_music_then_the_answer(self):
        phases = []
        wxo, convo = self.convo(routed_to("mortgage_affordability_agent"), tool_seconds=0.5, phases=phases)
        asked, answer = talk(convo, Q5, 0.1, "Sure.")
        self.assertEqual(asked, [ASK])
        self.assertEqual(answer[0], "Sure")              # the answer (the fixture starts "Sure thing!")
        self.assertNotIn(ASK, answer)
        self.assertEqual(phases, ["ask", "music", "answer"])
        self.assertEqual(len(wxo.calls), 1)             # "sure" isn't sent to wxO

    def test_answer_ready_before_the_go_ahead_needs_no_music(self):
        phases = []
        _, convo = self.convo(routed_to("mortgage_affordability_agent"), tool_seconds=0.0, phases=phases)
        _, answer = talk(convo, Q5, 0.2, "Yeah, that's fine.")
        self.assertEqual(answer[0], "Sure")
        self.assertEqual(phases, ["ask", "answer"])

    def test_no_thanks(self):
        _, convo = self.convo(routed_to("mortgage_affordability_agent"), tool_seconds=0.5)
        _, reply = talk(convo, Q5, "No thanks")
        self.assertEqual(reply, [DECLINED])

    def test_a_different_question_instead_is_answered(self):
        wxo, convo = self.convo(fixture_events(), tool_seconds=0.1)
        _, reply = talk(convo, Q5, 0.05, "Actually, what's the easy access saver rate?")
        self.assertIn("Sure", reply)                     # answered normally
        self.assertEqual(len(wxo.calls), 2)

    def test_routing_to_the_specialist_asks_too(self):
        # Worded so the question check doesn't spot it: wxO's routing does.
        phases = []
        _, convo = self.convo(routed_to("Mortgage_Affordability_Agent"), wait_before=0.3,
                              acknowledge_after=0.1, phases=phases)
        asked, answer = talk(convo, "and with my partner's income on top?", "okay")
        self.assertEqual(asked, ["Mm-hmm.", ASK])
        self.assertEqual(answer[0], "Sure")
        self.assertEqual(phases, ["filler", "ask", "music", "answer"])

    def test_product_questions_still_get_the_usual_filler(self):
        _, convo = self.convo(fixture_events())   # a knowledge base search
        [chunks] = talk(convo, "What mortgages do you have for first-time buyers?")
        self.assertEqual(chunks[:2], ["Mm-hmm.", "Sure"])

    def test_question_resent_while_waiting_for_the_go_ahead(self):
        import turns
        _, convo = self.convo(routed_to("mortgage_affordability_agent"), tool_seconds=0.5)
        saved = turns.RESAY_WINDOW
        turns.RESAY_WINDOW = 0.01
        try:
            with instant_speech():                      # the question is heard in full at once
                asked, again, answer = talk(convo, Q5, 0.05, Q5, "sure")
        finally:
            turns.RESAY_WINDOW = saved
        self.assertEqual(asked, [ASK])
        self.assertEqual(again, [])                     # still waiting for the go-ahead
        self.assertEqual(answer[0], "Sure")

    def test_go_ahead_resent_carries_on(self):
        wxo, convo = self.convo(routed_to("mortgage_affordability_agent"), tool_seconds=0.6)

        async def go():
            [c async for c in convo.reply(Q5)]
            await cut_off(convo, "Sure.", 0)            # cancelled during the music
            return chunks_of([c async for c in convo.reply("Sure.")])

        chunks = asyncio.run(go())
        self.assertEqual(chunks[0], "Sure")
        self.assertEqual(len(wxo.calls), 1)

    def test_off_without_an_ask_line(self):
        _, convo = self.convo(routed_to("mortgage_affordability_agent"), specialist_ask="")
        [chunks] = talk(convo, Q5)
        self.assertEqual(chunks[:2], ["Mm-hmm.", "Sure"])


if __name__ == "__main__":
    unittest.main()
