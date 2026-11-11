/**
 * The voice session: ElevenLabs WebRTC conversation plus the logic that
 * decides what the orb should show.
 *
 *   listening      the caller is talking, or the reply hasn't started
 *   acknowledging  a filler line is playing ("Uh, let's see...")
 *                  (shown as Listening, with the orb moving to the voice)
 *   handoff        "That one might take a little longer to check, is that
 *                  okay?" (shown as Speaking), then listening for the reply
 *   music          they said yes: hold music plays, with the microphone
 *                  muted, until the answer starts
 *   thinking       after the filler, until the answer is playing. A quieter
 *                  "still thinking" line keeps the orb spinning.
 *   speaking       the answer is playing
 *
 * The server says what it's sending ("filler", "ask", "music", "hold", "answer") over
 * /api/turn-events. If that isn't available, the page falls back to guessing
 * from sound levels: agent speech shorter than ACK_MS counts as a filler.
 */

import { Conversation } from '@elevenlabs/client';

// The agent's prompt treats this as "the caller just opened the assistant".
export const GREETING_CUE = 'ORB_CLICKED';

const QUIET_MS = 900;           // agent silent this long = not speaking
const ACK_MS = 750;             // agent speech shorter than this is an acknowledgement, not the answer
const ACK_WAIT_MS = 1500;       // how long after the caller finishes to wait for an acknowledgement
const BURST_GAP_MS = 300;       // a pause this long starts a new stretch of agent speech
const REPLY_TIMEOUT_MS = 30000; // stop showing "thinking" if nothing ever comes
const AUDIBLE = 0.02;
const USER_TALKING = 0.25;      // caller's mic level that counts as talking
const THINK_AFTER_MS = 1800;    // nothing sent this long after the caller finishes: show thinking
const MUSIC_MAX_MS = 45000;     // hold music stops by itself after this, whatever happens

export class VoiceSession {
  constructor({ onChange }) {
    this.onChange = onChange;
    this.status = 'idle';      // idle | connecting | live | denied | error
    this.error = '';
    this.conversation = null;
    this.mode = 'listening';
    this.owedSince = 0;        // 0 = no reply owed (or the answer is under way)
    this.lastAgentSound = 0;
    this.burstStart = 0;       // when the current stretch of agent speech began
    this.ackHeard = false;     // the acknowledgement for this turn has started playing
    this.ackDone = false;      // ...and has finished
    this.events = null;        // EventSource for what the server is sending
    this.eventsLive = false;
    this.phase = '';           // '' | 'filler' | 'ask' | 'music' | 'hold' | 'answer', for the current turn
    this.music = new HoldMusic('/hold-music.mp3');
    this.handoffHeard = false; // "...is that okay?" has started playing
    this.handoffDone = false;  // ...and has finished
  }

  get live() {
    return this.status === 'connecting' || this.status === 'live';
  }

  async start() {
    if (this.live) return;
    this.music.unlock(); // inside the click, so the browser lets it play later
    this.set('connecting');
    try {
      // Ask for the microphone first so a refusal gets a clear message.
      const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
      probe.getTracks().forEach((t) => t.stop());
    } catch (e) {
      this.set(e && e.name === 'NotAllowedError' ? 'denied' : 'error',
        e && e.name === 'NotAllowedError' ? '' : 'No microphone found');
      return;
    }

    let token;
    try {
      const res = await fetch('/api/token', { cache: 'no-store' });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body.token) throw new Error(body.error || 'The voice service is unavailable');
      token = body.token;
    } catch (e) {
      this.set('error', e.message || 'The voice service is unavailable');
      return;
    }
    if (this.status !== 'connecting') return; // ended while we waited

    try {
      this.conversation = await Conversation.startSession({
        conversationToken: token,
        connectionType: 'webrtc',
        onModeChange: ({ mode }) => {
          this.mode = mode;
          if (mode === 'speaking') this.lastAgentSound = performance.now();
        },
        onMessage: ({ source }) => {
          // The caller's turn has ended: think until the answer is under way.
          if (source === 'user') {
            this.owedSince = performance.now();
            this.ackHeard = false;
            this.ackDone = false;
            this.phase = '';
            this.handoffHeard = false;
            this.handoffDone = false;
          }
        },
        onInterruption: () => {
          this.owedSince = performance.now();
        },
        onConnect: ({ conversationId }) => this.listenForPhases(conversationId),
        onDisconnect: () => {
          this.stopMusic();
          this.stopListening();
          this.conversation = null;
          if (this.live) this.set('idle');
        },
        onError: (message) => {
          console.error('[voice]', message);
        },
      });
    } catch (e) {
      console.error('[voice] could not start', e);
      this.set('error', 'Couldn’t connect. Please try again.');
      return;
    }

    if (this.status !== 'connecting') {
      this.conversation.endSession();
      this.conversation = null;
      return;
    }
    this.mode = 'listening';
    this.owedSince = performance.now();
    this.set('live');
    // The agent speaks first: this cue is its prompt to greet the caller.
    this.conversation.sendUserMessage(GREETING_CUE);
  }

  /** Follow what the server is sending for this conversation. */
  listenForPhases(conversationId) {
    this.stopListening();
    if (!conversationId || typeof EventSource === 'undefined') return;
    const events = new EventSource(`/api/turn-events/${encodeURIComponent(conversationId)}`);
    events.onmessage = (e) => {
      if (['filler', 'ask', 'music', 'hold', 'answer'].includes(e.data)) this.phase = e.data;
      if (e.data === 'music') this.startMusic();
      else if (e.data === 'answer') this.stopMusic();
    };
    events.onopen = () => { this.eventsLive = true; };
    events.onerror = () => { this.eventsLive = false; };
    this.events = events;
  }

  stopListening() {
    if (this.events) this.events.close();
    this.events = null;
    this.eventsLive = false;
  }

  /** Hold music while the specialist works; the mic is muted so it isn't heard as speech. */
  startMusic() {
    this.music.play();
    try { this.conversation?.setMicMuted?.(true); } catch { /* older client */ }
    clearTimeout(this.musicTimer);
    this.musicTimer = setTimeout(() => this.stopMusic(), MUSIC_MAX_MS); // never left playing
  }

  stopMusic() {
    clearTimeout(this.musicTimer);
    this.music.stop();
    try { this.conversation?.setMicMuted?.(false); } catch { /* older client */ }
  }

  async end() {
    this.stopMusic();
    this.stopListening();
    const c = this.conversation;
    this.conversation = null;
    this.owedSince = 0;
    this.set('idle');
    if (c) {
      try { await c.endSession(); } catch { /* already closed */ }
    }
  }

  toggle() {
    return this.live ? this.end() : this.start();
  }

  /** Called every frame: what the orb should show and how loud each side is. */
  sample(now = performance.now()) {
    if (this.status === 'connecting') return { state: 'connecting', user: 0, agent: 0 };
    if (this.status !== 'live' || !this.conversation) return { state: 'idle', user: 0, agent: 0 };

    const c = this.conversation;
    const out = safe(() => c.getOutputVolume());
    const inp = safe(() => c.getInputVolume());

    if (out > AUDIBLE) {
      if (now - this.lastAgentSound > BURST_GAP_MS) this.burstStart = now;
      this.lastAgentSound = now;
    }
    const agentAudible = now - this.lastAgentSound < BURST_GAP_MS;
    const agentTalking = this.mode === 'speaking' && now - this.lastAgentSound < QUIET_MS;
    const userTalking = level(inp) > USER_TALKING && !agentAudible;

    if (this.eventsLive) return this.sampleFromServer(now, out, inp, agentAudible, agentTalking, userTalking);

    if (this.owedSince) {
      const answerStarted = agentAudible && now - this.burstStart > ACK_MS;
      if (answerStarted || now - this.owedSince > REPLY_TIMEOUT_MS) this.owedSince = 0;
    }

    if (userTalking) return { state: 'listening', user: level(inp), agent: 0 };
    if (this.owedSince) {
      if (this.ackHeard && !agentAudible) this.ackDone = true;
      if (agentAudible && !this.ackDone) {
        if (this.ackHeard || now - this.owedSince < ACK_WAIT_MS) {
          // The first acknowledgement, straight after the caller finishes.
          this.ackHeard = true;
          return { state: 'acknowledging', user: 0, agent: level(out) };
        }
        // No acknowledgement this turn (thanks, goodbye): this is the answer.
        this.owedSince = 0;
        return { state: 'speaking', user: 0, agent: level(out) };
      }
      // Anything short after it (the whispered "mm-hmm") stays "thinking".
      if (this.ackDone) return { state: 'thinking', user: 0, agent: 0 };
      // Give the acknowledgement a moment to arrive before starting to think.
      if (!this.ackHeard && now - this.owedSince < ACK_WAIT_MS) {
        return { state: 'listening', user: 0, agent: 0 };
      }
      return { state: 'thinking', user: 0, agent: 0 };
    }
    if (agentTalking) return { state: 'speaking', user: 0, agent: level(out) };
    return { state: 'listening', user: level(inp), agent: 0 };
  }

  /** The server says what it's sending; sound levels only say when it plays. */
  sampleFromServer(now, out, inp, agentAudible, agentTalking, userTalking) {
    if (userTalking) return { state: 'listening', user: level(inp), agent: 0 };
    if (this.owedSince && now - this.owedSince > REPLY_TIMEOUT_MS) this.owedSince = 0;

    if (this.owedSince) {
      const speaking = { state: 'speaking', user: 0, agent: level(out) };
      switch (this.phase) {
        case 'answer':
          if (agentAudible) {
            this.owedSince = 0;
            return speaking;
          }
          // Text sent, audio not playing yet.
          return { state: this.ackHeard || this.handoffHeard ? 'thinking' : 'listening', user: 0, agent: 0 };
        case 'music':
          return { state: 'thinking', user: 0, agent: 0 };
        case 'ask':
          // "...is that okay?": speaking, then their turn to answer.
          if (agentAudible && !this.handoffDone) {
            this.handoffHeard = true;
            return { state: 'handoff', user: 0, agent: level(out) };
          }
          if (this.handoffHeard) {
            this.handoffDone = true;
            this.owedSince = 0;
            return { state: 'listening', user: level(inp), agent: 0 };
          }
          return { state: 'thinking', user: 0, agent: 0 };
        case 'hold':
          return { state: 'thinking', user: 0, agent: 0 };
        case 'filler':
          if (agentAudible && !this.ackDone) {
            this.ackHeard = true;
            return { state: 'acknowledging', user: 0, agent: level(out) };
          }
          if (this.ackHeard) {
            this.ackDone = true;
            return { state: 'thinking', user: 0, agent: 0 };
          }
          return { state: 'listening', user: 0, agent: 0 };
        default:
          // Nothing sent yet: still taking it in, then visibly thinking.
          return { state: now - this.owedSince < THINK_AFTER_MS ? 'listening' : 'thinking', user: 0, agent: 0 };
      }
    }
    if (agentTalking) return { state: 'speaking', user: 0, agent: level(out) };
    return { state: 'listening', user: level(inp), agent: 0 };
  }

  set(status, error = '') {
    this.status = status;
    this.error = error;
    this.onChange?.(this);
  }
}

/** Looping hold music that fades in and out. */
class HoldMusic {
  constructor(src, volume = 0.3) {
    this.volume = volume;
    this.fade = 0;
    try {
      this.audio = new Audio(src);
      this.audio.loop = true;
      this.audio.preload = 'auto';
      this.audio.volume = 0;
    } catch {
      this.audio = null;
    }
  }

  /** Browsers only allow audio started from a click; do a silent start-stop there. */
  unlock() {
    const a = this.audio;
    if (!a || this.unlocked) return;
    this.unlocked = true;
    a.volume = 0;
    a.play().then(() => { if (!this.playing) a.pause(); }).catch(() => {});
  }

  play() {
    const a = this.audio;
    if (!a || this.playing) return;
    this.playing = true;
    a.currentTime = 0;
    a.play().catch((e) => console.warn('[voice] hold music could not play', e));
    this.rampTo(this.volume, 800);
  }

  stop() {
    if (!this.audio || !this.playing) return;
    this.playing = false;
    this.rampTo(0, 700, () => this.audio.pause());
  }

  rampTo(target, ms, done) {
    const a = this.audio;
    cancelAnimationFrame(this.fade);
    const from = a.volume;
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.max(0, Math.min(1, (now - t0) / ms));
      a.volume = Math.max(0, Math.min(1, from + (target - from) * k));
      if (k < 1) this.fade = requestAnimationFrame(step);
      else done?.();
    };
    this.fade = requestAnimationFrame(step);
  }
}

// Map raw RMS volume to a lively 0–1 level: ignore room noise, lift speech.
function level(v) {
  const x = (v - 0.012) / 0.3;
  return x <= 0 ? 0 : Math.min(1, Math.pow(x, 0.75));
}

function safe(fn) {
  try {
    const v = fn();
    return Number.isFinite(v) ? v : 0;
  } catch {
    return 0;
  }
}
