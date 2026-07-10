// app.js — state, transport clock, and UI wiring for the ReBirth-inspired sim.
import {
  NUM_STEPS, MasterBus, Bassline, DrumMachine, midiToName,
} from './audio.js';

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------
const DRUMS = [
  { id: 'bd', name: 'Bass Drum' },
  { id: 'sd', name: 'Snare' },
  { id: 'lt', name: 'Low Tom' },
  { id: 'mt', name: 'Mid Tom' },
  { id: 'ht', name: 'Hi Tom' },
  { id: 'rs', name: 'Rimshot' },
  { id: 'cp', name: 'Clap' },
  { id: 'cb', name: 'Cowbell' },
  { id: 'ch', name: 'Closed Hat' },
  { id: 'oh', name: 'Open Hat' },
  { id: 'cy', name: 'Crash' },
];

const BASE_MIDI = 24; // C1
const NOTE_RANGE = 24; // two octaves of pitch travel on each 303 step

function emptyBassPattern() {
  return Array.from({ length: NUM_STEPS }, () => ({
    on: false, midi: 36, accent: false, slide: false,
  }));
}
function emptyDrumPattern() {
  const p = {};
  for (const d of DRUMS) p[d.id] = Array.from({ length: NUM_STEPS }, () => 0);
  return p;
}

// A full pattern = state of both 303s + the drum grid.
function emptyPattern() {
  return {
    bass1: emptyBassPattern(),
    bass2: emptyBassPattern(),
    drums: emptyDrumPattern(),
  };
}

const state = {
  bpm: 130,
  swing: 0,
  playing: false,
  currentStep: 0,
  patterns: [emptyPattern(), emptyPattern(), emptyPattern(), emptyPattern()],
  activePattern: 0,
};

function pat() { return state.patterns[state.activePattern]; }

// ---------------------------------------------------------------------------
// Audio setup (lazy — created on first user gesture)
// ---------------------------------------------------------------------------
let ctx = null;
let bus = null;
let bass1 = null;
let bass2 = null;
let drums = null;

function ensureAudio() {
  if (ctx) return;
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  bus = new MasterBus(ctx);
  bass1 = new Bassline(ctx, bus.input);
  bass2 = new Bassline(ctx, bus.input);
  bass2.setWaveform('square');
  drums = new DrumMachine(ctx, bus.input);
  wireSynthControls();
}

// ---------------------------------------------------------------------------
// Transport — lookahead scheduler ("A Tale of Two Clocks").
// ---------------------------------------------------------------------------
const LOOKAHEAD = 0.1;      // seconds of audio scheduled ahead
const INTERVAL = 25;        // ms between scheduler ticks
let nextNoteTime = 0;
let schedStep = 0;
let timerId = null;
const drawQueue = [];       // {step, time} for UI playhead sync

function secondsPerStep() {
  return (60 / state.bpm) / 4; // 16th notes
}

function scheduleStep(step, time) {
  const p = pat();
  const spb = secondsPerStep();
  // Swing: delay odd 16ths.
  const swung = (step % 2 === 1) ? time + spb * state.swing * 0.5 : time;

  // --- 303 basslines ---
  [[bass1, p.bass1], [bass2, p.bass2]].forEach(([voice, steps]) => {
    const s = steps[step];
    if (s.on) {
      voice.play(s.midi, swung, spb, s.accent, s.slide);
    }
  });

  // --- Drums ---
  for (const d of DRUMS) {
    const v = p.drums[d.id][step];
    if (v > 0) {
      const vel = v === 2 ? 1.0 : 0.62; // 2 = accent
      drums.trigger(d.id, swung, vel);
    }
  }

  drawQueue.push({ step, time: swung });
}

function scheduler() {
  while (nextNoteTime < ctx.currentTime + LOOKAHEAD) {
    scheduleStep(schedStep, nextNoteTime);
    nextNoteTime += secondsPerStep();
    schedStep = (schedStep + 1) % NUM_STEPS;
  }
  timerId = setTimeout(scheduler, INTERVAL);
}

function startTransport() {
  ensureAudio();
  if (ctx.state === 'suspended') ctx.resume();
  if (state.playing) return;
  state.playing = true;
  schedStep = 0;
  nextNoteTime = ctx.currentTime + 0.05;
  scheduler();
  requestAnimationFrame(draw);
  document.getElementById('playBtn').classList.add('active');
}

function stopTransport() {
  state.playing = false;
  if (timerId) clearTimeout(timerId);
  timerId = null;
  state.currentStep = 0;
  document.getElementById('playBtn').classList.remove('active');
  highlightPlayhead(-1);
}

// Playhead animation, synced to scheduled audio time.
function draw() {
  if (!state.playing) return;
  const now = ctx.currentTime;
  while (drawQueue.length && drawQueue[0].time < now) {
    state.currentStep = drawQueue.shift().step;
  }
  highlightPlayhead(state.currentStep);
  requestAnimationFrame(draw);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
};

function buildBass(voiceId, steps, label, accentColor) {
  const wrap = el('div', 'synth bass');
  wrap.style.setProperty('--accent', accentColor);

  const head = el('div', 'synth-head');
  head.appendChild(el('span', 'synth-title', label));
  const sub = el('span', 'synth-sub', 'TB-303 Bass Line');
  head.appendChild(sub);
  wrap.appendChild(head);

  const body = el('div', 'synth-body');

  // Knob panel.
  const knobs = el('div', 'knobs');
  const knobDefs = [
    ['tuning', 'Tune', -12, 12, 0, 1],
    ['cutoff', 'Cutoff', 0, 1, 0.5, 0.01],
    ['resonance', 'Reso', 0, 1, 0.6, 0.01],
    ['envMod', 'Env Mod', 0, 1, 0.55, 0.01],
    ['decay', 'Decay', 0, 1, 0.4, 0.01],
    ['accentAmt', 'Accent', 0, 1, 0.6, 0.01],
    ['volume', 'Volume', 0, 1, 0.5, 0.01],
  ];
  for (const [param, name, min, max, def, step] of knobDefs) {
    const k = el('div', 'knob');
    const input = el('input');
    input.type = 'range';
    input.min = min; input.max = max; input.step = step; input.value = def;
    input.dataset.voice = voiceId;
    input.dataset.param = param;
    input.className = 'knob-input';
    k.appendChild(input);
    k.appendChild(el('label', 'knob-label', name));
    knobs.appendChild(k);
  }
  // Waveform toggle.
  const wave = el('div', 'knob wave-toggle');
  const wbtn = el('button', 'wave-btn', voiceId === 'bass2' ? '⊓ Square' : '⋀ Saw');
  wbtn.dataset.voice = voiceId;
  wbtn.dataset.wave = voiceId === 'bass2' ? 'square' : 'sawtooth';
  wave.appendChild(wbtn);
  wave.appendChild(el('label', 'knob-label', 'Wave'));
  knobs.appendChild(wave);

  body.appendChild(knobs);

  // Step grid.
  const grid = el('div', 'bass-grid');
  grid.dataset.voice = voiceId;
  for (let i = 0; i < NUM_STEPS; i++) {
    const cell = el('div', 'bass-step');
    cell.dataset.index = i;

    const noteLabel = el('div', 'note-label', '—');

    const slider = el('input', 'pitch');
    slider.type = 'range';
    slider.min = 0; slider.max = NOTE_RANGE; slider.step = 1;
    slider.value = steps[i].midi - BASE_MIDI;
    slider.setAttribute('orient', 'vertical');
    slider.dataset.index = i;

    const gate = el('button', 'gate', '');
    gate.dataset.index = i;

    const flags = el('div', 'flags');
    const acc = el('button', 'flag acc', 'A');
    acc.dataset.index = i;
    const sld = el('button', 'flag sld', 'S');
    sld.dataset.index = i;
    flags.appendChild(acc);
    flags.appendChild(sld);

    cell.appendChild(noteLabel);
    cell.appendChild(slider);
    cell.appendChild(gate);
    cell.appendChild(flags);
    if ((i % 4) === 0) cell.classList.add('beat');
    grid.appendChild(cell);
  }
  body.appendChild(grid);

  // Row tools.
  const tools = el('div', 'row-tools');
  const rnd = el('button', 'mini', 'Random');
  const clr = el('button', 'mini', 'Clear');
  rnd.dataset.action = 'rnd'; rnd.dataset.voice = voiceId;
  clr.dataset.action = 'clr'; clr.dataset.voice = voiceId;
  tools.appendChild(rnd); tools.appendChild(clr);
  body.appendChild(tools);

  wrap.appendChild(body);
  return wrap;
}

function buildDrums() {
  const wrap = el('div', 'drums');
  const head = el('div', 'synth-head');
  head.appendChild(el('span', 'synth-title', 'RHYTHM'));
  head.appendChild(el('span', 'synth-sub', 'TR-808 / TR-909 Drum Machine'));
  wrap.appendChild(head);

  const table = el('div', 'drum-table');
  for (const d of DRUMS) {
    const row = el('div', 'drum-row');
    row.dataset.drum = d.id;

    const label = el('button', 'drum-label', d.name);
    label.dataset.drum = d.id;
    label.title = 'Click to audition';
    row.appendChild(label);

    const vol = el('input', 'drum-vol');
    vol.type = 'range'; vol.min = 0; vol.max = 1; vol.step = 0.01; vol.value = 0.85;
    vol.dataset.drum = d.id;
    row.appendChild(vol);

    const cells = el('div', 'drum-cells');
    for (let i = 0; i < NUM_STEPS; i++) {
      const c = el('button', 'drum-step');
      c.dataset.drum = d.id;
      c.dataset.index = i;
      if ((i % 4) === 0) c.classList.add('beat');
      cells.appendChild(c);
    }
    row.appendChild(cells);
    table.appendChild(row);
  }
  wrap.appendChild(table);

  const tools = el('div', 'row-tools drum-tools');
  ['Random', 'Clear'].forEach((t) => {
    const b = el('button', 'mini', t);
    b.dataset.action = t === 'Random' ? 'drnd' : 'dclr';
    tools.appendChild(b);
  });
  wrap.appendChild(tools);

  return wrap;
}

// ---------------------------------------------------------------------------
// Sync DOM <- state
// ---------------------------------------------------------------------------
function refreshBass(voiceId) {
  const steps = pat()[voiceId];
  const grid = document.querySelector(`.bass-grid[data-voice="${voiceId}"]`);
  grid.querySelectorAll('.bass-step').forEach((cell) => {
    const i = +cell.dataset.index;
    const s = steps[i];
    cell.classList.toggle('on', s.on);
    cell.querySelector('.gate').classList.toggle('lit', s.on);
    cell.querySelector('.acc').classList.toggle('lit', s.accent);
    cell.querySelector('.sld').classList.toggle('lit', s.slide);
    cell.querySelector('.pitch').value = s.midi - BASE_MIDI;
    cell.querySelector('.note-label').textContent = s.on ? midiToName(s.midi) : '—';
  });
}

function refreshDrums() {
  const grid = pat().drums;
  document.querySelectorAll('.drum-step').forEach((c) => {
    const v = grid[c.dataset.drum][+c.dataset.index];
    c.classList.toggle('on', v > 0);
    c.classList.toggle('accent', v === 2);
  });
}

function highlightPlayhead(step) {
  document.querySelectorAll('.bass-step, .drum-step').forEach((c) => {
    c.classList.toggle('playing', +c.dataset.index === step);
  });
  document.querySelectorAll('.pat-led').forEach((l, i) => {
    l.classList.toggle('beat-on', step >= 0 && i === Math.floor(step / 4));
  });
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------
function wireBass(voiceId) {
  const grid = document.querySelector(`.bass-grid[data-voice="${voiceId}"]`);
  const steps = () => pat()[voiceId];

  grid.addEventListener('click', (e) => {
    const t = e.target;
    const i = +t.dataset.index;
    if (t.classList.contains('gate')) {
      steps()[i].on = !steps()[i].on;
      refreshBass(voiceId);
    } else if (t.classList.contains('acc')) {
      steps()[i].accent = !steps()[i].accent;
      refreshBass(voiceId);
    } else if (t.classList.contains('sld')) {
      steps()[i].slide = !steps()[i].slide;
      refreshBass(voiceId);
    }
  });

  grid.addEventListener('input', (e) => {
    if (!e.target.classList.contains('pitch')) return;
    const i = +e.target.dataset.index;
    steps()[i].midi = BASE_MIDI + (+e.target.value);
    if (!steps()[i].on) steps()[i].on = true; // dragging pitch enables the step
    refreshBass(voiceId);
  });
}

function randomBass(voiceId) {
  const steps = pat()[voiceId];
  const scale = [0, 3, 5, 7, 10, 12]; // minor pentatonic-ish
  for (let i = 0; i < NUM_STEPS; i++) {
    const on = Math.random() < 0.55;
    steps[i].on = on;
    steps[i].midi = BASE_MIDI + 12 + scale[(Math.random() * scale.length) | 0];
    steps[i].accent = on && Math.random() < 0.3;
    steps[i].slide = on && Math.random() < 0.25;
  }
  refreshBass(voiceId);
}
function clearBass(voiceId) {
  pat()[voiceId] = emptyBassPattern();
  refreshBass(voiceId);
}

function wireDrums() {
  document.querySelector('.drum-table').addEventListener('click', (e) => {
    const t = e.target;
    if (t.classList.contains('drum-step')) {
      const arr = pat().drums[t.dataset.drum];
      const i = +t.dataset.index;
      // cycle: off -> on -> accent -> off
      arr[i] = (arr[i] + 1) % 3;
      refreshDrums();
    } else if (t.classList.contains('drum-label')) {
      ensureAudio();
      if (ctx.state === 'suspended') ctx.resume();
      drums.trigger(t.dataset.drum, ctx.currentTime, 1);
    }
  });
  document.querySelector('.drum-table').addEventListener('input', (e) => {
    if (!e.target.classList.contains('drum-vol')) return;
    // Store on the DrumMachine via a per-instrument scale — handled at trigger.
    drumVol[e.target.dataset.drum] = +e.target.value;
  });
}
const drumVol = {};

function randomDrums() {
  const g = pat().drums;
  const density = { bd: 0.4, sd: 0.2, ch: 0.6, oh: 0.15, cp: 0.12, rs: 0.1,
    lt: 0.08, mt: 0.08, ht: 0.08, cb: 0.06, cy: 0.03 };
  for (const d of DRUMS) {
    for (let i = 0; i < NUM_STEPS; i++) {
      const on = Math.random() < (density[d.id] ?? 0.15);
      g[d.id][i] = on ? (Math.random() < 0.25 ? 2 : 1) : 0;
    }
  }
  // Ensure a kick on the downbeats for musicality.
  [0, 8].forEach((i) => (g.bd[i] = 1));
  refreshDrums();
}
function clearDrums() {
  pat().drums = emptyDrumPattern();
  refreshDrums();
}

// Route drum volume into DrumMachine by wrapping trigger.
function applyDrumVolumes() {
  const origTrigger = DrumMachine.prototype.trigger;
  drums.trigger = function (name, time, vel = 1) {
    const scale = drumVol[name] ?? 0.85;
    origTrigger.call(this, name, time, vel * scale);
  };
}

function wireSynthControls() {
  applyDrumVolumes();
  // Knobs.
  document.querySelectorAll('.knob-input').forEach((inp) => {
    inp.addEventListener('input', () => {
      const voice = inp.dataset.voice === 'bass1' ? bass1 : bass2;
      const param = inp.dataset.param;
      const val = +inp.value;
      if (param === 'volume') voice.setVolume(val);
      else voice[param] = val;
    });
  });
  // Waveform toggles.
  document.querySelectorAll('.wave-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const voice = btn.dataset.voice === 'bass1' ? bass1 : bass2;
      const next = btn.dataset.wave === 'sawtooth' ? 'square' : 'sawtooth';
      btn.dataset.wave = next;
      btn.textContent = next === 'square' ? '⊓ Square' : '⋀ Saw';
      voice.setWaveform(next);
    });
  });
  // Master FX.
  bindRange('distortion', (v) => bus.setDistortion(v));
  bindRange('delay', (v) => bus.setDelay(v));
  bindRange('feedback', (v) => bus.setFeedback(v));
  bindRange('master', (v) => bus.setMaster(v));
}

function bindRange(id, fn) {
  const e = document.getElementById(id);
  if (!e) return;
  const apply = () => fn(+e.value);
  e.addEventListener('input', apply);
  apply();
}

// ---------------------------------------------------------------------------
// Pattern bank + transport controls
// ---------------------------------------------------------------------------
function selectPattern(idx) {
  state.activePattern = idx;
  document.querySelectorAll('.bank-btn').forEach((b, i) =>
    b.classList.toggle('active', i === idx));
  refreshBass('bass1');
  refreshBass('bass2');
  refreshDrums();
}

function wireTransport() {
  document.getElementById('playBtn').addEventListener('click', () => {
    if (state.playing) stopTransport(); else startTransport();
  });
  document.getElementById('stopBtn').addEventListener('click', stopTransport);

  const bpm = document.getElementById('bpm');
  const bpmVal = document.getElementById('bpmVal');
  bpm.addEventListener('input', () => {
    state.bpm = +bpm.value;
    bpmVal.textContent = state.bpm;
  });

  const swing = document.getElementById('swing');
  const swingVal = document.getElementById('swingVal');
  swing.addEventListener('input', () => {
    state.swing = +swing.value;
    swingVal.textContent = Math.round(state.swing * 100) + '%';
  });

  document.querySelectorAll('.bank-btn').forEach((b, i) => {
    b.addEventListener('click', () => selectPattern(i));
  });

  document.getElementById('copyBtn').addEventListener('click', () => {
    // copy active pattern into the next slot
    const next = (state.activePattern + 1) % state.patterns.length;
    state.patterns[next] = JSON.parse(JSON.stringify(pat()));
    selectPattern(next);
  });

  document.getElementById('clearAllBtn').addEventListener('click', () => {
    state.patterns[state.activePattern] = emptyPattern();
    selectPattern(state.activePattern);
  });

  // keyboard: space = play/stop
  document.addEventListener('keydown', (e) => {
    if (e.code === 'Space' && e.target.tagName !== 'INPUT') {
      e.preventDefault();
      if (state.playing) stopTransport(); else startTransport();
    }
  });
}

function wireRowTools() {
  document.body.addEventListener('click', (e) => {
    const a = e.target.dataset.action;
    if (a === 'rnd') randomBass(e.target.dataset.voice);
    else if (a === 'clr') clearBass(e.target.dataset.voice);
    else if (a === 'drnd') randomDrums();
    else if (a === 'dclr') clearDrums();
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
function init() {
  const synths = document.getElementById('synths');
  synths.appendChild(buildBass('bass1', pat().bass1, 'BASS 1', '#ff8a3d'));
  synths.appendChild(buildBass('bass2', pat().bass2, 'BASS 2', '#4dd0e1'));
  document.getElementById('drumsMount').appendChild(buildDrums());

  wireBass('bass1');
  wireBass('bass2');
  wireDrums();
  wireTransport();
  wireRowTools();

  refreshBass('bass1');
  refreshBass('bass2');
  refreshDrums();

  // Seed a starter groove so it makes sound immediately.
  seedDemo();
  selectPattern(0);
}

function seedDemo() {
  const p = state.patterns[0];
  // Four-on-the-floor kick + hats + clap.
  [0, 4, 8, 12].forEach((i) => (p.drums.bd[i] = 1));
  [2, 6, 10, 14].forEach((i) => (p.drums.ch[i] = 1));
  [4, 12].forEach((i) => (p.drums.sd[i] = 1));
  p.drums.oh[14] = 1;
  // A little acid line on bass1.
  const line = [
    [0, 36, true, false], [2, 36, false, true], [3, 48, false, false],
    [6, 39, true, false], [8, 36, false, false], [10, 43, false, true],
    [11, 36, false, false], [14, 41, true, false],
  ];
  for (const [i, m, a, s] of line) {
    p.bass1[i] = { on: true, midi: m, accent: a, slide: s };
  }
}

window.addEventListener('DOMContentLoaded', init);
