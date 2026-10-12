#!/usr/bin/env python3
"""The chart for the band's apps and the stage: ChordPro, an iReal Pro import, a gig sheet.

Why: the band charts in iReal Pro and on one- to three-page chord sheets, and plays in other
keys; the rendered chart (one cell per half-bar, the song bar by bar) is the listening and
checking view, 4-6 pages long. All three come from the same chart data file, so the
player's fixes carry over:
  .cho        ChordPro (OnSong, SongbookPro, ChordPro apps): sections as environments,
              each lyric line with its chords inline where they are sung, instrumental
              sections as chord lines folded into repeats.
  - iReal.html a page with a tap-to-import irealbook:// link (chords and form only, no
              lyrics): sections as iReal rehearsal marks, exact repeats as { } with a
              count. A meter iReal Pro has no symbol for (11/8, 7/4 as 2+2+3 is fine, 13/8
              is not) is refused, never approximated; iReal shows at most 12 lines of four
              bars - a longer form is written and warned about.
  - Gig.html   one or two printed pages: each section's pattern once with x N, the bars
              that differ by number, a section that repeats an earlier one as "= Verse 1",
              the first words as a cue.
Transposition: --transpose N semitones (the band's key) and/or --capo N (chord shapes for
a capo at fret N), from the command line or the data file's 'transpose' / 'capo' keys;
the files then say which key they are in.

Usage (python3, standard library only; nothing is printed of the lyrics):
    chart_export.py <song>/gen_v1.py [--chordpro] [--ireal] [--gig] [--out-dir DIR]
        [--transpose -2] [--capo 3] [--style "Medium Rock"]     # default: all three
"""
from __future__ import annotations

import argparse, html, json, re, sys, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chart_html import (PC, Grid, distribute, key_of, lead_sheet, load_json,  # noqa: E402
                        load_song, mmss, pretty, spelling, split_slash, transposed)
from chart_form import fold  # noqa: E402

TS = {(2, 4): 'T24', (3, 4): 'T34', (4, 4): 'T44', (5, 4): 'T54', (6, 4): 'T64', (7, 4): 'T74',
      (2, 2): 'T22', (3, 2): 'T32', (5, 8): 'T58', (6, 8): 'T68', (7, 8): 'T78', (9, 8): 'T98',
      (12, 8): 'T12'}
MARK = {'intro': 'i', 'verse': 'V', 'chorus': 'A', 'bridge': 'B', 'post': 'C', 'inst': 'D',
        'outro': 'D'}
CHORDPRO_ENV = {'verse': 'verse', 'chorus': 'chorus', 'bridge': 'bridge'}
QUALITY = [  # lead-sheet quality -> iReal Pro, longest first
    ('m(maj7)', '-^7'), ('maj13', '^13'), ('maj9', '^9'), ('maj7', '^7'), ('m7b5', 'h7'),
    ('dim7', 'o7'), ('dim', 'o'), ('aug', '+'), ('m6/9', '-69'), ('6/9', '69'), ('m13', '-11'),
    ('m11', '-11'), ('m9', '-9'), ('m7', '-7'), ('m6', '-6'), ('7sus4', '7sus'), ('sus4', 'sus'),
    ('sus2', '2'), ('add9', 'add9'), ('m', '-'), ('', '')]


# ------------------------------------------------------------------ the song's grid

def context(S: dict) -> dict:
    folder = Path(S.get('folder', '.'))
    F = load_json(folder / 'analysis' / 'foundation.json')
    grouping = list(S.get('grouping') or F.get('grouping') or [])
    if not grouping:
        raise ValueError('no grouping in foundation.json: run foundation.py meter first')
    db = list(F['downbeat_times'])
    last_bar = max(sec[2] for sec in S['sections'])
    if last_bar == len(db):
        end = S.get('duration_s') or 0
        db.append(end if end > db[-1] else 2 * db[-1] - db[-2])
    words = None
    if S.get('words'):
        W = load_json(folder / 'analysis' / S['words'])
        words = W.get('words') or None
    grid = Grid(db, grouping)
    lyr, over = distribute(S, grid, words)
    return dict(F=F, grouping=grouping, n=len(grouping), grid=grid, db=db, lyr=lyr, over=over,
                beats=sum(grouping), unit=F.get('pulse_unit', 4))


def base(S: dict, note: str) -> str:
    key = f" - {S['key_short']}" if S.get('key_short') and not note else ''
    t = re.sub(r'[\\/:]', '-', f"{S['artist']} - {S['title']}{key}")
    return t + (f" ({re.sub(r'[^\w +#-]', '', note.split(' (')[0])})" if note else '')


# ------------------------------------------------------------------ ChordPro

def chordpro(S: dict, X: dict, note: str) -> str:
    out = [f"{{title: {S['title']}}}", f"{{artist: {S['artist']}}}"]
    k = key_of(S.get('key_short'))
    if k:
        out.append(f"{{key: {spelling(k)[k[0]]}{'m' if k[1] else ''}}}")
    if X['F'].get('live_tempo'):
        out.append(f"{{tempo: {round(X['F']['live_tempo'])}}}")
    out.append(f"{{time: {X['beats']}/{X['unit']}}}")
    if note:
        out.append(f'{{comment: {note}}}')
    anchors = sorted(k for k, (_, kind) in S.get('lyrics', {}).items()
                     if kind in ('', 'fixed'))
    form = {s.name: s for s in fold(S, X['n'])}
    for name, b0, b1, kind, *_ in S['sections']:
        env = CHORDPRO_ENV.get(kind)
        out.append('')
        out.append(f'{{start_of_{env}: {name}}}' if env else f'{{comment: {name}}}')
        cells = [(b, c) for b in range(b0, b1 + 1) for c in range(1, X['n'] + 1)]
        if not any(X['lyr'].get(x) for x in cells):            # instrumental: folded chords
            s = form[name]
            line = lambda bars: ' | '.join(' '.join(f'[{c}]' for c in dict.fromkeys(b)) for b in bars)
            if s.head:
                out.append(line(s.head))
            out.append(line(s.pattern) + (f'   (x{s.times})' if s.times > 1 else ''))
            if s.tail:
                out.append(line(s.tail))
        else:
            starts = [x for x in cells if x in anchors] or [cells[0]]
            if starts[0] != cells[0]:
                starts.insert(0, cells[0])
            held = None
            for i, st in enumerate(starts):
                end = starts[i + 1] if i + 1 < len(starts) else None
                seg, held_line = [], None
                for x in cells[cells.index(st):cells.index(end) if end else None]:
                    ch = S['chords'].get(x) or held
                    text = X['lyr'].get(x, '')
                    if ch and (ch != held_line or x[1] == 1 and not text):
                        seg.append(f'[{ch}]')
                        held_line = ch
                    held = ch
                    if text:
                        seg.append(text + ' ')
                line = ''.join(seg).strip()
                if line:
                    out.append(line)
        if env:
            out.append(f'{{end_of_{env}}}')
    return '\n'.join(out) + '\n'


# ------------------------------------------------------------------ iReal Pro

def ireal_chord(label: str) -> str:
    if not label or label.startswith('N'):
        return 'n'
    chord, bass = split_slash(label)
    m = re.match(r'([A-G][#b]?)(.*)', chord)
    if not m:
        return label
    q = m.group(2)
    rest = next((v + q[len(k):] for k, v in QUALITY if q.startswith(k)), q)
    return m.group(1) + rest + (f'/{bass}' if bass else '')


def ireal_bar(bar: tuple) -> str:
    """Four cells for one or two chords (a chord, a space each); more cells, two per chord."""
    toks = [ireal_chord(c) if i == 0 or c != bar[i - 1] else '' for i, c in enumerate(bar)]
    if len(bar) == 1:
        return f'{toks[0]}   '
    if len(bar) == 2:
        return f"{toks[0]} {toks[1] or ' '} "
    return ''.join(f'{t or " "} ' for t in toks)


def ireal(S: dict, X: dict, style: str, note: str) -> tuple[str, int]:
    """The irealbook:// URL and the number of 4-bar lines it fills."""
    ts = TS.get((X['beats'], X['unit']))
    if ts is None:
        raise ValueError(f"iReal Pro has no {X['beats']}/{X['unit']} time signature: no iReal "
                         'export (the chart keeps the meter)')
    k = key_of(S.get('key_short'))
    key = (spelling(k)[k[0]] + ('-' if k[1] else '')) if k else 'C'
    parts, bars = [], 0
    form = fold(S, X['n'])
    for i, s in enumerate(form):
        mark = f"*{MARK.get(s.kind, 'A')}"
        body = '|'.join(ireal_bar(b) for b in s.pattern)
        lead = '[' + mark + '|'.join(ireal_bar(b) for b in s.head) + ']' if s.head else ''
        if s.times > 1:
            txt = f'<{s.times}x>' if s.times != 2 else ''
            part = lead + '{' + ('' if lead else mark) + txt + body + '}'
            if s.tail:
                part += '|' + '|'.join(ireal_bar(b) for b in s.tail)
        else:
            part = '[' + mark + '|'.join(ireal_bar(b) for b in s.head + s.pattern)
        bars += len(s.head) + len(s.pattern) + len(s.tail)
        last = i == len(form) - 1
        if not part.endswith('}'):
            part += 'Z' if last else ']'
        elif last:
            part += ' Z'
        parts.append(part)
    title = S['title']
    if title.lower().startswith('the '):
        title = f'{title[4:]}, The'
    clean = lambda x: x.replace('=', '-')
    prog = ts + ''.join(parts)
    fields = [clean(title + (f' ({note})' if note else '')), clean(S['artist']), clean(style),
              key, 'n', prog]
    return 'irealbook://' + urllib.parse.quote('='.join(fields), safe="/*()-_.!~'"), -(-bars // 4)


# ------------------------------------------------------------------ gig sheet

GIG_CSS = """body{font-family:-apple-system,"Helvetica Neue",Arial,sans-serif;max-width:1000px;margin:.8em auto;padding:0 .8em;color:#1a1a1a;background:#fff}
h1{font-size:1.15em;margin:0}.sub{color:#555;font-size:.8em;margin:.1em 0 .8em}
.sec{display:grid;grid-template-columns:9.5em 1fr;gap:.2em .8em;padding:.45em 0;border-top:1px solid #e0e0dc;page-break-inside:avoid}
.name{font-weight:700;text-transform:uppercase;letter-spacing:.04em;font-size:.82em}.meta{font:.7em Menlo,monospace;color:#888}
.verse .name{color:#4a6f96}.chorus .name{color:#b03030}.bridge .name{color:#5b9a52}.post .name{color:#b58632}.inst .name,.intro .name,.outro .name{color:#777}
.bars{display:flex;flex-wrap:wrap;align-items:center;gap:0}.bar{min-width:4.2em;padding:.15em .5em;border-left:2px solid #b8b8b0;font:700 1.15em Georgia,serif;white-space:nowrap}
.bar:last-of-type{border-right:2px solid #b8b8b0}.x{font:700 .9em -apple-system,Arial,sans-serif;color:#b03030;margin-left:.5em}
.acc{font-family:STIXGeneral,"Apple Symbols","Segoe UI Symbol","Noto Music",serif;font-weight:400}.same{font-style:italic;color:#555}.cue{font-size:.72em;color:#777;font-style:italic;grid-column:2}.diff{font-size:.72em;color:#8f6420;grid-column:2}
.rep{display:flex;align-items:center}.rep::before{content:"𝄆";font-size:1.4em;color:#888;margin-right:.1em}.rep .x::before{content:"𝄇 ";color:#888}
@media print{body{margin:0;max-width:100%}@page{size:A4 portrait;margin:.4in}}"""


def gig(S: dict, X: dict, note: str) -> str:
    form = fold(S, X['n'], tolerance=1)
    esc = lambda s: html.escape(s, quote=True)
    acc = lambda c: re.sub('([♯♭])', r'<span class="acc">\1</span>', esc(pretty(c)))  # Georgia has no ♭
    bar = lambda b: '<span class="bar">' + ' '.join(acc(c) for c in dict.fromkeys(b)) + '</span>'
    lyr = X['lyr']
    rows = []
    for s in form:
        head = (f'<div class="name">{esc(s.name)}</div>')
        meta = f'{s.b1 - s.b0 + 1} bars · {mmss(X["db"][s.b0 - 1])}'
        if s.same_as:
            body = f'<div class="bars same">= {esc(s.same_as)}</div>'
        elif s.times > 1:
            body = (f'<div class="bars">{"".join(bar(b) for b in s.head)}<span class="rep">'
                    f'{"".join(bar(b) for b in s.pattern)}<span class="x">×{s.times}</span>'
                    f'</span>{"".join(bar(b) for b in s.tail)}</div>')
        else:
            body = f'<div class="bars">{"".join(bar(b) for b in s.head + s.pattern)}</div>'
        extra = ''
        if s.differs and not s.same_as:
            extra += ('<div class="diff">but ' + ', '.join(
                f'bar {n}: {esc(" ".join(pretty(c) for c in dict.fromkeys(b)))}'
                for n, b in s.differs) + '</div>')
        cue = next((lyr[(b, c)] for b in range(s.b0, s.b1 + 1) for c in range(1, X['n'] + 1)
                    if lyr.get((b, c))), '')
        if cue:
            extra += f'<div class="cue">“{esc(" ".join(cue.split()[:6]))}…”</div>'
        rows.append(f'<div class="sec {s.kind}"><div>{head}<div class="meta">{meta}</div></div>'
                    f'{body}{extra}</div>')
    k = f" · {esc(S['key_short'])}" if S.get('key_short') and not note else ''
    tempo = X['F'].get('live_tempo')
    sub = ' · '.join(x for x in (f"{X['beats']}/{X['unit']}", tempo and f'♩ = {round(tempo)}',
                                 note and esc(note)) if x)
    name = f"{esc(S['artist'])} — {esc(S['title'])}"
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{name} · Gig{k}</title>'
            f'<style>{GIG_CSS}</style></head><body><h1>{name}{k}</h1><div class="sub">{sub}</div>'
            + '\n'.join(rows) + '</body></html>\n')


def ireal_page(S: dict, url: str, lines: int, note: str) -> str:
    esc = lambda s: html.escape(s, quote=True)
    warn = (f'<p>Note: {lines} lines of four bars; iReal Pro shows 12 — trim the form in '
            'the app.</p>' if lines > 12 else '')
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{esc(S["title"])} · iReal Pro'
            f'</title><style>body{{font-family:-apple-system,Arial,sans-serif;max-width:40em;'
            f'margin:2em auto;padding:0 1em}}a{{font-size:1.2em}}</style></head><body>'
            f'<h1>{esc(S["artist"])} — {esc(S["title"])}</h1><p>{esc(note)}</p>'
            f'<p><a href="{esc(url)}">Open in iReal Pro</a> (tap on the phone or tablet with '
            f'iReal Pro installed)</p>{warn}</body></html>\n')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('data', help='the chart data file, e.g. gen_v1.py')
    ap.add_argument('--chordpro', action='store_true')
    ap.add_argument('--ireal', action='store_true')
    ap.add_argument('--gig', action='store_true')
    ap.add_argument('--out-dir', help='default: the song folder')
    ap.add_argument('--transpose', type=int, help='semitones (default: the data file\'s)')
    ap.add_argument('--capo', type=int, help='fret (default: the data file\'s)')
    ap.add_argument('--style', default='Pop', help='iReal Pro style, e.g. "Medium Rock"')
    a = ap.parse_args()
    sys.dont_write_bytecode = True
    which = [w for w in ('chordpro', 'ireal', 'gig') if getattr(a, w)] or ['chordpro', 'ireal', 'gig']
    try:
        S = load_song(a.data)
        S['chords'] = {k: lead_sheet(v) for k, v in S['chords'].items()}
        tr = a.transpose if a.transpose is not None else S.get('transpose') or 0
        capo = a.capo if a.capo is not None else S.get('capo') or 0
        S, note = transposed(S, tr, capo)
        X = context(S)
        out = Path(a.out_dir) if a.out_dir else Path(S['folder'])
        out.mkdir(parents=True, exist_ok=True)
        name = base(S, note)
        if 'chordpro' in which:
            p = out / f'{name}.cho'
            text = chordpro(S, X, note)
            p.write_text(text, encoding='utf-8')
            print(f'wrote {p.name}: {text.count("{start_of_") + text.count("{comment:")} sections')
        if 'ireal' in which:
            try:
                url, lines = ireal(S, X, a.style, note)
                p = out / f'{name} - iReal.html'
                p.write_text(ireal_page(S, url, lines, note), encoding='utf-8')
                print(f'wrote {p.name}: {lines} lines of four bars'
                      + (' - iReal Pro shows 12: trim it in the app' if lines > 12 else ''))
            except ValueError as e:
                print(f'iReal Pro: {e}')
        if 'gig' in which:
            p = out / f'{name} - Gig.html'
            p.write_text(gig(S, X, note), encoding='utf-8')
            print(f'wrote {p.name}')
    except (OSError, ValueError) as e:
        sys.exit(f'chart_export: {e}')


if __name__ == '__main__':
    main()
