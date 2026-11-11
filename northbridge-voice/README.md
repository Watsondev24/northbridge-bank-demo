# Northbridge Bank voice assistant

A voice front end for the Northbridge Bank Agent in watsonx Orchestrate (wxO).
The Northbridge site is on the left and a voice orb on the right: click
**Start conversation** and talk to the agent.

ElevenLabs Speech Engine handles the microphone, speech-to-text, turn-taking
and the voice. This project connects it to wxO, keeps the conversation
natural while the agents work, and draws the orb.

```
Browser ──── GET /api/token ─────────────► this server ── WebRTC token ─► ElevenLabs
   │
   └── WebRTC audio ──► ElevenLabs (STT, turns, TTS)
                            │  each finished user turn
                            ▼
                        wss://<your ngrok address>/ws  ──►  this server
                            │  latest user message + thread id
                            ▼
                        watsonx Orchestrate  /v2/orchestrate/{agent}/chat/completions
                            │  streamed reply
                            ▼
                        cleaned for speech ──► ElevenLabs TTS ──► Browser
```

One process serves the page, issues conversation tokens and hosts the Speech
Engine socket. It runs on your laptop; ngrok gives ElevenLabs a public address
to reach it.

## What happens in a conversation

1. **Start conversation.** The browser asks for the microphone, gets a token
   from the server and joins the call. It sends `ORB_CLICKED` as the first
   message, which the agent's instructions turn into a greeting.
2. **You ask something.** While wxO works, a short filler line plays
   ("Hm...", "Let me have a look...") as soon as it starts searching, and a
   quieter one if the answer is slow. Thanks and goodbyes get no filler.
3. **The answer streams back.** Bold, lists and links are cleaned out as it
   arrives, so nothing like "asterisk" or a URL is read aloud.
4. **Borrowing estimates take longer.** They go to the Mortgage Agent, which
   runs outside wxO on Amazon Bedrock AgentCore. The assistant asks "That one
   might take a little longer to check, is that okay?". If the caller says
   yes, hold music plays (with the microphone muted) until the answer starts.
5. **Talk over it any time.** The agent stops and the wxO request is
   cancelled. If ElevenLabs sends the same question twice, which happens after
   a pause mid-sentence, the search already running carries on.

The wxO thread lives with the call, so the agent remembers what was said, and
nothing is kept on the server afterwards.

## What you need

- **watsonx Orchestrate** with the Northbridge Bank Agent, its knowledge base
  and its two collaborators (the Fraud & Scam Awareness Agent and the Mortgage
  Agent). You'll need the instance URL, the agent's ID and an API key, all
  under Settings → API details.
- **An ElevenLabs** account and API key.
- **Python 3.10+, Node.js 20.19+ and [ngrok](https://ngrok.com)** (a free
  account is fine).

## Set up (once)

**1. Give the agent its voice instructions.** Paste the block in
[`wxo-agent-instructions.md`](wxo-agent-instructions.md) into the Northbridge
Bank Agent's Behavior / Instructions, save, and **deploy**. The app always
talks to the deployed version, not the draft.

**2. Fill in your settings.**

```bash
cp .env.example .env
```

Fill in `WXO_INSTANCE_URL`, `WXO_AGENT_ID`, `WXO_API_KEY` and
`ELEVENLABS_API_KEY`, and optionally `ELEVENLABS_VOICE_ID`. Leave
`ELEVENLABS_SPEECH_ENGINE_ID` empty for now. Never commit `.env`.

**3. Install and build.**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
cd client && npm install && npm run build && cd ..
```

## Run it

Use three Terminal tabs, all in this folder.

**Tab 1: the server**

```bash
source .venv/bin/activate
python -m uvicorn app:app --app-dir server --port 8080
```

**Tab 2: ngrok**

```bash
ngrok http 8080
```

Copy the `https://….ngrok-free.app` address next to Forwarding.

**Tab 3: point ElevenLabs at it**

```bash
source .venv/bin/activate
python server/create_engine.py https://YOUR-ADDRESS.ngrok-free.app
```

- **The first time**, it creates the Speech Engine and prints
  `ELEVENLABS_SPEECH_ENGINE_ID=seng_…`. Add that line to `.env` and restart
  the server in tab 1.
- **After that**, run it again whenever the ngrok address changes (each time
  ngrok restarts). It updates the same engine, so the ID never changes.

Open <http://localhost:8080>, click **Start conversation**, allow the
microphone, and wait for the greeting before you speak.

### Things to try

| Ask | Goes to |
|---|---|
| "What savings accounts do you have?" | The knowledge base |
| "I got a text saying my account is locked and I need to verify my details. Is it a scam?" | The Fraud & Scam Awareness Agent |
| "I earn £70k, I've got £40k saved and no debts. How much could I borrow?" | The Mortgage Agent, with the "is that okay?" question and hold music |

### Reading the server log

Each turn logs what the caller said (`user:`), any filler line, the tools and
agents wxO calls (`tool call:`), when the reply started and what the agent
said (`agent said:`). After the first reply of each call it also logs either
`wxO is streaming replies` or a warning that wxO sent the reply all at once
(see Troubleshooting).

## Settings

All in `.env`; `.env.example` explains each one.

| Variable | |
|---|---|
| `WXO_INSTANCE_URL`, `WXO_AGENT_ID`, `WXO_API_KEY` | Required. From Settings → API details in wxO |
| `ELEVENLABS_API_KEY` | Required |
| `ELEVENLABS_SPEECH_ENGINE_ID` | Printed by `create_engine.py` the first time |
| `ELEVENLABS_VOICE_ID` | Optional. Applied by `create_engine.py` |
| `FILLERS` | Optional. The lines played while wxO searches, separated by `\|` |
| `SPECIALIST_ASK` | Optional. The question asked before a borrowing estimate; empty turns it and the hold music off |
| `TURN_EAGERNESS` | Optional. `patient`, `normal` or `eager`: how soon the caller's turn counts as finished. Applied by `create_engine.py` |

Finer timing (how soon fillers play, the quieter follow-up lines, the hold
music trigger) is set at the top of `server/app.py`.

## Troubleshooting

| What you see | What to do |
|---|---|
| The orb starts, then the call ends straight away, and the server log has no `WebSocket /ws [accepted]` | The ngrok address has changed. Run `create_engine.py` with the new one |
| The page says "Client not built" | Run `cd client && npm install && npm run build`, then restart the server |
| `address already in use` when starting the server | An old server is still running: `lsof -ti tcp:8080 \| xargs kill` |
| The greeting is "No action required", or answers sound like chat replies | The deployed agent doesn't have the voice instructions. Paste them in, save and **deploy** |
| The greeting gets cut off | The microphone heard you or background noise. Stay quiet until she's said hello |
| Silence after every question, with no `agent said:` in the log | wxO is returning nothing. A control whose endpoint is offline will do this, because controls fail closed. Try the agent in the wxO chat to see the error |
| The log warns that wxO sent the reply all at once | The agent's model isn't streaming. Answers still play, but start later. We saw this with the Bedrock-hosted gpt-oss-120b; the Groq-hosted one streams |
| The agent says it's having trouble reaching Northbridge | The wxO request failed. Look for `wxO request failed` in the log: 401 means the API key, 404 the instance URL or agent ID |
| "Microphone access is blocked" | Allow the microphone for localhost in the browser's site settings |

## Security

- Both API keys stay on the server. The browser only gets a short-lived
  conversation token.
- `/ws` only accepts connections signed by ElevenLabs, so other people can't
  connect to it through your ngrok address.
- ngrok makes the page public while it runs, so each visitor can start at most
  12 conversations a minute, to protect your ElevenLabs credit.
- Speech is capped at 8,192 characters before it reaches the agent.

## Project layout

```
├── wxo-agent-instructions.md   the Northbridge Bank Agent's voice instructions
├── .env.example
├── client/                     the page (Vite, no framework)
│   ├── index.html              the Northbridge site and the orb
│   ├── public/hold-music.mp3
│   └── src/
│       ├── orb.js              the dot-cloud orb and its states
│       ├── voice.js            the ElevenLabs session and the orb's state
│       ├── main.js             wires the two together
│       └── styles.css
└── server/
    ├── app.py                  FastAPI: /api/token, /ws, the page; settings
    ├── turns.py                one call: wxO thread, fillers, re-sends, the mortgage hand-off
    ├── questions.py            spots small talk and questions that need a search
    ├── wxo.py                  IAM token and streaming chat/completions
    ├── sse.py                  parses wxO's stream (text, tool calls, thread id)
    ├── speech.py               strips markdown and links from the reply
    ├── create_engine.py        creates or re-points the ElevenLabs Speech Engine
    └── tests/                  replay a recorded wxO stream; no keys needed
```

## Developing

Tests run without network access or keys:

```bash
cd server && python -m unittest discover tests
```

For work on the page, `npm run dev` in `client/` serves it on port 5173 and
passes `/api` through to the server on 8080. In that mode,
`__orbManual('thinking')` in the browser console drives the orb without a
call, and `__orbManual(false)` hands control back.
