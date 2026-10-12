---
name: song-analysis
description: Use when a song recording has to become tempo, time signature, key, stems, a bass line, chords per bar, lyric timing, a drum-pattern read, or a chord+lyric chart for a band — including songs in odd or unknown meters.
---

# Song Analysis — recording → bars, chords, lyrics, chart

Song-agnostic pipeline, validated over many real projects (dream pop, Greek laiko, punk
reinterpretations, drone/devotional). Any song, genre, key or meter.

**Deliverable:** one self-contained HTML per song — the chord+lyric chart plus the
commentary (Phase 8), checked by a player, published to the band as HTML + PDF. The JSON
artifacts are working files, not the answer.

## Hard rules — read first

1. **Never assume 4/4.** The meter, grouping and pulse unit come from the sweep and
   `foundation.py meter`; never pass a constrained candidate list (`beats_per_bar=(3, 4)`)
   to a tracker. Everything downstream is keyed by `(bar, cell)`, one cell per group of the
   grouping (4/4 → 2+2, 3/4 → one cell, 11/8 as 6+5 → two unequal cells; never split an odd
   bar at its midpoint).
2. **Ask, don't guess.** A script that stops with `NEEDS A DECISION` (exit 2) or a
   `QUESTION` from `run.py` is a question for the user: put it to them as printed, then
   answer with their words. A player's count settles in seconds what a sweep can only rank.
3. **Beat 1 before anything keyed by bar.** Confirm the meter and beat 1 with the player
   when they are Claude's call or measured at LOW confidence (`chart_questions.py` asks
   first). Moving beat 1 later re-runs every bar-keyed step (`run.py`: ~30 s).
4. **The player checks the chart before the band gets it**, and while they correct it the
   data file is the only thing that changes (below). Rules change after the session,
   against every song's recorded corrections.
5. **Never retype lyrics through your own output** — copyrighted text is blocked. Move a
   page's text into `lyrics.txt` with `scripts/lyrics_from_page.py` (it prints only counts).
6. **Shared folders only with a yes.** Publishing writes to the band's folder: ask first.
7. **Key ≠ chord quality; lv-chordia is a reading, not the truth** (traps below).

## Run it — `scripts/run.py`

```bash
python3 scripts/run.py doctor                 # once: interpreters, ffmpeg, model caches
python3 scripts/run.py run <song folder>      # Phases 1–8, skipping what is done
python3 scripts/run.py status <song folder>   # each step: done / stale (why) / to do
python3 scripts/run.py answer <song folder> --cycle 4 --decided-by player   # then run again
```

The song folder holds the recording (Phase 0 fetches it from a name) and `lyrics.txt`.
`run.py` runs every step with its interpreter, the GPU lane (demucs, Whisper) beside the
CPU lane (one song's `run.py` at a time on one GPU; queue several songs one after another), and prints each step's summary as the script wrote it. It re-runs a step only
when its inputs, answers or script changed, so it resumes after a usage limit or a fix.
When a step asks, it stops what depends on the answer (the rest carries on) and prints
the question and the `run.py answer` that settles it; the answer flags are the scripts'
own (`--cycle --grouping --downbeat-pulse --use-alternative --pulse-unit --min-bpm
--max-bpm --bass-entry-bar --language`, plus `--keep-downbeat`, `--no-6s`, `--performance`,
`--decided-by player` when the player counted). A late bass entry is taken by itself.
State and answers: `analysis/run.json`; logs: `analysis/logs/`; times:
`analysis/timings.jsonl`. A folder analysed by hand is adopted as it is. Each step is
also a script you can run by hand: `references/phases.md`.

| Phase | Steps (`run.py`) | Script | Output |
|---|---|---|---|
| 0 Audio (optional) | — | `fetch_audio.py` (yt-dlp; the user confirms the pick) | `<Artist> - <Title>.wav`, `source.json` |
| 1 Pulse + key | `pulse` | `foundation.py pulse` (madmom beats + CNN key) | `foundation.json` |
| 2 Stems | `stems`, `stems_6s` | demucs `htdemucs_ft` (+ `htdemucs_6s` for guitar/piano) `-d mps` | `stems/htdemucs_ft/<slug>/` |
| 3 Meter | `sweep`, `meter` | `detect_meter.py` → `foundation.py meter` | `meter.json`, `foundation.json` |
| 4 Bass, tonic, mode | `bass`, `mode` | `bass_notes.py` (pyin) → `mode_test.py` | `bass_per_cell.json`, `mode.json` |
| 4b Performance | `drums`, `strum` (`--performance`) | `drum_transcribe.py` (ADTOF), `strum_pattern.py` | `drum_hits.json`, `strum.json` |
| 5 Lyrics | `lyrics`, `lyrics_mix` | `whisper_gated.py` (gated by the vocal stem) | `lyrics.json`, `lyrics_mix.json` |
| 6 Sections | `align` | `align_lyrics.py` (canonical lyrics ↔ word times) | `lyrics_aligned.json`, `sections.json` |
| 7 Chords | `chords`, `chords_lv`, `tab` | `chord_proposal.py`, `lv_chords.py`, `tab_compare.py` | `chord_proposal.json`, `chords_lv.json` |
| 8 Chart | `activity`, `validate`, `chart` | `stem_activity.py`, `validate_artifacts.py`, `chart_html.py` + `chart_questions.py` | the HTML chart, the player's questions |

**References (read on demand):** `references/phases.md` (Phases 1–7: what each step
does, by-hand commands, traps) · `meter-detection.md` · `stems.md` · `chord-proposal.md`
· `chart-and-lyrics.md` (the chart, lyric placement, the data file) ·
`drum-pattern-analysis.md` · `modal-theory.md` · `lead-and-keys-extraction.md` ·
`environment-setup.md` (venvs, pins, this machine).

## Checkpoints — when to ask the user (one message each)

- **A. Intake:** the recording (Phase 0's top pick: title, channel, length, album, year —
  wait for a yes), the lyrics source, and the purpose: a chart only (`--no-6s`), or a Live
  sketch or remix too (keep the 6-stem split; `--performance` for the drummer's hits and
  the guitar's strums). Get the lyrics before the run: Phase 6 needs them.
- **B. A question from the run:** the meter (INCONCLUSIVE, a phrase-length or duple cycle,
  two accents for beat 1, eighth or quarter pulse) or a `DOWNBEAT CHECK`. Put it as printed;
  `run.py answer` with the user's words.
- **C. The player check** (Phase 8, below): up to four cells a round, by ear.
- **D. Publish and what next:** the band's folder (a yes, WiP or OK), then the Live offer.

## Inputs

1. **Audio** — the full mix. **Only a name?** Phase 0:
   `<ytdlp-venv>/bin/python scripts/fetch_audio.py --artist="<Artist>" --title="<Title>"
   --out-dir="<song folder>" [--duration=<length of the user's copy>]` searches YouTube Music
   first (the labels' uploads), rejects live/cover/karaoke/remix/sped-up uploads and prints
   the `* top pick` — nothing downloaded until the user says yes; then run the printed
   command. It writes the WAV and `source.json` (cite it in the provenance). Fetch only
   what the user has the right to study; no cookies or logins, ever.
2. **Lyrics** — canonical text from an official source; section labels (Verse, Chorus…)
   come from it. `scripts/lyrics_from_page.py <URL> --out lyrics.txt --chords-out
   analysis/tab_chords.json` moves a lyrics or chord-tab page's text into the folder. On a
   403/404 try another site (songlyrics.com, lyricsondemand.com, the band's Bandcamp, a
   chord-tab site); such text is unofficial — say so in the provenance. Whisper's text is
   the lyrics only when no page has the song.

## Phase 8 — the chart

The chart is rendered: you write the decisions as a `SONG` dict in `gen_v<N>.py` in the
song folder (a new N per revision) — sections, a chord per `(bar, cell)` (lead-sheet
symbols, or `chords_lv.json`'s labels, converted), each lyric line at its anchor cell, the
header, provenance and commentary — and `run.py` (or `python3 scripts/chart_html.py
gen_v1.py`) renders it, reading everything measured from `analysis/`. It refuses evidence
made on another grid (re-run it; `--allow-stale` renders anyway) and checks the player's
`corrections` on every render. Read `references/chart-and-lyrics.md` first. Invariants:
- Each section starts a new row; parallel sections get identical row splits. Chart bar =
  audio bar (a final chord may ring on the bar that starts at the last downbeat).
- **Every word sits where it is sung** (Rule 1, player-checked): a word held across a
  half-bar boundary, sung within a dotted eighth before it, sits after it; stop bars (the
  band out under the voice) are greyed, with no "?". `placement: 'anchor'` only if the
  band asks for it.
- **Show the evidence:** `provenance` says where meter, grouping and mode came from
  (`foundation.json` → `provenance`: `agent` = Claude's call, say so; `mode.json`); the
  renderer marks "?" where a cell's own reading names another root.
- **Where the bass drops out, agreement proves little:** both readers hear only the upper
  voices. In bass-less cells chart what the parallel section plays and ask.
- `notes`: per-section harmonic notes in scale degrees, arrangement/groove notes, and the
  open questions (every call the player hasn't confirmed).

**Player check — ask, don't wait.** Run `python3 scripts/chart_questions.py gen_v1.py`
(`run.py` does after each render) and ask the player directly, up to four cells per
round, the chart's chord first, in the order it prints (the order answers most often
change the chart): the meter and beat 1 if unconfirmed; cells that break their section's
repeating pattern even where the readers agree (on one song all four of the player's chord
fixes were such breaks); bass-less cells charted unlike their parallel section; the "?"
cells; the lines it lists as `placement check` (Whisper heard under half of them) and any
`SUNG, NOT IN THE TEXT` words. Each cell question carries its time (m:ss.s) — the player
finds it by ear. Each run scores the last round (changed, kept, fixes not on the list) into
`analysis/questions_log.jsonl`.

**While the player corrects — data only, rules after.** One correction session cost two
hours when each fix also changed the renderer, ran the tests, re-printed the shared PDF and
made a commit. Per fix: edit only the data file (a fix in `chords`, the cell in `verified`,
a word as a `'fixed'` lyric or in `stops`), add chord and word fixes to `corrections`
(`(bar, cell, 'chord' | 'word', value, 'player', date)`; stops live in `stops` only),
re-render the draft locally. No renderer edits, commits,
PDFs or shared-folder writes during the session. After it, if fixes show a rule is wrong,
change the rule once, run `chart_html.py <songs root>/*/ --check` (each song's newest data
file; every correction must hold) before committing, and `publish_chart.py --rerender <songs root>` lists the charts the
change touches. Say in `provenance` what the player checked.

**Publish — when the player says the chart is ready.**
`python3 scripts/publish_chart.py gen_v1.py [--status OK] [--prefix 3.3]` names it the
band's way (`3.3 Artist - Title - chords - <key> WiP|OK`, HTML + A4 PDF via headless
Chrome, page count reported) and prints what it would write; ask the user, then add `--yes`.
The folder: `--to`, or `publish_to` in `~/.config/music-workflow-skills/env.json`
(`{artist}` in it). WiP until the band has played it; OK replaces the WiP copy.

**What next (Live optional).** Only if the Live skills are installed and
`mcp__ableton__health_check` answers, ask once: a **sketch in Live** (the vocal on Live's
grid, the chart's chords, the bass line and a drum part, the original mix muted for A/B) or
a **remix** (keep the vocal; new drums, bass and keys in a style you pick), or stop here?
Both are `ableton-song-remix` (sketch = `--mode sketch`; Live 12 and the patched Remote
Script). Otherwise stop at the chart.

## Traps

1. **A bass walk is one chord or two; the upper voicing decides.** Bass moving inside a
   bar (`C → A♭`) is one chord over a moving bass (`Cm/A♭`) or two chords (`Cm → A♭`). A
   re-attack where the bass moves = two chords; register-pooled chroma (above ~165 Hz) that
   changes with the bass = two chords, that stays put = one.
2. **"Minor key" ≠ minor chords.** Key estimators report the melody's mode; many songs put
   major triads under a minor melody. Test each chord's third (`chord-proposal.md`); label
   modal keys as a pair (`E♭ / Cm`). The tonic is the pitch class the bass sustains longest,
   and the mode comes from `mode_test.py` (`modal-theory.md`), not the key CNN.
3. **The meter you never tested for looks like no meter at all.** An odd cycle folded onto
   the wrong period gives a flat profile, not a low one: uniform contrast means the right
   period hasn't been tested yet (`meter-detection.md`).

Automated signals are wrong ~30% of the time on modal-mixture songs: a musician who knows
the song is ground truth — plan the player check before calling the chart done.

## Lessons

1. Trust the player's ear over any analyzer — but when they say "not sure" and the bass
   and both readers agree against it, show that evidence first (a player heard A on two
   bars whose bass plays C, asked to check, and the C stood).
2. Never hand an analyzer a candidate list it can't say "none of these" to — a constrained
   `beats_per_bar` and a key-gated major bias both gave confident wrong answers.
3. Chord tools are starting points; Whisper is precise to the consonant while singers push
   into the beat — place by timing plus the push (Rule 1), scored against the player's
   corrections. A lyrics page can drop sung words (`SUNG, NOT IN THE TEXT`).
4. `basic-pitch` duplicates notes at octaves and invents low content: floor it at the
   instrument's range before anything goes to Ableton.
5. Two stem separations of one song moved its measured beat 1 by three pulses (LOW
   confidence both times): a LOW-confidence meter is a question, not a fact.
6. Mirror parallel sections visually; overlay section-boundary pickups in the same cell.

## Benchmark and local environment

`bench/run_bench.py` scores the artifacts against local ground truth (never committed;
`$MWS_BENCH_ROOT`; `--baseline` fails on a 2-point drop). Expert annotators agree on 73%
(maj/min) / 54% (full labels) of chord segments. Venvs, interpreters and cached models on
this machine: `references/environment-setup.md` → "This machine"; `run.py doctor` checks
them.
