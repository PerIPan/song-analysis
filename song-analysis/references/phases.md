# Phases 1–7 in detail — what each step does, its commands, its traps

`scripts/run.py` runs these steps in order (step names in brackets) with the right
interpreters; this page is what each one does and how to run it by hand. `<venv>` = the
analysis venv; Whisper, lv-chordia, demucs and ADTOF have their own
(`environment-setup.md`). `ST=stems/htdemucs_ft/<song>`. After any step,
`scripts/validate_artifacts.py analysis` checks the hand-offs.

**Run order** (what `run.py` does): stems on the GPU lane first, the pulse beside them on
the CPU lane; Whisper needs only the vocal stem; everything keyed by `(bar, cell)` waits for
the meter, and mode, chords, validation and the chart also for the bass step's downbeat
check. Moving beat 1 later re-runs all of it (with `run.py`, ~30 s of compute).

## Phase 1 — Pulse and key [pulse] (no meter assumed)

```bash
<venv>/bin/python scripts/foundation.py pulse <song.mp3> --out analysis/foundation.json
```

Tracks beats with **no bar assumption** — never pass `beats_per_bar=(3, 4)`: a constrained
candidate list can't say "neither", so it returns the least-bad option with full
confidence and every bar count inherits it. Writes `pulse_bpm`, `beat_times`,
`key_top2` and `tempo_octave`: a pulse above 160 BPM is flagged as probably eighth notes
(a 91 BPM soul track was tracked at 182), one below 70 as possibly half-time. If the
user's count disagrees, re-run with `--min-bpm`/`--max-bpm` to force the other octave.
A GRID REPAIR over a long stretch (a quiet intro) is the same slip — check the octave.
**Cross-check online:** look the song up on songbpm.com and tunebat.com (page tools work
there). They catch a gross error, but often list the doubled octave (a song at 87 shown as
174, "87 half-time") and the melody's key — they don't decide the octave or the tonic;
note what they say in the provenance.

**Key: the top two are the melody's key, not the tonic.** The madmom CNN beats chroma +
Krumhansl by ~20 MIREX points and fixes relative-major/minor flips, but knows only 24
major/minor keys, and its probability is not a confidence on modal or drone material (a
Lydian track came out as the wrong key at p = 0.59). After Phase 4, take the pitch class
the bass sustains longest: if it disagrees, trust the pedal as the tonic and name the mode
with the mode test (`modal-theory.md`).

## Phase 2 — Stems [stems, stems_6s]

**Decide the split from the purpose, early** (ask with the inputs if unclear: chart only,
drums/bass, or the guitar/piano parts too — e.g. for a Live sketch or remix):

| Purpose / song | Run | Keep |
|---|---|---|
| **default** (a full analysis, a Live sketch or remix) | `htdemucs_ft`, **then** `htdemucs_6s` | the four from `_ft` + only `guitar.wav` / `piano.wav` from `_6s` |
| only a chart, the drums or the bass, and the user says so | `htdemucs_ft` (4 stems) | all four |

The 4-stem `_ft` is the cleaner split (vocals, drums, bass): never replace it with the
6-stem run, which bleeds keys into the bass. In `other.wav` the guitars, keys and pads are
one mix, so a guitar-led song needs the extra run.

```bash
ffmpeg -v error -i <song.mp3> -c:a pcm_s16le /tmp/<song>.wav     # decode first (see below)
demucs -n htdemucs_ft -d mps -o stems /tmp/<song>.wav   # → $ST/{bass,drums,vocals,other}.wav
demucs -n htdemucs_6s -d mps -o stems /tmp/<song>.wav   # guitar/piano songs: keep only
                                                        # stems/htdemucs_6s/<song>/{guitar,piano}.wav
```

**Decode MP3 to WAV first:** demucs 4.1 reads MP3 without the gapless trim, so every stem
starts 25 ms late against the mix — enough to smear bass and beat timing. `-d mps` on Apple
Silicon (otherwise CPU, ~3× slower). A fetched WAV needs no decode: copy it to
`/tmp/<song>.wav` (a name without spaces, so `$ST` needs no quoting). **Check the model cache first** —
uncached, `htdemucs_ft` downloads 4 × 84 MB silently. Listen to `bass.wav` alone: piano or
guitar in it means separation struggled. Faster/other options and timings:
`stems.md`.

## Phase 3 — Meter [sweep, meter] (sweep every cycle, then decide)

```bash
<venv>/bin/python scripts/detect_meter.py <song.mp3> --drums $ST/drums.wav \
    --bass $ST/bass.wav --other $ST/other.wav \
    --foundation analysis/foundation.json --json analysis/meter.json
<venv>/bin/python scripts/foundation.py meter [--pulse-unit 8] [--use-alternative | --cycle N ...]
```

The sweep folds band-limited onsets onto every period 2–25 and ranks by accent contrast;
songs without a kit still carry the cycle in the bass and harmony, so always pass
`--bass` and `--other`. It reports a cycle, the downbeat (counted with the kick) and the
main split (`grouping`, e.g. 6+5) — or **INCONCLUSIVE**.

If the sweep is INCONCLUSIVE or the pulse is slow, it also tries a 2× (eighth-note) grid
— a half-time grid hides odd cycles — and prints the result with the command to adopt it.
It warns when successive beat intervals run in a 3:2 ratio: the tracker may be following
aksak groups (2+2+3) as uneven beats.

`foundation.py meter` then writes `beats_per_bar`, `pulse_unit`, `time_signature`,
`grouping`, `downbeat_times`, `num_bars`, `bar_bpm`, `tempo_drift_pct` (spread of the middle
90% of bars), `tempo_outlier_bars` (more than 5% off) and `live_tempo`. A tracker that drops
a tempo octave for a stretch is repaired in Phase 1 (`grid_repair` lists where).
**It stops with a question instead of guessing** — put that question to the user and
re-run with their answer: INCONCLUSIVE (count along), a phrase-length cycle (8/16 → 4/4?),
a bare duple (2/4 or 4/4?), two equally strong accents (which one is beat 1?), or an odd
cycle (eighth or quarter pulse — 11/8 vs 11/4 doubles Live's tempo). INCONCLUSIVE with
one band clear (often the bass, when the kit enters late) — put that band's cycle and
beat 1 to the user as the proposal, then `--cycle`/`--downbeat-pulse`. Reading the sweep,
calibration, and why beat trackers' own downbeats aren't used:
`meter-detection.md`.

**Four-on-the-floor kits** (kick on every beat) give the kick band no cycle, so the sweep
reports INCONCLUSIVE or a bare duple; the bass and harmonic bands carry the meter, and a
2-and-4 backbeat can't tell pulse 0 from pulse 2. When you must pick beat 1 yourself,
weigh (strongest first): the first full-band hit at the song's start (a drum-only pickup
before it is common); the phase where bass and chords change (Phase 4 downbeat check).
Cymbal accents alone are weak — a crash pattern can sit on beat 3. Whoever chose what
the flags set is recorded: add `--decided-by player` when the player counted it; without
it the provenance says `agent` (Claude's call), the script says so, and
`chart_questions.py` makes the meter and beat 1 its first question — say so in the chart
header until the player confirms. A question exits 2 (`NEEDS A DECISION` on stderr); 1 is
an error.

**Cells.** Everything downstream (bass, chords, lyrics, chart) is keyed by `(bar, cell)`,
one cell per group in `grouping`: 4/4 → 2+2 (the familiar half-bars), 3/4 → one cell,
6/8 → 3+3, 11/8 as 6+5 → two unequal cells. Never split an odd bar at its midpoint.

**Sanity checks:** `tempo_drift_pct` above ~3% means one BPM misplaces notes by the end —
place them through the beat grid (`ableton-mcp` → "Timing"). Watch half/double time on
slow songs (60–90 BPM) — count along. A `num_bars` far from
`duration ÷ (beats_per_bar × beat)` means rubato, a wrong tempo octave or a wrong meter.

## Phase 4 — Bass, tonic and mode [bass, mode]

```bash
<venv>/bin/python scripts/bass_notes.py $ST/bass.wav --foundation analysis/foundation.json \
    [--bass-entry-bar <N>] --outdir analysis
<venv>/bin/python scripts/mode_test.py --other $ST/other.wav \
    --foundation analysis/foundation.json --bass-cells analysis/bass_per_cell.json \
    [--sections analysis/sections.json] --out analysis/mode.json
```

`bass_notes.py`: **pyin** (why not CREPE: the `bass-transcribe` skill) → `bass.mid` and
each pitch class's sounding time per `(bar, cell)`. basic-pitch only if the part is
polyphonic.

**Downbeat check — before anything else keyed by bar.** `bass_notes.py` counts where in
the bar the bass changes pitch. If a later cell takes most changes (a loop moving on beat
3 of 4/4), it prints `DOWNBEAT CHECK` with the corrected `--downbeat-pulse`: re-run
`foundation.py meter` with it, then `bass_notes.py`. The one legitimate exception is
harmony deliberately pushed off beat 1 — confirm with the song-start hit before shifting.
 **The tonic is the pitch class the bass sustains longest** — not the key
estimate. `mode_test.py` then names the mode by dueling characteristic degrees bar by bar
(3 vs ♭3, 4 vs ♯4, 7 vs ♭7, 2 vs ♭2, 6 vs ♭6); a degree that doesn't sound doesn't vote,
so a drone with no 6th reports "6th undetermined" instead of a guess. On a player-verified
Lydian track: tonic E (57% of bass time), ♯4 in 32/32 bars — where the key CNN said G♯
minor. With `sections.json` it runs per section and flags a tonic change only if it holds
8+ bars. Method: `modal-theory.md`.

**Spell pitch classes from the key signature.** Flats for flat and neutral keys; sharps
for sharp keys — in F♯ minor a flat table writes the tonic `G♭m` and the dominant `D♭7`.

- Sub-0.5 s detections are noisy; ≥ 0.7 s sustained notes are usually right.
- Bass pedals, walks, sits on 3rds/5ths — it's a *clue* to the root, not the chord.
- **Bass enters late** in most songs: `bass_notes.py` prints `BASS ENTRY: bar N` when it
  finds one — re-run it with `--bass-entry-bar N` (earlier notes are stem bleed);
  `chord_proposal.py` reads the bar from `bass_notes.json` and warns if it was skipped.
- `bass.mid` is timed in seconds at pretty_midi's 120 BPM, not on the song's bars: in a
  DAW, place notes through the beat grid (`ableton-mcp` → "Timing").

## Phase 4b — Performance [drums, strum]: the drummer's hits and the guitar's strumming

```bash
<adtof-venv>/bin/python scripts/drum_transcribe.py $ST/drums.wav \
    --foundation analysis/foundation.json                 # → drum_hits.json, drums.mid
<venv>/bin/python scripts/strum_pattern.py stems/htdemucs_6s/<song>/guitar.wav \
    --foundation analysis/foundation.json [--sections analysis/sections.json] # → strum.json
```

A chart says which chord; a band (and a Live sketch) also needs **how** it's played.
`drum_transcribe.py` labels every hit (ADTOF: kick, snare, hat, toms, cymbals; the stem
is peak-normalised first) with a velocity from the stem, and lists the **fill bars** — a
tom when toms are rare; twice the usual tom bar when the drummer grooves on the toms (a
surf beat put toms in half the bars); or a crowded last beat. On the first two songs they
sat before section changes. It can't tell crash from ride well (one cymbal class). A
guitar under 4 attacks a bar holds its chords (reverb, surf): no strum pattern is read. `strum_pattern.py` snaps the
guitar's onsets to the 16ths of each bar and prints each section's pattern (`D`/`U` by
the hand-motion convention, not measured) — on its first song it showed the verse push on
4& the player described. Both keep every hit's real time and strength for the sketch.
Skip 4b when the purpose is only a chart.

## Phase 5 — Lyric timing [lyrics, lyrics_mix] (Whisper, gated by the vocal stem)

```bash
<whisper-venv>/bin/python scripts/whisper_gated.py $ST/vocals.wav [--language en] \
    --out analysis/lyrics.json
<whisper-venv>/bin/python scripts/whisper_gated.py $ST/vocals.wav --mix <song.mp3> \
    [--language en] --out analysis/lyrics_mix.json          # when canonical lyrics exist
```

An RMS gate on the vocal stem, fed to Whisper as `clip_timestamps`, keeps it from
transcribing silence; the script also sets large-v3-turbo's word-alignment heads and drops
words whose *whole* span is silent. **Which audio to transcribe is song-dependent:**
measured with this exact setup on 6 benchmark songs, the vocal stem averaged 19.8% word
error and the full mix 23.6%, but either one won by up to 25 points on single songs
(published results favouring the mix used Whisper without the gate). With canonical
lyrics, transcribe both and let Phase 6 keep the one matching more of the lyrics — that
picked the better transcription every time (17.9%). Without lyrics, use the vocal stem.
Force `--language` when detection wobbles (chant, non-English). Keep repeated lines —
mantras are lyrics — until Phase 6 has aligned them. Whisper invents subtitle phrases over
music ("Thanks for watching"): known ones are dropped, and `CHECK BY EAR` names any short
phrase standing alone in an instrumental stretch.

Map each word to a bar:

```python
def locate(t, downbeats, beats_per_bar):     # from foundation.json — never assume 4
    for i in range(len(downbeats)-1):
        if downbeats[i] <= t < downbeats[i+1]:
            return (i+1, (t - downbeats[i]) / (downbeats[i+1] - downbeats[i]) * beats_per_bar)
    return None
```

## Phase 6 — Sections [align] (canonical lyrics aligned to the word times)

```bash
python3 scripts/align_lyrics.py --lyrics lyrics.txt --words analysis/lyrics.json \
    --words analysis/lyrics_mix.json --foundation analysis/foundation.json
    # keeps the better transcription → lyrics_aligned.json, sections.json
```

Keeps the **canonical text** and borrows only Whisper's times: a monotonic alignment with
fuzzy word matching (accents and Greek final sigma normalised) pairs canonical words with
heard words; dropped lines — normal on repeats — get times interpolated between matched
neighbours, and lines under 30% matched are flagged; `SUNG, NOT IN THE TEXT` names Whisper
words sung just before a line that the page left out ("I'm coming back…" written
"Coming back…") — check by ear, add them. In `lyrics.txt` a blank line starts a
section and a `[Chorus]` line labels it; each section gets its first line's time and
`(bar, cell)`. On the benchmark, 83% of line starts landed within 1 s (median error
~0.5 s) and 98% of section starts within 2 s. Automatic segmentation can *suggest* boundaries, never decide them:
`as_seg` (barwise CBM on this song's own bars, `penalty_weight=0`) hit 80% of
lyric-anchored boundaries within ±1 bar on the one reference song with section truth,
27% within ±0.5 s.

## Phase 7 — Chords [chords, chords_lv, tab] (lv-chordia, cross-checked)

```bash
<venv>/bin/python scripts/chord_proposal.py --other $ST/other.wav --bass $ST/bass.wav \
    --foundation analysis/foundation.json \
    --out analysis/chord_proposal.json      # triad cross-check; bass entry bar from bass_notes.json
<lv-venv>/bin/python scripts/lv_chords.py <song.mp3> --foundation analysis/foundation.json \
    --compare analysis/chord_proposal.json --out analysis/chords_lv.json
```

**lv-chordia is the provisional primary reading** — it names 7ths and inversions, which
the triad method can't, and led it on all three benchmark songs (two scored against
another automatic tool, one against a player's ear; `chord-proposal.md`). Three
songs is a small sample: it is weakest on rare qualities, and anything beyond 7ths
(add9, ♯11) is untested — read those by ear. Run it on the **full mix**.

**The triad method is the independent cross-check** (bass-root constraint with slash
relaxation, major bias **0**, flip count, per-cell margin). `--compare` lists cells where
the two disagree on the root — check those by ear with the Trap 1 tests.

**Read first, then check against a tab** (when `lyrics_from_page.py` found one):
`tab_compare.py --tab analysis/tab_chords.json --chords analysis/chords_lv.json
--sections analysis/sections.json --bass analysis/bass_per_cell.json` lists per section
the chords only in the tab (never in the bass → a passing chord over a held bass, or
wrong), only in ours (a tab simplification?), and the same root with the other third.
A tab is a second opinion — often simplified or transposed — never the chart's source;
name it and the agreement in the provenance, and its disagreements in the open questions.

**Where the bass drops out, agreement proves little.** In a breakdown both readers hear
only the upper voices, and chords sharing them pass for each other: both said Am where the
player heard G (a chorus-2 turnaround, bass out) — the parallel chorus-1 bar, with bass,
read G. In bass-less cells, chart what the parallel section plays and list it for the ear.
