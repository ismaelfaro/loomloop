# RE·LOOM — a ReBirth-inspired web simulator

A browser reimagining of Propellerhead's classic
[**ReBirth RB-338**](https://en.wikipedia.org/wiki/ReBirth_RB-338): two
**Roland TB-303**-style acid bass lines and an **808 / 909**-flavored drum
machine, wired through a shared distortion + delay + compressor master bus.

Everything is **synthesized live** with the Web Audio API — there are no audio
samples and no network calls. It's plain ES modules and CSS, no build step and
no dependencies.

```
rebirth/
├── index.html   # UI shell + transport + FX rack
├── styles.css   # retro Roland-style panel design
├── audio.js     # Web Audio engine: MasterBus, Bassline (303), DrumMachine
└── app.js       # state, lookahead clock/sequencer, and UI wiring
```

## Run it

Because it uses ES modules, open it through a tiny static server (opening the
file over `file://` will be blocked by module CORS rules):

```bash
cd rebirth
python3 -m http.server 8000
# then visit http://localhost:8000
```

Any static host works just as well.

## What's inside

**Two TB-303 bass lines** — each a monophonic oscillator (saw / square) →
resonant low-pass filter → amp VCA, with the signature per-note filter
envelope. Knobs: Tune, Cutoff, Resonance, Env Mod, Decay, Accent, Volume, and a
waveform toggle. Per step you set **pitch** (drag the slider), plus **Gate**,
**Accent** (louder + bigger filter sweep) and **Slide** (portamento that rings
into the next step) — the three ingredients of an acid line.

**Drum machine** — 11 analog-style voices synthesized from scratch (Bass Drum,
Snare, three Toms, Rimshot, Clap, Cowbell, Closed/Open Hat, Crash). Click a
cell to cycle **off → hit → accent**; each voice has its own volume, and the
label auditions the sound.

**Transport & patterns** — play/stop (<kbd>Space</kbd>), 60–200 BPM, swing, 4
pattern slots (A–D) with copy, and per-track Random / Clear. The sequencer uses
the lookahead-scheduling technique for sample-accurate timing that stays steady
even when the tab is busy.

**Master FX** — waveshaper distortion, feedback delay, and a glue compressor.

A starter groove is loaded in pattern **A** so it makes sound the moment you hit
Play.
