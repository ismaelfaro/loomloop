// audio.js — Web Audio synthesis engine for the ReBirth-inspired simulator.
// Everything is synthesized live: two TB-303 bass voices and a TR-808/909-style
// drum machine, wired through a shared distortion + delay + compressor master bus.
// No samples, no network — pure Web Audio.

export const NUM_STEPS = 16;

// ---------------------------------------------------------------------------
// Note helpers. The 303 sequencer stores semitone offsets from a base note.
// ---------------------------------------------------------------------------
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

// MIDI note -> frequency (A4 = 69 = 440Hz).
export function midiToFreq(midi) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

export function midiToName(midi) {
  const name = NOTE_NAMES[((midi % 12) + 12) % 12];
  const octave = Math.floor(midi / 12) - 1;
  return name + octave;
}

// ---------------------------------------------------------------------------
// Master bus: distortion (waveshaper) -> delay (feedback) -> compressor -> out.
// ---------------------------------------------------------------------------
export class MasterBus {
  constructor(ctx) {
    this.ctx = ctx;
    this.input = ctx.createGain();

    // Waveshaper distortion.
    this.preDrive = ctx.createGain();
    this.shaper = ctx.createWaveShaper();
    this.shaper.oversample = '4x';
    this.postDrive = ctx.createGain();
    this.setDistortion(0);

    // Delay with feedback + wet/dry.
    this.delay = ctx.createDelay(1.5);
    this.delay.delayTime.value = 0.28;
    this.feedback = ctx.createGain();
    this.feedback.gain.value = 0.35;
    this.delayWet = ctx.createGain();
    this.delayWet.gain.value = 0.0;
    this.dry = ctx.createGain();
    this.dry.gain.value = 1.0;

    // Glue compressor.
    this.comp = ctx.createDynamicsCompressor();
    this.comp.threshold.value = -18;
    this.comp.knee.value = 24;
    this.comp.ratio.value = 3;
    this.comp.attack.value = 0.003;
    this.comp.release.value = 0.18;

    this.master = ctx.createGain();
    this.master.gain.value = 0.85;

    // Wiring: input -> preDrive -> shaper -> postDrive -> (dry + delay path) -> comp -> master -> out
    this.input.connect(this.preDrive);
    this.preDrive.connect(this.shaper);
    this.shaper.connect(this.postDrive);

    this.postDrive.connect(this.dry);
    this.postDrive.connect(this.delay);
    this.delay.connect(this.feedback);
    this.feedback.connect(this.delay); // feedback loop
    this.delay.connect(this.delayWet);

    this.dry.connect(this.comp);
    this.delayWet.connect(this.comp);
    this.comp.connect(this.master);
    this.master.connect(ctx.destination);
  }

  // amount 0..1
  setDistortion(amount) {
    const k = amount * 100;
    const n = 1024;
    const curve = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const x = (i * 2) / n - 1;
      curve[i] = ((3 + k) * x * 20 * (Math.PI / 180)) / (Math.PI + k * Math.abs(x));
    }
    this.shaper.curve = curve;
    this.preDrive.gain.value = 1 + amount * 1.5;
    this.postDrive.gain.value = 1 / (1 + amount * 0.9);
  }

  // amount 0..1
  setDelay(amount) {
    this.delayWet.gain.setTargetAtTime(amount * 0.8, this.ctx.currentTime, 0.02);
  }

  setDelayTime(seconds) {
    this.delay.delayTime.setTargetAtTime(seconds, this.ctx.currentTime, 0.02);
  }

  setFeedback(amount) {
    this.feedback.gain.setTargetAtTime(Math.min(amount, 0.9), this.ctx.currentTime, 0.02);
  }

  setMaster(v) {
    this.master.gain.setTargetAtTime(v, this.ctx.currentTime, 0.02);
  }
}

// ---------------------------------------------------------------------------
// TB-303 bass synth voice.
//
// One monophonic oscillator -> resonant lowpass filter -> amp VCA.
// A per-note filter envelope sweeps the cutoff; accent boosts the sweep and
// volume; slide glides pitch/amp from the previous note (portamento).
// ---------------------------------------------------------------------------
export class Bassline {
  constructor(ctx, dest) {
    this.ctx = ctx;
    this.osc = ctx.createOscillator();
    this.osc.type = 'sawtooth';

    this.filter = ctx.createBiquadFilter();
    this.filter.type = 'lowpass';
    this.filter.frequency.value = 300;
    this.filter.Q.value = 8;

    this.amp = ctx.createGain();
    this.amp.gain.value = 0.0;

    this.out = ctx.createGain();
    this.out.gain.value = 0.5;

    this.osc.connect(this.filter);
    this.filter.connect(this.amp);
    this.amp.connect(this.out);
    this.out.connect(dest);
    this.osc.start();

    // Knob state (ReBirth / 303 style).
    this.tuning = 0;      // semitones, -12..+12
    this.cutoff = 0.5;    // 0..1
    this.resonance = 0.6; // 0..1
    this.envMod = 0.55;   // 0..1
    this.decay = 0.4;     // 0..1
    this.accentAmt = 0.6; // 0..1
    this.waveform = 'sawtooth';

    this._lastFreq = midiToFreq(36);
  }

  setWaveform(w) {
    this.waveform = w;
    this.osc.type = w;
  }

  setVolume(v) {
    this.out.gain.setTargetAtTime(v, this.ctx.currentTime, 0.01);
  }

  // Trigger one note.
  //   midi      : midi note number
  //   time      : audiocontext time to start
  //   duration  : seconds until the next step (for gate + slide length)
  //   accent    : boolean
  //   slide     : boolean (glide from previous note, and let it ring into next)
  play(midi, time, duration, accent, slide) {
    const ctx = this.ctx;
    const freq = midiToFreq(midi + this.tuning);

    // --- Pitch (with optional slide/portamento) ---
    if (slide) {
      this.osc.frequency.setValueAtTime(this._lastFreq, time);
      this.osc.frequency.exponentialRampToValueAtTime(freq, time + Math.min(0.12, duration * 0.9));
    } else {
      this.osc.frequency.setValueAtTime(freq, time);
    }
    this._lastFreq = freq;

    // --- Resonance ---
    const q = 2 + this.resonance * 28;
    this.filter.Q.setValueAtTime(q, time);

    // --- Filter envelope ---
    // Base cutoff maps exponentially for a musical feel.
    const baseCut = 120 * Math.pow(60, this.cutoff); // ~120Hz .. ~7kHz
    const envDepth = this.envMod * (accent ? 5000 : 3200) * (0.4 + this.cutoff);
    const accentPush = accent ? 1.6 : 1.0;
    const peak = Math.min(baseCut + envDepth * accentPush, 12000);
    const decayTime = 0.03 + this.decay * 0.9;

    this.filter.frequency.cancelScheduledValues(time);
    this.filter.frequency.setValueAtTime(peak, time);
    this.filter.frequency.exponentialRampToValueAtTime(
      Math.max(baseCut, 80),
      time + decayTime
    );

    // --- Amp envelope ---
    const peakGain = accent ? 1.0 : 0.75;
    const gate = slide ? duration * 1.02 : Math.min(duration * 0.9, 0.28);
    this.amp.gain.cancelScheduledValues(time);
    this.amp.gain.setValueAtTime(this.amp.gain.value, time);
    this.amp.gain.linearRampToValueAtTime(peakGain, time + 0.004);
    if (slide) {
      // Sustain into the next note.
      this.amp.gain.setValueAtTime(peakGain, time + gate - 0.01);
    } else {
      this.amp.gain.setTargetAtTime(0.0001, time + 0.02, 0.06 + this.decay * 0.12);
    }
  }
}

// ---------------------------------------------------------------------------
// Drum voices — analog-style synthesis (808/909 flavored).
// Each returns a small graph triggered at a given time, routed to `dest`.
// ---------------------------------------------------------------------------
export class DrumMachine {
  constructor(ctx, dest) {
    this.ctx = ctx;
    this.dest = dest;
    this.noiseBuffer = this._makeNoise();
    // Per-instrument gains.
    this.gains = {};
  }

  _makeNoise() {
    const ctx = this.ctx;
    const buf = ctx.createBuffer(1, ctx.sampleRate * 1.0, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    return buf;
  }

  _noiseSource() {
    const src = this.ctx.createBufferSource();
    src.buffer = this.noiseBuffer;
    src.loop = true;
    return src;
  }

  _out(vel = 1) {
    const g = this.ctx.createGain();
    g.gain.value = vel;
    g.connect(this.dest);
    return g;
  }

  trigger(name, time, vel = 1) {
    const fn = this['_' + name];
    if (fn) fn.call(this, time, vel);
  }

  // ---- Bass drum (808-style: sine with pitch drop) ----
  _bd(time, vel) {
    const ctx = this.ctx;
    const osc = ctx.createOscillator();
    osc.type = 'sine';
    const g = this._out(vel);
    const click = ctx.createOscillator();
    click.type = 'triangle';

    osc.frequency.setValueAtTime(150, time);
    osc.frequency.exponentialRampToValueAtTime(48, time + 0.09);
    g.gain.setValueAtTime(1.1, time);
    g.gain.exponentialRampToValueAtTime(0.001, time + 0.42);

    // transient click
    const cg = ctx.createGain();
    cg.gain.setValueAtTime(0.6, time);
    cg.gain.exponentialRampToValueAtTime(0.001, time + 0.02);
    click.frequency.setValueAtTime(600, time);
    click.connect(cg).connect(g);

    osc.connect(g);
    osc.start(time); osc.stop(time + 0.45);
    click.start(time); click.stop(time + 0.03);
  }

  // ---- Snare (tone + noise) ----
  _sd(time, vel) {
    const ctx = this.ctx;
    const g = this._out(vel * 0.9);
    // Two tuned oscillators for the body.
    [180, 278].forEach((f) => {
      const o = ctx.createOscillator();
      o.type = 'triangle';
      o.frequency.setValueAtTime(f, time);
      const og = ctx.createGain();
      og.gain.setValueAtTime(0.5, time);
      og.gain.exponentialRampToValueAtTime(0.001, time + 0.1);
      o.connect(og).connect(g);
      o.start(time); o.stop(time + 0.12);
    });
    // Noise snap.
    const n = this._noiseSource();
    const bp = ctx.createBiquadFilter();
    bp.type = 'highpass';
    bp.frequency.value = 1500;
    const ng = ctx.createGain();
    ng.gain.setValueAtTime(0.8, time);
    ng.gain.exponentialRampToValueAtTime(0.001, time + 0.18);
    n.connect(bp).connect(ng).connect(g);
    n.start(time); n.stop(time + 0.2);
  }

  // ---- Closed hat ----
  _ch(time, vel) {
    this._hat(time, vel, 0.045, 0.7);
  }
  // ---- Open hat ----
  _oh(time, vel) {
    this._hat(time, vel, 0.32, 0.5);
  }
  _hat(time, vel, dur, level) {
    const ctx = this.ctx;
    const g = this._out(vel * level);
    const n = this._noiseSource();
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = 7000;
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 10000;
    bp.Q.value = 1.2;
    g.gain.setValueAtTime(0.7, time);
    g.gain.exponentialRampToValueAtTime(0.001, time + dur);
    n.connect(hp).connect(bp).connect(g);
    n.start(time); n.stop(time + dur + 0.02);
  }

  // ---- Clap ----
  _cp(time, vel) {
    const ctx = this.ctx;
    const g = this._out(vel * 0.8);
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 1100;
    bp.Q.value = 1.5;
    // Three fast bursts + tail.
    const offsets = [0, 0.01, 0.02, 0.03];
    offsets.forEach((off, i) => {
      const n = this._noiseSource();
      const ng = ctx.createGain();
      const t = time + off;
      const peak = i === offsets.length - 1 ? 0.7 : 0.5;
      ng.gain.setValueAtTime(peak, t);
      ng.gain.exponentialRampToValueAtTime(0.001, t + (i === offsets.length - 1 ? 0.15 : 0.02));
      n.connect(ng).connect(bp);
      n.start(t); n.stop(t + 0.16);
    });
    bp.connect(g);
  }

  // ---- Rimshot / clave ----
  _rs(time, vel) {
    const ctx = this.ctx;
    const g = this._out(vel * 0.7);
    const o = ctx.createOscillator();
    o.type = 'square';
    o.frequency.setValueAtTime(1700, time);
    const og = ctx.createGain();
    og.gain.setValueAtTime(0.6, time);
    og.gain.exponentialRampToValueAtTime(0.001, time + 0.03);
    o.connect(og).connect(g);
    o.start(time); o.stop(time + 0.04);
  }

  // ---- Toms ----
  _lt(time, vel) { this._tom(time, vel, 100); }
  _mt(time, vel) { this._tom(time, vel, 160); }
  _ht(time, vel) { this._tom(time, vel, 240); }
  _tom(time, vel, f) {
    const ctx = this.ctx;
    const g = this._out(vel * 0.9);
    const o = ctx.createOscillator();
    o.type = 'sine';
    o.frequency.setValueAtTime(f * 1.8, time);
    o.frequency.exponentialRampToValueAtTime(f, time + 0.1);
    g.gain.setValueAtTime(0.9, time);
    g.gain.exponentialRampToValueAtTime(0.001, time + 0.3);
    o.connect(g);
    o.start(time); o.stop(time + 0.32);
  }

  // ---- Cowbell ----
  _cb(time, vel) {
    const ctx = this.ctx;
    const g = this._out(vel * 0.6);
    [540, 800].forEach((f) => {
      const o = ctx.createOscillator();
      o.type = 'square';
      o.frequency.value = f;
      const og = ctx.createGain();
      og.gain.setValueAtTime(0.4, time);
      og.gain.exponentialRampToValueAtTime(0.001, time + 0.25);
      o.connect(og).connect(g);
      o.start(time); o.stop(time + 0.26);
    });
  }

  // ---- Crash cymbal ----
  _cy(time, vel) {
    const ctx = this.ctx;
    const g = this._out(vel * 0.5);
    const n = this._noiseSource();
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = 5000;
    g.gain.setValueAtTime(0.6, time);
    g.gain.exponentialRampToValueAtTime(0.001, time + 0.9);
    n.connect(hp).connect(g);
    n.start(time); n.stop(time + 0.95);
  }
}
