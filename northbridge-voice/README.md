# Northbridge Bank voice assistant

The Northbridge site on the left, the voice assistant on the right. Tap the
orb, talk to the Northbridge Banking Assistant in watsonx Orchestrate, hear it
answer. ElevenLabs Speech Engine handles the microphone, speech-to-text,
turn-taking and the voice. This project connects it to wxO and draws the orb.

```
Browser ──── GET /api/token ─────────────► this server ── WebRTC token ─► ElevenLabs
   │                                                                     
   └── WebRTC audio ──► ElevenLabs (STT, turns, TTS)                   
                            │  each finished user turn                 
                            ▼                                          
                        wss://<this server>/ws                         
                            │  latest user message + thread id         
                            ▼                                          
                        watsonx Orchestrate  /v2/orchestrate/{agent}/chat/completions
                            │  streamed reply                          
                            ▼                                          
                        cleaned for speech ──► ElevenLabs TTS ──► Browser
```

One process does everything: serves the page, issues tokens, and hosts the
Speech Engine socket. Deploy it as one Code Engine app.

## What happens in a conversation

1. **Tap the orb.** The browser asks for the microphone, gets a token from
   `/api/token`, and joins the conversation. The orb turns slowly: *Connecting*.
2. **The agent greets you.** The browser sends `ORB_CLICKED` as the first
   turn, which the agent's prompt treats as its cue to say hello. The orb spins
   faster while it thinks, then moves with its voice.
3. **You ask something.** The orb ripples with your voice. When you stop,
   it spins: *Thinking*. While the main agent works, a second, tool-free wxO
   agent (the *filler agent*, `WXO_FILLER_AGENT_ID`) keeps the conversation
   going in its own words. Nothing is hard-coded. For each question it's sent
   what the assistant last said, your words, the lines it has already used,
   and an opening word to start with so it doesn't settle into a favourite.
   You hear, in order:
   - **instantly**, a short reaction ("Sure.", "Okay, right.") that the
     filler agent wrote *ahead*, when the previous answer finished. It fits
     any question because it promises nothing. Interruptions skip it.
   - **about a second later**, the filler agent's line for *this* question
     ("Ah, parking, let me have a look."), unless the answer got there first
   - then up to two "still on it" lines, each following the previous line
     after a short pause (`LINE_GAP_SECONDS`), only while the answer hasn't
     started

   Both are checked before they're spoken (no digits, no questions, nothing
   long). Thanks and goodbyes don't ask the filler agent at all, and if the
   main agent answers first, the filler is dropped. `server/filler_agent.py`
   has the rules for when it's asked, what it's sent and what's spoken.

   **Interruptions and re-sends.** ElevenLabs sometimes sends the same
   question again, after a pause mid-sentence or when the agent's own voice
   reaches the microphone. A question that matches the one being answered
   (allowing for small transcription differences) carries on with the search
   already running instead of starting over, and isn't acknowledged twice.
   Only a different question arriving mid-answer counts as an interruption;
   the filler agent is then told so it can open with a brief apology.
   **Questions for the mortgage specialist.** Personal borrowing estimates go
   to the Mortgage Affordability Agent, which runs outside wxO and takes
   around ten seconds. The assistant asks "That one might take a little longer
   to check, is that okay?" (`SPECIALIST_ASK`) and ends its turn, while wxO
   keeps working. When the caller says "sure", hold music
   (`client/public/hold-music.mp3`) fades in on the page, with the microphone
   muted so the music isn't heard as speech, and fades out as the answer
   starts. If they'd rather not wait, it says `SPECIALIST_DECLINED`; anything
   else is treated as a new question. It's asked straight away when the
   question is clearly a borrowing estimate with figures ("I earn £70k with
   £40k saved, how much could I borrow?"), or the moment wxO routes to a tool
   or agent whose name matches `SPECIALIST_TOOLS`. Product questions
   ("first-time buyer mortgages") are answered from the knowledge base and
   get the usual filler.
4. **The answer streams back.**
   Bold, bullet points and links are cleaned out
   as the text streams, so nothing like "asterisk" or a URL gets read aloud.
5. **Talk over it any time.** The agent stops and the wxO request is cancelled.

The wxO thread id lives with the socket for that conversation, so the agent
remembers context across turns, and nothing is left on the server afterwards.

## Repository

```
├── client/                 Vite, no framework
│   ├── index.html
│   └── src/
│       ├── orb.js          the dot-cloud orb and its five states
│       ├── voice.js        ElevenLabs session + working out the orb's state
│       ├── main.js         wires the two together, caption
│       └── styles.css
├── server/
│   ├── app.py              FastAPI: /api/token, /ws, static client
│   ├── turns.py            one conversation: thread, re-sends, timing of filler lines
│   ├── filler_agent.py     when to ask the filler agent, what it's sent, what's spoken
│   ├── wxo.py              IAM token + streaming chat/completions
│   ├── sse.py              parses wxO's stream (text, tool calls, thread id)
│   ├── speech.py           strips markdown and URLs from streamed text
│   ├── create_engine.py    registers the Speech Engine with ElevenLabs
│   └── tests/              run against a real captured wxO stream
├── Dockerfile
└── .env.example
```

## The wxO agent's instructions

The Northbridge Bank Agent needs voice instructions, including the cue that
turns `ORB_CLICKED` into a greeting. They're in
[`wxo-agent-instructions.md`](wxo-agent-instructions.md): paste them into the
agent's Behavior / Instructions in wxO, save and deploy.

## Deploy to IBM Cloud Code Engine

You need the [IBM Cloud CLI](https://cloud.ibm.com/docs/cli) with the Code
Engine plugin, and Python 3.10+ on your laptop (for one script).

### 1. Fill in `.env`

```bash
cp .env.example .env
```

Fill in `WXO_INSTANCE_URL`, `WXO_AGENT_ID` and `WXO_API_KEY` (Settings → API details
in wxO), `ELEVENLABS_API_KEY`, and optionally `ELEVENLABS_VOICE_ID`. Leave `ELEVENLABS_SPEECH_ENGINE_ID` empty for now.

### 2. Create the app

```bash
ibmcloud login --sso
ibmcloud target -r eu-gb
ibmcloud plugin install code-engine        # first time only

ibmcloud ce project create --name northbridge-voice     # or: ibmcloud ce project select --name <existing>

ibmcloud ce secret create --name northbridge-voice-env --from-env-file .env

ibmcloud ce application create --name northbridge-voice \
  --build-source . --strategy dockerfile \
  --port 8080 \
  --env-from-secret northbridge-voice-env \
  --request-timeout 600 \
  --min-scale 1 --max-scale 3 \
  --cpu 1 --memory 2G
```

Code Engine builds the image from this folder and deploys it. The first build
takes a few minutes.

- `--request-timeout 600` matters. Each conversation is one long-lived
  WebSocket, and Code Engine cuts requests off at this limit. 600 seconds is
  its maximum, so conversations are capped at 10 minutes. `create_engine.py`
  sets the same limit on the ElevenLabs side.
- `--min-scale 1` keeps one instance warm, so the first tap of the day doesn't
  wait for a cold start. It costs a little to leave running; set it to `0`
  when you're not demoing.

Get the app's URL:

```bash
ibmcloud ce application get --name northbridge-voice --output url
```

### 3. Register the Speech Engine

On your laptop:

```bash
pip install -r server/requirements.txt
python server/create_engine.py https://northbridge-voice.xxxxxxxx.eu-gb.codeengine.appdomain.cloud
```

It prints a line like `ELEVENLABS_SPEECH_ENGINE_ID=seng_…`. Add it to `.env`,
then give it to the app:

```bash
ibmcloud ce application update --name northbridge-voice --env ELEVENLABS_SPEECH_ENGINE_ID=seng_...
```

Open the app URL, tap the orb, and allow the microphone.

To choose the voice, set `ELEVENLABS_VOICE_ID` in `.env` and run
`create_engine.py` again with the same URL. With the engine ID already in
`.env`, it updates the existing engine rather than making a new one.

### Updating after a code change

```bash
ibmcloud ce application update --name northbridge-voice --build-source . --strategy dockerfile
```

### Logs

```bash
ibmcloud ce application logs --name northbridge-voice --follow
```

Each turn logs the user's words, when the tool was called and returned, how
long until the first reply text, and when the turn finished.

## Run locally

ElevenLabs has to reach your server from the internet, so local runs need a
tunnel such as ngrok.

```bash
cd client && npm install && npm run build && cd ..
pip install -r server/requirements.txt
uvicorn app:app --app-dir server --port 8080
ngrok http 8080                                     # in another terminal
python server/create_engine.py https://<id>.ngrok.app
```

Open http://localhost:8080. For front-end work, `npm run dev` in `client/`
serves on :5173 and proxies `/api` to :8080. In dev, `__orbManual('thinking')`
in the browser console drives the orb without a session;
`__orbManual(false)` hands control back.

Tests (no network, no keys needed):

```bash
cd server && python -m unittest discover tests
```

## Settings

| Variable | Default | |
|---|---|---|
| `WXO_INSTANCE_URL` | | Settings → API details in wxO |
| `WXO_AGENT_ID` | | |
| `WXO_API_KEY` | | Exchanged for an IAM token, refreshed automatically |
| `WXO_FILLER_AGENT_ID` | | The tool-free agent that writes everything said while the main agent works. Without it, nothing is said until the answer |
| `ELEVENLABS_API_KEY` | | |
| `ELEVENLABS_SPEECH_ENGINE_ID` | | From `create_engine.py` |
| `ELEVENLABS_VOICE_ID` | | Optional, read by `create_engine.py` |
| `ELEVENLABS_TTS_MODEL` | `eleven_v4_turbo` | Voice model, applied by `create_engine.py` |
| `ENGINE_LANGUAGE` | `en` | Read by `create_engine.py` |
| `LINE_GAP_SECONDS` | `0.6` | Pause after one filler line finishes before the next "still on it" line, while the answer hasn't started |
| `QUICK_FILLER` | `true` | Ask the filler agent each turn; `false` stays quiet until the answer |
| `SPECIALIST_ASK` | "That one might take a little longer to check, is that okay?" | Asked before waiting for the mortgage specialist. Empty turns the ask and hold music off |
| `SPECIALIST_DECLINED` | "No problem. Is there anything else I can help with?" | Said if the caller would rather not wait |
| `SPECIALIST_TOOLS` | `mortgage\|affordab` | Pattern matched against the name of the tool or agent wxO routes to. The server logs every name as `tool call: …` |
| `TURN_EAGERNESS` | `normal` | `patient`, `normal` or `eager`: how soon the caller's turn is judged finished. Read by `create_engine.py` |
| `TOKENS_PER_MINUTE` | `12` | Per IP address, protects your ElevenLabs quota |
| `DEBUG` | `false` | Verbose logs, including the Speech Engine SDK's own |
| `DISABLE_AUTH` | `false` | Skips the ElevenLabs signature check on `/ws`. Never in Code Engine |

## Security

- Both API keys stay on the server. The browser only gets a short-lived
  conversation token.
- `/ws` only accepts connections signed by ElevenLabs. They sign each one with
  a JWT derived from your API key, and connections without a valid one are
  rejected before the socket opens.
- Speech is treated as untrusted input and capped at 8,192 characters before
  it reaches the agent.

## Troubleshooting

| What you see | What to do |
|---|---|
| App won't start: `Missing settings` | A required variable is empty in the Code Engine secret |
| Caption: "The voice service isn't set up yet." | `ELEVENLABS_SPEECH_ENGINE_ID` isn't set on the app (step 3) |
| Caption: "Microphone access is blocked" | Allow the microphone for this site in the browser's site settings |
| Connects, then silence | Check the logs. `rejected /ws connection` means the engine was created with a different ElevenLabs API key than the app has |
| Agent says it's having trouble reaching the information | The wxO request failed. Look for `wxO request failed` in the logs: 401 means `WXO_API_KEY`, 404 means the instance URL or agent ID |
| Conversations end after 10 minutes | Code Engine's request limit (see step 2) |
