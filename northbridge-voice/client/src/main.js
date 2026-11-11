import { createOrb } from './orb.js';
import { VoiceSession } from './voice.js';
import './styles.css';

const stage = document.getElementById('orb');
const toggle = document.getElementById('toggle');
const canvas = document.getElementById('orb-canvas');
const caption = document.getElementById('caption');

const orb = createOrb(canvas);
const session = new VoiceSession({ onChange: render });

let shown = '';

function render() {
  const live = session.live;
  stage.setAttribute('aria-label', live ? 'End the conversation' : 'Start talking to the Northbridge assistant');
  toggle.textContent = live ? 'End conversation' : 'Start conversation';
  toggle.setAttribute('aria-pressed', live ? 'true' : 'false');
  document.body.dataset.status = session.status;
}

// No status words: the orb shows what's happening. The line below the orb
// only appears when something is wrong.
function setCaption(text) {
  if (text === shown) return;
  shown = text;
  caption.textContent = text;
}

let manual = false; // dev only: set via __orbManual()

function tick() {
  const s = manual ? { state: orb.state } : session.sample();
  if (!manual) {
    // Fillers and the specialist heads-up have no look of their own: the orb
    // moves with the voice.
    orb.state = s.state === 'acknowledging' || s.state === 'handoff' ? 'speaking' : s.state;
    orb.user = s.user;
    orb.agent = s.agent;
  }

  if (session.status === 'denied') setCaption('Microphone access is blocked');
  else if (session.status === 'error') setCaption(session.error || 'Something went wrong');
  else setCaption('');

  requestAnimationFrame(tick);
}

stage.addEventListener('click', () => session.toggle());
toggle.addEventListener('click', () => session.toggle());
render();
requestAnimationFrame(tick);

// Dev only: drive the orb from the console without a live session, e.g.
//   __orbManual('thinking')      __orbManual('speaking', { agent: .7 })
//   __orbManual(false)           hand control back to the session
if (import.meta.env.DEV) {
  window.__orbManual = (state, levels = {}) => {
    manual = Boolean(state);
    if (manual) Object.assign(orb, { state, user: 0, agent: 0 }, levels);
  };
  window.__voice = session;
}
