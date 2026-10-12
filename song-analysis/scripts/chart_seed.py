#!/usr/bin/env python3
"""Draft a song's chart data file (gen_v1.py) from its analysis, as plain literal data.

Why: each chart's data file was written by hand - a hundred-odd lines of chords per cell,
sections, lyric anchors, header and provenance, much of it copied from analysis/ - before
anyone could look at a chart. The seed writes that part: the chords lv-chordia read, one per
(bar, cell), as literal labels (an analysis re-run doesn't change a chart someone checked);
the sections from lyrics.txt's labels on the bar grid, with an Intro before the first sung
line, an Interlude where four or more bars pass between sections, an Outro after the last
(a song without lyrics gets one section to split by ear); each lyric line at the cell where
it starts; the header facts (tempo and drift, meter and grouping, key or mode, length); a
provenance line saying where each came from and that no player has checked it; and the
open questions (a meter Claude chose or measured at LOW confidence, lines Whisper barely
heard or never placed, cells where the readers disagree). Claude then names and checks
the sections, writes the commentary, and the player checks the chart (chart_questions.py).

It never overwrites a data file: with a gen_v<N>.py in the folder it stops (--out writes
elsewhere). Nothing of the lyrics is printed.

Usage (python3, standard library only):
    chart_seed.py <song folder> [--out PATH] [--title T --artist A]
"""
from __future__ import annotations

import argparse, html, json, re, sys, time
from pathlib import Path
from pprint import pformat

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chart_html import Grid, compose, lead_sheet, load_song, mmss  # noqa: E402

KINDS = [('pre', 'post'), ('post', 'post'), ('chorus', 'chorus'), ('refrain', 'chorus'),
         ('hook', 'chorus'), ('bridge', 'bridge'), ('middle', 'bridge'), ('intro', 'intro'),
         ('outro', 'outro'), ('coda', 'outro'), ('ending', 'outro'), ('solo', 'inst'),
         ('instrumental', 'inst'), ('interlude', 'inst'), ('break', 'inst'), ('verse', 'verse')]
GAP = 4          # bars between sections (or after the last) that make an Interlude / Outro


def kind_of(label: str) -> str:
    low = label.lower()
    return next((k for word, k in KINDS if word in low), 'verse')


def read(a: Path, name: str):
    p = a / name
    return json.loads(p.read_text()) if p.exists() else None


def sections(F: dict, grid: Grid, secs: list, lines: list) -> list:
    """[(name, first bar, last bar, kind, '')] covering bars 1..num_bars: lyric sections from
    their first line's bar, an Intro before, an Interlude in a long gap, an Outro after."""
    nbars = len(F['downbeat_times']) - 1
    if not secs:
        return [('Song', 1, nbars, 'verse', 'no lyrics: split into sections by ear')]
    starts = [max(1, s['where'][0]) for s in secs if s.get('where')]
    labels = [s['label'] for s in secs if s.get('where')]
    seen, names = {}, []
    for lab in labels:                                   # Chorus, Chorus -> Chorus 1, 2
        seen[lab] = seen.get(lab, 0) + 1
        names.append(lab)
    count = {}
    for i, lab in enumerate(names):
        if seen[lab] > 1 and not re.search(r'\d$', lab):
            count[lab] = count.get(lab, 0) + 1
            names[i] = f'{lab} {count[lab]}'
    last_sung = {}                                       # section index -> bar its last line ends
    for ln in lines:
        if ln.get('end') is not None and ln.get('section') is not None:
            b = grid.at(ln['end'])[0]
            last_sung[ln['section']] = max(last_sung.get(ln['section'], 0), b)
    out = []
    if starts[0] > 1:
        out.append(('Intro', 1, starts[0] - 1, 'intro', ''))
    for i, (name, b0) in enumerate(zip(names, starts)):
        nxt = starts[i + 1] if i + 1 < len(starts) else nbars + 1
        end = nxt - 1
        sung = last_sung.get(i)
        if sung is not None and nxt - (sung + 1) >= GAP and sung + 1 > b0:
            end = sung                                   # the voice stops: a break follows
        out.append((name, b0, end, kind_of(name), ''))
        if end < nxt - 1:
            out.append(('Outro' if i + 1 == len(starts) else 'Interlude', end + 1, nxt - 1,
                        'outro' if i + 1 == len(starts) else 'inst', ''))
    return out


def seed(folder: Path, title: str | None, artist: str | None) -> tuple[str, dict]:
    a = folder / 'analysis'
    F = read(a, 'foundation.json')
    if not F or 'downbeat_times' not in F:
        raise ValueError('no meter in analysis/foundation.json: run the analysis first (run.py)')
    lv = read(a, 'chords_lv.json')
    if not lv:
        raise ValueError('no analysis/chords_lv.json: run Phase 7 first')
    src = read(folder, 'source.json') or {}
    title = title or src.get('song') or src.get('title') or folder.name
    artist = artist or src.get('artist') or 'Unknown'
    grouping = F['grouping']
    grid = Grid(F['downbeat_times'], grouping)
    al = read(a, 'lyrics_aligned.json') or {}
    lines = al.get('lines', [])
    secs = (read(a, 'sections.json') or {}).get('sections', [])
    S = sections(F, grid, secs, lines)
    chords = {(c['bar'], c['cell']): lead_sheet(c['chord']) for c in lv['cells']
              if 1 <= c['bar'] <= S[-1][2]}
    held = 'N.C.'
    for b in range(1, S[-1][2] + 1):                     # every cell, holds filled in
        for k in range(1, len(grouping) + 1):
            held = chords.setdefault((b, k), held)
    lyrics = {tuple(ln['where']): (ln['text'], '') for ln in lines if ln.get('where')}
    unplaced = [ln for ln in lines if not ln.get('where')]
    weak = [ln for ln in lines if ln.get('where') and (ln.get('matched') or 0) < 0.5]
    M = read(a, 'mode.json') or {}
    song = M.get('song') or {}
    if song.get('tonic') and song.get('mode') in ('major', 'minor', 'ionian', 'dorian', 'phrygian',
                                                  'lydian', 'mixolydian', 'aeolian', 'locrian'):
        key = f"{song['tonic']} {song['mode']}"
    elif song.get('tonic'):
        key = f"{song['tonic']} ({song.get('mode', 'mode undetermined')})"
    else:
        key = (F.get('key_top2') or [['', 0]])[0][0]
    prov = F.get('provenance', {})
    disagree = sum(c.get('status') == 'root-disagree' for c in lv['cells'])
    tempo = F.get('live_tempo') or F.get('pulse_bpm')
    drift = F.get('tempo_drift_pct', 0)
    esc = lambda s: html.escape(str(s), quote=False)
    who = F.get('decided_by') or {}
    facts = [('Tempo', f"{tempo} BPM" + (f' (drift {drift}%)' if drift > 3 else '')),
             ('Meter', f"{F.get('time_signature')} as {'+'.join(map(str, grouping))}"),
             ('Key', esc(key)), ('Length', mmss(F['downbeat_times'][-1]))]
    parts = ['<b>Seeded</b> by chart_seed.py from the analysis — <b>not yet checked by a '
             'player</b>.']
    if src.get('url'):
        parts.append(f"<b>Audio</b>: {esc(src.get('channel') or '')} "
                     f"({esc(src['url'])}){', ' + esc(src['album']) if src.get('album') else ''}.")
    parts.append(f"<b>Meter</b>: {esc(prov.get('cycle', '?'))}; beat 1 {esc(prov.get('downbeat', '?'))}"
                 + (f" — {', '.join(who.get('what', []))} Claude's call" if who.get('who') == 'agent'
                    else '') + (' — LOW confidence: confirm by ear' if F.get('to_confirm') else '')
                 + '.')
    parts.append(f"<b>Key</b>: {esc(key)} (tonic from the bass, mode from mode_test); the key "
                 f"CNN said {esc((F.get('key_top2') or [['?']])[0][0])}.")
    parts.append(f"<b>Chords</b>: lv-chordia, cross-checked by the triad reader ({disagree} cells "
                 'name another root).')
    if lines:
        parts.append(f"<b>Lyrics</b>: lyrics.txt (say whether it is official), placed on "
                     f"Whisper's word times ({al.get('words_matched', '?')} words matched).")
    qs = []
    if who.get('who') == 'agent' or F.get('to_confirm'):
        qs.append('<li><b>Meter and beat 1</b>: count along from bar 1 — '
                  f"{esc(F.get('time_signature'))} as {'+'.join(map(str, grouping))}?</li>")
    if unplaced:
        qs.append(f'<li><b>{len(unplaced)} lyric line(s) not placed</b> (Whisper heard none of '
                  'their words): where are they sung?</li>')
    if weak:
        qs.append(f'<li><b>{len(weak)} line(s) Whisper barely heard</b>: check where their words '
                  'fall (chart_questions.py lists them).</li>')
    if disagree:
        qs.append(f'<li><b>{disagree} cells</b> where the two chord readers disagree: the "?" '
                  'cells and chart_questions.py.</li>')
    qs.append('<li><b>The form</b>: sections are named from lyrics.txt — check the boundaries, '
              'name the instrumental parts.</li>')
    D = dict(title=title, artist=artist, key_short=key,
             words=(al.get('source') or '').replace('analysis/', '') or None,
             sections=S, chords=dict(sorted(chords.items())), lyrics=dict(sorted(lyrics.items())) or None,
             verified=[], corrections=[], facts=facts, provenance=' '.join(parts),
             notes=[('Open questions for a player', f"<ol>{''.join(qs)}</ol>", 'open')])
    D = {k: v for k, v in D.items() if v is not None}
    return render_file(D), dict(sections=len(S), chords=len(chords), lyrics=len(lyrics),
                                unplaced=len(unplaced), questions=len(qs))


def render_file(D: dict) -> str:
    """The data file: SONG = dict(...) with one key per line, chords one bar per line."""
    out = [f'# Seeded by chart_seed.py on {time.strftime("%Y-%m-%d")} from analysis/ - a draft:',
           '# check the sections, write the notes, then the player check (chart_questions.py).',
           "# Chords are literal labels: an analysis re-run doesn't change them.", 'SONG = dict(']
    for k, v in D.items():
        if k == 'chords':
            out.append('    chords={')
            bars = {}
            for (b, c), lab in v.items():
                bars.setdefault(b, []).append(f'({b}, {c}): {lab!r}')
            out += [f"        {', '.join(cells)}," for _, cells in sorted(bars.items())]
            out.append('    },')
        elif k in ('lyrics', 'sections', 'facts', 'notes') and v:
            open_, close = ('{', '}') if isinstance(v, dict) else ('[', ']')
            out.append(f'    {k}={open_}')
            items = v.items() if isinstance(v, dict) else enumerate(v)
            for kk, vv in items:
                out.append(f'        {kk!r}: {vv!r},' if isinstance(v, dict) else f'        {vv!r},')
            out.append(f'    {close},')
        else:
            out.append(f'    {k}={pformat(v, width=200)},')
    out.append(')')
    return '\n'.join(out) + '\n'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('folder', help='the song folder (holding analysis/)')
    ap.add_argument('--out', help='write here instead of <folder>/gen_v1.py')
    ap.add_argument('--title')
    ap.add_argument('--artist')
    a = ap.parse_args()
    sys.dont_write_bytecode = True
    folder = Path(a.folder).expanduser().resolve()
    have = sorted(folder.glob('gen_v*.py'))
    if have and not a.out:
        sys.exit(f'chart_seed: {have[-1].name} exists - a chart data file is never overwritten '
                 '(--out writes the draft elsewhere)')
    try:
        text, info = seed(folder, a.title, a.artist)
        out = Path(a.out) if a.out else folder / 'gen_v1.py'
        out.write_text(text, encoding='utf-8')
        S = load_song(out)
        if a.out:                                        # render against the song's analysis
            S['folder'] = str(folder)
        _, r = compose(S)
    except (OSError, ValueError) as e:
        sys.exit(f'chart_seed: {e}')
    print(f"wrote {out.name}: {info['sections']} sections, {info['chords']} chord cells, "
          f"{info['lyrics']} lyric lines placed ({info['unplaced']} not), {info['questions']} open "
          f"questions; renders: {r['n_q']} cells marked '?'")


if __name__ == '__main__':
    main()
