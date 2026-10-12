#!/usr/bin/env python3
"""The chart for the band's apps and the stage: ChordPro, an iReal Pro import, a gig sheet.

Why: the band charts in iReal Pro and on one- to three-page chord sheets, and plays in other
keys; the rendered chart (one cell per half-bar, the song bar by bar) is the listening and
checking view, 4-6 pages long. All three come from the same chart data file, so the
player's fixes carry over (a bass note printed under a chord becomes its slash bass):
  .cho         ChordPro (OnSong, SongbookPro, ChordPro apps): sections as environments,
               each sung line (as lyrics.txt has it) with its chords inline where they are
               sung, pickups at the start of the line they lead into, ad-libs in brackets,
               instrumental stretches as chord lines folded into repeats; {key} is the key
               the chords are written in, with {capo} when they are capo shapes.
  - iReal.html a page with a tap-to-import irealbook:// link (chords and form only, no
               lyrics): sections as iReal rehearsal marks, exact repeats as { } with a
               count, the key from iReal's own list. Concert pitch: a capo is left out (the
               backing plays the sounding key). A meter iReal Pro has no symbol for (11/8,
               13/8) is refused, never approximated; iReal shows at most 12 lines of 16
               cells - a longer form is written and warned about.
  - Gig.html   one or two printed pages: each section's pattern once with x N, the bars
               that differ by number, a section that repeats an earlier one as "= Verse 1",
               the first words as a cue.
Transposition: --transpose N semitones (the band's key) and/or --capo N (chord shapes for
a capo at fret N), from the command line or the data file's 'transpose' / 'capo' keys,
spelt by letter from the new key (the raised 7th stays raised); the files say which key.

Usage (python3, standard library only; nothing is printed of the lyrics):
    chart_export.py <song>/gen_v1.py [--chordpro] [--ireal] [--gig] [--out-dir DIR]
        [--transpose -2] [--capo 3] [--style "Medium Rock"]     # default: all three
"""
from __future__ import annotations

import argparse, html, re, sys, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chart_html import (Grid, distribute, key_of, key_suffix, lead_sheet, load_json,  # noqa: E402
                        load_song, mmss, note_name, pretty, split_slash, transposed)
from chart_form import bar_chords, fold, fold_bars  # noqa: E402

TS = {(2, 4): 'T24', (3, 4): 'T34', (4, 4): 'T44', (5, 4): 'T54', (6, 4): 'T64', (7, 4): 'T74',
      (2, 2): 'T22', (3, 2): 'T32', (5, 8): 'T58', (6, 8): 'T68', (7, 8): 'T78', (9, 8): 'T98',
      (12, 8): 'T12'}
MARK = {'intro': 'i', 'verse': 'V', 'chorus': 'A', 'bridge': 'B', 'post': 'C', 'inst': 'D',
        'outro': 'D'}
CHORDPRO_ENV = {'verse': 'verse', 'chorus': 'chorus', 'bridge': 'bridge'}
IREAL_MAJOR = ('C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B')
IREAL_MINOR = ('C-', 'C#-', 'D-', 'Eb-', 'E-', 'F-', 'F#-', 'G-', 'G#-', 'A-', 'Bb-', 'B-')
QUALITY = [  # lead-sheet quality -> iReal Pro, longest first
    ('m(maj7)', '-^7'), ('maj13', '^13'), ('maj9', '^9'), ('maj7', '^7'), ('m7b5', 'h7'),
    ('dim7', 'o7'), ('dim', 'o'), ('aug', '+'), ('m6/9', '-69'), ('6/9', '69'), ('m13', '-11'),
    ('m11', '-11'), ('m9', '-9'), ('m7', '-7'), ('m6', '-6'), ('7sus4', '7sus'), ('sus4', 'sus'),
    ('sus2', '2'), ('add9', 'add9'), ('m', '-'), ('', '')]


def runs(bar: tuple) -> list:
    """A bar's chords in order, a chord held over cells written once (Am G Am stays three)."""
    return [c for i, c in enumerate(bar) if i == 0 or c != bar[i - 1]]


def with_bass(S: dict) -> dict:
    """The printed bass notes as slash basses ('Bb' with bass A -> 'Bb/A')."""
    bn = S.get('bass_notes', {})
    return dict(S, chords={k: (f'{v}/{bn[k]}' if k in bn and '/' not in v and not v.startswith('N')
                               else v) for k, v in S['chords'].items()})


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
    owners = {}
    lyr, over = distribute(S, grid, words, owners)
    return dict(F=F, grouping=grouping, n=len(grouping), grid=grid, db=db, lyr=lyr, over=over,
                owners=owners, beats=sum(grouping), unit=F.get('pulse_unit', 4))


def base(S: dict, keys: dict) -> str:
    moved = key_suffix(keys)
    key = f" - {S['key_short']}" if S.get('key_short') and not moved else ''
    return re.sub(r'[\\/:]', '-', f"{S['artist']} - {S['title']}{key}" + (f' ({moved})' if moved else ''))


def short_key(k) -> str:
    """'Em', 'Bb', 'F#m' for ChordPro's {key} (the mode's third decides the m)."""
    return note_name(k.letter, k.pc) + ('m' if k.minor else '')


# ------------------------------------------------------------------ ChordPro

def starts_line(S: dict, owner: tuple) -> bool:
    """A sung line starts a ChordPro line; a player's 'fixed' fragment does when it starts
    with a capital (the line's first word), else it continues the line before."""
    text, kind = S['lyrics'][owner]
    return kind == '' or (kind == 'fixed' and text[:1].isupper())


def chordpro(S: dict, X: dict, note: str, keys: dict) -> str:
    out = [f"{{title: {S['title']}}}", f"{{artist: {S['artist']}}}"]
    shape = key_of(keys['shape']) if keys.get('capo') and keys.get('shape') else None
    k = shape or keys.get('key') or key_of(S.get('key_short'))
    if k:
        out.append(f'{{key: {short_key(k)}}}')
    if keys.get('capo'):
        out.append(f"{{capo: {keys['capo']}}}")
    if X['F'].get('live_tempo'):
        out.append(f"{{tempo: {round(X['F']['live_tempo'])}}}")
    out.append(f"{{time: {X['beats']}/{X['unit']}}}")
    if note:
        out.append(f'{{comment: {note}}}')
    n, own, over = X['n'], X['owners'], X['over']
    cb = bar_chords(S, n)                                # every cell's sounding chord
    chord_line = lambda bars: ' | '.join(' '.join(f'[{c}]' for c in runs(b)) for b in bars)

    def folded(cells):
        """Chord-only cells as one or two lines, the bars folded into repeats."""
        bars = sorted({b for b, _ in cells})
        head, pattern, times, tail, _ = fold_bars([cb[b] for b in bars])
        lines = [chord_line(head)] if head else []
        lines.append(chord_line(pattern) + (f'   (x{times})' if times > 1 else ''))
        return lines + ([chord_line(tail)] if tail else [])

    carry = ''                                           # a pickup into the next section
    for name, b0, b1, kind, *_ in S['sections']:
        env = CHORDPRO_ENV.get(kind)
        out += ['', f'{{start_of_{env}: {name}}}' if env else f'{{comment: {name}}}']
        cells = [(b, c) for b in range(b0, b1 + 1) for c in range(1, n + 1)]
        sung = [i for i, x in enumerate(cells) if own.get(x) or over.get(x, ('', ''))[1] == 'adlib']
        pk = [x for x in cells if over.get(x, ('', ''))[1].startswith('pk')]
        if not sung:
            out += folded(cells)
        else:
            first = sung[0]
            last = max(i for i, x in enumerate(cells) if x[0] == cells[sung[-1]][0])  # bar's end
            if first >= 2 * n:                           # two bars or more before the voice
                out += folded(cells[:first])
                cells_used = cells[first:last + 1]
            else:
                cells_used = cells[:last + 1]
            lines, cur, owner, prev = [], [], None, None
            for x in cells_used:
                ch = cb[x[0]][x[1] - 1]
                words = own.get(x, [])
                at_chord = ch != prev
                if not cur and not words and not at_chord and x[1] != 1:
                    continue
                groups = []
                for o, w in words:                       # consecutive words of one line
                    if groups and groups[-1][0] == o:
                        groups[-1][1].append(w)
                    else:
                        groups.append((o, [w]))
                chord_tag = f'[{ch}]' if ch and (at_chord or not cur) else ''
                if not groups:
                    if chord_tag:
                        cur.append(chord_tag)
                else:
                    for gi, (o, ws) in enumerate(groups):
                        new = owner is not None and o != owner and starts_line(S, o)
                        if new:
                            lines.append(cur)
                            cur = []
                        if not cur and carry:
                            cur.append(carry + ' ')
                            carry = ''
                        tag = chord_tag if gi == 0 else ''
                        if new and not tag and ch:
                            tag = f'[{ch}]'          # a new line restates its chord
                        cur.append(tag + ' '.join(ws) + ' ')
                        owner = o
                ad = over.get(x)
                if ad and ad[1] == 'adlib':
                    cur.append(f'({ad[0]}) ')
                prev = ch
            if cur:
                lines.append(cur)
            out += [''.join(seg).strip() for seg in lines if ''.join(seg).strip()]
            rest = cells[last + 1:]
            if len({b for b, _ in rest}) >= 2:           # the band carries on after the voice
                out += folded(rest)
            elif rest and out[-1] and not out[-1].startswith('{'):
                out[-1] += ' | ' + ' '.join(f'[{c}]' for c in runs(cb[rest[0][0]]))
        for x in pk:
            carry = over[x][0]
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


def bar_cells(n: int) -> int:
    """Cells ireal_bar writes for a bar of n chart cells."""
    return 4 if n <= 2 else 2 * n


def ireal_bar(bar: tuple) -> str:
    """Four cells for one or two chords (a chord, a space each); more cells, two per chord."""
    toks = [ireal_chord(c) if i == 0 or c != bar[i - 1] else '' for i, c in enumerate(bar)]
    if len(bar) == 1:
        return f'{toks[0]}   '
    if len(bar) == 2:
        return f"{toks[0]} {toks[1] or ' '} "
    return ''.join(f'{t or " "} ' for t in toks)


def ireal_key(k) -> str:
    return (IREAL_MINOR if k.minor else IREAL_MAJOR)[k.pc]


def ireal(S: dict, X: dict, style: str, note: str, keys: dict) -> tuple[str, int]:
    """The irealbook:// URL (concert pitch) and the number of 16-cell lines it fills."""
    ts = TS.get((X['beats'], X['unit']))
    if ts is None:
        raise ValueError(f"iReal Pro has no {X['beats']}/{X['unit']} time signature: no iReal "
                         'export (the chart keeps the meter)')
    k = keys.get('key') or key_of(S.get('key_short'))
    key = ireal_key(k) if k else 'C'
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
    fields = [clean(title + (f' ({note})' if note else '')), clean(S['artist']), clean(style),
              key, 'n', ts + ''.join(parts)]
    lines = -(-bars * bar_cells(X['n']) // 16)
    return 'irealbook://' + urllib.parse.quote('='.join(fields), safe="/*()-_.!~'"), lines


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
    bar = lambda b: '<span class="bar">' + ' '.join(acc(c) for c in runs(b)) + '</span>'
    lyr = X['lyr']
    rows = []
    for s in form:
        head = f'<div class="name">{esc(s.name)}</div>'
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
                f'bar {n}: {esc(" ".join(pretty(c) for c in runs(b)))}'
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
    warn = (f'<p>Note: {lines} lines of 16 cells; iReal Pro shows 12 — trim the form in the '
            'app.</p>' if lines > 12 else '')
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
        S0 = load_song(a.data)
        S0['chords'] = {k: lead_sheet(v) for k, v in S0['chords'].items()}
        tr = a.transpose if a.transpose is not None else S0.get('transpose') or 0
        capo = a.capo if a.capo is not None else S0.get('capo') or 0
        S, note, keys = transposed(S0, tr, capo)
        S = with_bass(S)
        X = context(S)
        out = Path(a.out_dir) if a.out_dir else Path(S['folder'])
        out.mkdir(parents=True, exist_ok=True)
        name = base(S, keys)
        if 'chordpro' in which:
            p = out / f'{name}.cho'
            text = chordpro(S, X, note, keys)
            p.write_text(text, encoding='utf-8')
            print(f'wrote {p.name}: {text.count("{start_of_") + text.count("{comment:")} sections')
        if 'ireal' in which:
            try:                                         # concert pitch: no capo shapes
                C, cnote, ckeys = transposed(S0, tr, 0)
                C = with_bass(C)
                url, lines = ireal(C, X, a.style, cnote + (' (concert pitch, no capo)'
                                                           if capo else ''), ckeys)
                p = out / f'{name} - iReal.html'
                p.write_text(ireal_page(C, url, lines, cnote), encoding='utf-8')
                print(f'wrote {p.name}: {lines} lines of 16 cells'
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
