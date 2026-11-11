/**
 * The dot-cloud orb.
 *
 * At rest it is exactly the "Blue Presence" sphere: 5,700 dots on a
 * Fibonacci sphere, swaying and breathing slowly. On top of that:
 *
 *   connecting  the cloud starts to turn and draws in a little
 *   thinking    the cloud spins noticeably faster
 *   listening   a soft wave rolls in from the left with the caller's voice
 *   speaking    rings breathe out from the core with the agent's voice
 *
 * Drive it by writing to the returned object every frame or whenever
 * things change:  orb.state = 'thinking';  orb.user = 0.6;  orb.agent = 0;
 * Levels are 0–1. Every change is eased, so nothing ever snaps.
 */

const TAU = Math.PI * 2;
const COUNT = 5700;
const BUCKETS = 24;
const BASE = [0, 102, 204];      // Northbridge blue #0066CC
const SPEAKING = [0, 113, 227];  // a touch brighter while the assistant talks

// Spin speed, radians per second.
const SPEED = { idle: 0, connecting: 0.5, listening: 0.04, thinking: 1.9, speaking: 0.08 };

function makeDots() {
  // Deterministic, so the orb looks the same on every load.
  let seed = 91371;
  const random = () => ((seed = (1664525 * seed + 1013904223) >>> 0) / 4294967296);
  const dots = [];
  for (let i = 0; i < COUNT; i++) {
    const theta = i * Math.PI * (3 - Math.sqrt(5));
    const y = 1 - 2 * (i + 0.5) / COUNT;
    const ring = Math.sqrt(Math.max(0, 1 - y * y));
    const depth = 0.81 + 0.19 * random();
    const x = Math.cos(theta) * ring * depth;
    const z = Math.sin(theta) * ring * depth;
    const yy = y * depth;
    dots.push({
      x, y: yy, z,
      len: Math.hypot(x, yy, z),
      r: 0.70 + random() * 0.43,
      opacity: 0.60 + random() * 0.28,
      phase: random() * TAU,
    });
  }
  return dots;
}

export function createOrb(canvas) {
  const ctx = canvas.getContext('2d');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const dots = makeDots();

  const input = { state: 'idle', user: 0, agent: 0 };
  const d = { user: 0, agent: 0, speak: 0, gather: 0, speed: 0 };
  const ease = (cur, to, k) => cur + (to - cur) * k;

  let w = 0, h = 0, dpr = 1;
  const resize = () => {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = canvas.getBoundingClientRect();
    w = r.width; h = r.height;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
  };
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  let t = 0, spin = 0, last = performance.now(), frameId = 0;

  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    const still = reduceMotion.matches;
    if (!still) t += dt;

    const s = input.state in SPEED ? input.state : 'idle';
    d.user   = ease(d.user,   s === 'listening' ? clamp(input.user) : 0, 0.12);
    d.agent  = ease(d.agent,  s === 'speaking' ? clamp(input.agent) : 0, 0.12);
    d.speak  = ease(d.speak,  s === 'speaking' ? 1 : 0, 0.03);
    d.gather = ease(d.gather, s === 'connecting' || s === 'thinking' ? 1 : 0, 0.04);
    d.speed  = ease(d.speed,  SPEED[s], 0.035);
    if (!still) spin += dt * d.speed;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const scale = Math.min(w, h) * 0.37;
    const cx = w / 2, cy = h / 2;
    const angle = Math.sin(t * 0.075) * 0.14 + spin;
    const ca = Math.cos(angle), sa = Math.sin(angle);
    const breath = (1 + 0.014 * Math.sin(t * 0.45))
                 * (1 - 0.03 * d.gather + 0.01 * d.gather * Math.sin(t * 2.2))
                 * (1 + 0.03 * d.agent + 0.02 * d.user);
    const dotScale = Math.max(0.9, scale / 370);
    const paths = Array.from({ length: BUCKETS }, () => new Path2D());

    for (const p of dots) {
      const ripple = 1 + 0.026 * Math.sin(p.y * 5.5 + t * 0.28 + p.phase * 0.13)
                       + 0.010 * Math.cos(p.x * 8 - t * 0.19);
      let voice = 0;
      if (d.user > 0.002) {
        const u = p.x + 1;
        voice += d.user * 0.075 * Math.sin(u * 6.5 - t * 5.5) * Math.exp(-u * 0.7);
      }
      if (d.agent > 0.002) {
        voice += d.agent * 0.06 * Math.sin(p.len * 15 - t * 6 + p.phase * 0.25);
      }
      const x = p.x * (ripple + voice), z = p.z * (ripple + voice);
      const xr = x * ca - z * sa;
      const zr = x * sa + z * ca;
      const yr = p.y * (1 + voice) * (1 + 0.015 * Math.sin(t * 0.24 + p.x * 3));
      const perspective = 1 + zr * 0.075;
      const px = cx + xr * scale * perspective * breath;
      const py = cy + yr * scale * perspective * breath;
      const edge = Math.max(0, 1 - Math.pow(Math.hypot(xr, yr) / 1.08, 5));
      const alpha = p.opacity * (0.72 + 0.28 * (zr + 1) / 2) * (0.72 + 0.28 * edge);
      const radius = Math.max(0.28, p.r * dotScale * (1 + 0.12 * zr));
      const b = Math.min(BUCKETS - 1, Math.max(0, Math.round(alpha * (BUCKETS - 1))));
      paths[b].moveTo(px + radius, py);
      paths[b].arc(px, py, radius, 0, TAU);
    }

    const col = BASE.map((v, i) => Math.round(v + (SPEAKING[i] - v) * d.speak));
    for (let b = 1; b < BUCKETS; b++) {
      ctx.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${(b / (BUCKETS - 1)).toFixed(3)})`;
      ctx.fill(paths[b]);
    }

    frameId = requestAnimationFrame(frame);
  }
  frameId = requestAnimationFrame(frame);

  input.destroy = () => {
    cancelAnimationFrame(frameId);
    ro.disconnect();
  };
  return input;
}

function clamp(v) {
  return v > 1 ? 1 : v < 0 || !Number.isFinite(v) ? 0 : v;
}
