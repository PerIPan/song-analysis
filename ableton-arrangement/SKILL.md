---
name: ableton-arrangement
description: Use when composing or arranging a song in Ableton Live — section design, track layout, bass and drum patterns in any meter, lead lines, effects chains, dynamics — including reinterpreting a song in a new genre or building from a chart or MIDI.
---

# Ableton Arrangement — composing full songs via MCP

Song-agnostic patterns for fleshing a song idea (MIDI or chart in hand) into a full
arrangement. Validated on a hardcore-punk 11/4 reinterpretation of a Byzantine hymn;
applies to any genre/key/meter. Connection mechanics and device gotchas live in the
`ableton-mcp` skill; analysis of existing recordings in `song-analysis`.

## Track layout template

Works for rock/punk/electronic/cinematic reinterpretation:

| Track | Role |
|---|---|
| **Reference (muted)** | Original melody/reference audio for A/B |
| **Melody / Voices** | Lead vocal or chant melody MIDI |
| **Bass** | e.g. `Deep Hop Bass` rack, `Electric Basic Bass`, `String Studio` |
| **Rhythm Guitar** | Power chords — `Guitar-Dual Amped Heavy` (heavy) / `Crunch` (medium) |
| **Drums** | Kit (Memphis Studio etc.) — kick=36, snare=38, hh_closed=42, hh_open=46, crash=49, ride=51, toms=41/43/45 |
| **Lead Guitar** | Same guitar rack as rhythm, Amp Gain pushed (~115/127) |
| **Color/Aux** | Trumpet, strings, pads — punctuates bridges, fills holes |

One MIDI clip per track at song length (e.g. 198 beats for 18 bars of 11/4). Slot 8 is a
good "live" slot; leave slots 0–7 for variations.

## Section design

At least 5 sections, each with its own character:

| Section | Bars (typical) | Function |
|---|---|---|
| Intro | 1–2 | Bass + lead color only. No rhythm guitar. Anticipation. |
| Verse build | 3–4 | Rhythm guitar enters. Bass still sparse. |
| Chorus | 5–8 | Full instrumentation, peak energy. |
| Bridge | 9–12 | Pull back — sparse; a NEW instrument enters (trumpet, strings). Lead silent. |
| Solo | 13–16 | Lead foreground. Drums change pattern (ride > closed hat). |
| Outro | 17–18 | Breath, then finale hit. |

Each instrument changes role per section — never the same density throughout. The
contrasts create the song's narrative.

## Dynamic techniques (proven to add soul)

1. **Pre-section drops** — silence drums + bass for 1 beat before each section change.
   The ear reaches for the missing beat → next section HITS harder.
2. **Section-based volume automation** via `set_clip_automation` "Volume": Intro 0.65,
   Build 0.85, Bridge 0.70–0.78, Solo 0.95, Outro 0.70 → 1.0.
   ⚠️ Only works where the track exposes Volume as automatable — bass usually does; drum
   kit racks and guitar amp racks often DON'T ("Parameter not found") → fall back to
   per-note velocity or a manual envelope.
3. **Drum ghost notes** — quiet snares (vel 24–38) ~0.25–0.5 beats before each main
   snare. Skip the bridge.
4. **Solo-specific drums** — swap constant closed hats for ride on chord-change beats +
   open-hat splashes at offbeats. ~50% fewer notes; breathing room.
5. **Pre-solo crash** (pitch 49) at the solo's first beat.
6. **Tom fills at section boundaries** — Hi → Mid → Low over 0.5–1 beat, vel ramp 80→110.

## Bass pattern palette (per-bar, never uniform)

| Pattern | Use case | Per 4/4 bar | Per 11/4 bar |
|---|---|---|---|
| **DRIVE** (8ths on root) | High-energy chorus/solo | 8 | 22 |
| **BREATH** (half + quarter feel) | Verse/build, space | 2–3 | 4–6 |
| **SLIDE** (last 2 8ths step up) | Section transitions | 8 ending up | 22 ending up |
| **STAB** (sustains) | Bridge, sparse | 2–3 | 5 |
| **STAC_AIR** (rests + isolated hits) | Punk breaks | 2–4 | 4–6 |
| **OCT** (root/octave alternation) | Push energy | 8 | 22 |
| **ACCENT** (3+3+2 grouping, vel accents) | Solo entry | 8 | 22 |
| **WALK/CLIMB** (scale walk between roots) | Transitions | varies | varies |

**Don't DRIVE every bar** — constant 8ths sound like a sequencer. Mix patterns; ~50–100
notes total per *song section*, not hundreds. Punk reference (four consecutive bars):
DRIVE → BREATH+SLIDE → STAC_AIR → ACCENT.

## Drum conventions per meter

- **4/4 rock/punk:** kick 1+3, snare 2+4, closed hat every 8th.
- **11/4 (3+4+4):** kick 1, 4, 8 (sub-group downbeats); snare 3, 7, 11 (sub-group ends).
- **9/8 zeibekiko (4+5):** kick 1, 5; snare varies by sub-style.
- General: hat velocity −22% to avoid harsh top; crash on section entries; tom fill at
  the bar before transitions.
- **HARD RULE — drummer-playable:** patterns must be humanly performable. No sustained
  32nds at moderate tempos, hands alternate, no impossible limb stacks (e.g. 3
  simultaneous hand hits). If a real drummer couldn't play it, rewrite it.
- Match the source genre's drum logic when reinterpreting (see `song-analysis`
  references/drum-pattern-analysis.md) — don't impose a rock backbeat on laiko.

## Lead guitar techniques (in order of subtlety)

1. **Power chord swells** (root+5th+octave) on changes; strum offsets 12–80 ms.
2. **Chord-tone landings** on strong beats; scale tones connect.
3. **String-pull bends** — diatonic-step-below grace (~0.15 beat) before a peak.
   Selective only — every-note bends sound fake.
4. **Re-plucks** — split a sustain into long+short same-pitch pair (~0.05 beat gap).
   Phrase peaks and final resolutions only.
5. **Chromatic approach** for horns — half-step grace below each stab (D# → E).

Power-chord chart shorthand (single letters, no quality): see `song-analysis`
references/modal-theory.md.

## Effects chains

**Bass — punk grit (cuts through):** Overdrive (Drive 35, Tone 60, Dry/Wet 45 —
parallel) → EQ Eight (HP 40 Hz, −2 dB @ 250, +3.5 dB @ 1k presence, +2 dB @ 1.5k growl)
→ Compressor (4:1, threshold ~−15 dB, makeup on).

**Rhythm guitar — wide and warm:** rack Chorus macro ~75, Room ~70 → Chorus-Ensemble
(Ensemble mode, Width 0.85, Warmth 0.65, Dry/Wet 0.35) → EQ Eight (HP 60 Hz, +2.5 dB @
200 body, −1.5 dB @ 3.5k smooth top).

**Lead — distortion:** rack "Amp Gain" macro 110–120 (88 = clean-ish, max 127), drop
"Amp Volume" ~10 to compensate; Chorus-Ensemble + Reverb after the amp = soaring solo.

**Mastering** (stock Remote Script: by hand; patched — `ableton-mcp` patch 2 — `insert_device` on the Master track, or `remix_build.py --master`): EQ Eight (HP 30 Hz, +1 dB @ 3k, +1.5 dB
@ 10k air) → Glue Compressor (2:1, Attack 10 ms, Release Auto, Makeup +2 dB, 1–2 dB GR)
→ Limiter (ceiling −0.3 dB, ~−12 LUFS modern / ~−9 LUFS aggressive punk).

## Arrangement-specific MCP cautions

(Full gotcha list → `ableton-mcp` skill.)
- Drum clips with 500+ notes exceed read token limits — work from locally-saved JSON.
- **Read the clip before wiping.** The user hand-edits clips mid-session ("made a few
  changes") — filter + re-push over wipe + full push; `remove_notes` by range.
- Volume automation rejected on rack tracks → per-note velocity.
- UI says "track 11" → MCP index 10.

## Iteration patterns that worked

- **Save every meaningful state to JSON** — easy revert, diff history.
- **Push in 2–3 chunks**, not 6–9.
- **Filter + add over wipe + push** for small changes.
- **Re-read the clip when the user says "made changes"** — never trust last-saved state.
- **Get direction before big rewrites** (AskUserQuestion when the request is ambiguous).
- **Test small first** — one section, then propagate.

## When NOT to use this workflow

- Live recording sessions — manual playing beats MCP for tracking.
- One-note tweaks — Ableton UI directly.
- Auditioning samples — browser preview is faster.
- Final mastering — needs manual ears and tools beyond MCP.

## Local environment (this machine)

- Note generators live in `~/dev/abletonAI/audio-analysis/` (`gen_*.py`,
  `build_*.py`) — bass palettes, drum fills, lead techniques implemented there.
- Source doc (read-only): `WORKFLOW-ableton-arrangement.md` in the same folder.
