#!/usr/bin/env python3
"""The chart's open calls as questions for the player, each with its evidence and options.

Why: a "?" in a printed chart waits for someone to notice it; a player checking on their
instrument answers in seconds when asked directly. After chart_html.py, this lists what
the chart is unsure of - cells marked "?" (the readers name another root), skipping
verified cells and stop bars - with the chart's chord, what lv-chordia, the triad reader
and the bass heard, and the parallel section's chord when the section repeats (counted
from the start, or from the end when the two differ in length - turnarounds close them). Ask them
a few at a time - and cells that break their section's repeating pattern even where the
readers agree (pattern_breaks); each answer goes back into the data file (a fix in `chords`, the cell
in `verified`), then re-render.

Printed in the order the answers most often change the chart: the meter and beat 1 when
they were Claude's call (foundation.json decided_by), pattern breaks, bass-less cells that
differ from their parallel section (readers agreeing there prove little: with no bass
they read the same guitar), then the "?" cells, then lines Whisper barely heard. Each
cell question gives its time in the recording (m:ss-m:ss), so the player finds it by ear.

Each run keeps the list it printed (analysis/questions_round.json); the next run, once
the chart has changed, scores it against the chart - which listed cells the player
changed, which they kept, and the fixes that were not on the list - into
analysis/questions_log.jsonl: how well the questions find what the player fixes.

Usage (python3, standard library only; from the song folder):
    chart_questions.py gen_v1.py [--json analysis/questions.json] [--max 12] [--no-log]
"""
from __future__ import annotations

import argparse, json, runpy, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chart_html import STOP, Grid, flags, lead_sheet, mmss  # noqa: E402


def load(a: Path, name: str, key: str = 'cells') -> list:
    p = a / name
    return json.loads(p.read_text()).get(key, []) if p.exists() else []


def parallel_chords(S: dict, key: tuple) -> list:
    """The chords the same position holds in the parallel sections (same kind): counted from
    the start when the two are as long, else from the end (turnarounds close a section)."""
    sec = next((s for s in S['sections'] if s[1] <= key[0] <= s[2]), None)
    if sec is None:
        return []
    _, b0, b1, kind, *_ = sec
    out = []
    for n, p0, p1, k, *_ in S['sections']:
        if k != kind or p0 == b0:
            continue
        pb = p0 + key[0] - b0 if p1 - p0 == b1 - b0 else p1 - (b1 - key[0])
        if p0 <= pb <= p1:
            out.append(S['chords'].get((pb, key[1])))
    return out


def questions(S: dict, a: Path) -> list[dict]:
    """One dict per open cell: bar, cell, section, chart, lv, triads, bass, parallel, options."""
    lv = {(c['bar'], c['cell']): c for c in load(a, 'chords_lv.json')}
    tri = {(c['bar'], c['cell']): c for c in load(a, 'chord_proposal.json')}
    bass = {(c['bar'], c['cell']): c['pc_seconds'] for c in load(a, 'bass_per_cell.json')}
    stops = {b for b, k, v in load(a, 'band_level.json') if v < STOP}
    verified = {tuple(k) for k in S.get('verified', [])}
    open_ = sorted(k for k in flags(S, lv, tri, bass) if k not in verified and k[0] not in stops)
    sec = {b: n for n, b0, b1, *_ in S['sections'] for b in range(b0, b1 + 1)}
    out = []
    for key in open_:
        name, par = sec.get(key[0], '?'), parallel_chords(S, key)
        pcs = bass.get(key) or {}
        top = max(pcs, key=pcs.get) if pcs and max(pcs.values()) >= 0.15 else None
        chart = S['chords'][key]
        heard = [lead_sheet(x) for x in (lv.get(key, {}).get('chord'), tri.get(key, {}).get('chord'))
                 if x and x != 'N']
        opts = list(dict.fromkeys([chart] + heard + [p for p in par if p]))
        out.append(dict(bar=key[0], cell=key[1], section=name, chart=chart,
                        lv=lv.get(key, {}).get('chord'), triads=tri.get(key, {}).get('chord'),
                        bass=top, parallel=sorted({p for p in par if p}), options=opts[:4]))
    return out


def pattern_breaks(S: dict, agree: float = 0.65, repeats: int = 3) -> list[dict]:
    """Cells that break their section's repeating pattern: the shortest period (1, 2 or 4
    bars) at which at least `agree` of the section's cells match their position's usual
    chord, seen at least `repeats` times; a cell counts only when the usual chord comes at
    its position both before and after it in the section (a break inside the pattern - a
    turnaround or a different first cycle closes or opens it and is not asked about). A reader can
    agree with itself and still break the pattern (a verse played F# F# A B every time but
    charted A on one B bar - the player heard B)."""
    verified = {tuple(k) for k in S.get('verified', [])}
    ch = S['chords']
    out = []
    for name, b0, b1, *_ in S['sections']:
        bars = list(range(b0, b1 + 1))
        keys = [k for k in sorted(ch) if b0 <= k[0] <= b1 and ch[k] != 'N.C.']
        for per in (1, 2, 4):
            if len(bars) < per * repeats:
                break
            pos = {}
            for k in keys:
                pos.setdefault(((k[0] - b0) % per, k[1]), []).append(k)
            usual = {q: max(set(ch[k] for k in ks), key=[ch[k] for k in ks].count)
                     for q, ks in pos.items()}
            hits = sum(ch[k] == usual[((k[0] - b0) % per, k[1])] for k in keys)
            if keys and hits / len(keys) >= agree:
                for q, ks in pos.items():
                    same = [k for k in ks if ch[k] == usual[q]]
                    if len(same) < repeats:
                        continue
                    out += [dict(bar=k[0], cell=k[1], section=name, chart=ch[k],
                                 usual=usual[q], like=[s[0] for s in same][:4])
                            for i, k in enumerate(ks) if ch[k] != usual[q] and k not in verified
                            and any(ch[x] == usual[q] for x in ks[:i])      # the usual chord
                            and any(ch[x] == usual[q] for x in ks[i + 1:])]  # on both sides
                break
    return sorted(out, key=lambda x: (x['bar'], x['cell']))


def parallel_breaks(S: dict, a: Path, skip: set = frozenset()) -> list[dict]:
    """Cells with no bass (under 0.15 s of any note) charted another chord than every
    parallel section plays there, where no reader objected (those are '?' cells already):
    with no bass both readers hear the same guitar, so their agreement proves little - the
    player's fixes came there (a bar charted Am that the other chorus plays G). Verified
    cells, stop bars and the cells in skip are left out."""
    bass = {(c['bar'], c['cell']): c['pc_seconds'] for c in load(a, 'bass_per_cell.json')}
    stops = {b for b, k, v in load(a, 'band_level.json') if v < STOP}
    verified = {tuple(k) for k in S.get('verified', [])}
    sec = {b: n for n, b0, b1, *_ in S['sections'] for b in range(b0, b1 + 1)}
    out = []
    for key, ch in sorted(S['chords'].items()):
        if ch == 'N.C.' or key in verified or key in skip or key[0] in stops:
            continue
        if max((bass.get(key) or {}).values(), default=0) >= 0.15:
            continue
        par = [p for p in parallel_chords(S, key) if p and p != 'N.C.']
        if par and all(p == par[0] for p in par) and par[0] != ch:
            out.append(dict(bar=key[0], cell=key[1], section=sec.get(key[0], '?'), chart=ch,
                            parallel=par[0]))
    return out


def meter_question(F: dict) -> str | None:
    """The meter and beat 1 to confirm first when Claude chose them (foundation.py meter
    without --decided-by player): every bar-keyed answer depends on them."""
    d = F.get('decided_by') or {}
    if d.get('who') != 'agent' or not F.get('downbeat_times'):
        return None
    sig = F.get('time_signature', '?')
    grp = '+'.join(map(str, F.get('grouping', [])))
    t = F['downbeat_times'][0]
    return (f"meter check: {sig} as {grp}, beat 1 at {mmss(t)} ({t:.2f} s) - "
            f"{', '.join(d.get('what', []))} were Claude's call. Ask the player to count along "
            f"from bar 1 first; once confirmed, re-run foundation.py meter with the same flags "
            f"and --decided-by player")


def timer(F: dict, S: dict):
    """(bar, cell) -> 'm:ss.s-m:ss.s' in the recording ('' past the grid)."""
    db, grouping = list(F.get('downbeat_times') or []), S.get('grouping') or F.get('grouping')
    if len(db) < 2 or not grouping:
        return lambda key: ''
    g = Grid(db, list(grouping))

    def when(key):
        if not (1 <= key[0] < len(db)) or key[1] > g.n:
            return ''
        end = g.start(g.next(key)) if g.next(key)[0] < len(db) else db[-1]
        tenths = lambda s: f'{int(s // 60)}:{s % 60:04.1f}'      # a half-bar can be 1 s
        return f'{tenths(g.start(key))}-{tenths(end)}'
    return when


def score_round(prev: dict, S: dict) -> dict | None:
    """Last round's list against the chart now: listed cells changed / kept, chord changes
    not on the list. None when nothing changed since (no answers yet)."""
    old = {tuple(map(int, k.split('.'))): v for k, v in prev.get('chords', {}).items()}
    now = {k: lead_sheet(v) for k, v in S['chords'].items()}
    ver = sorted(map(list, {tuple(k) for k in S.get('verified', [])}))
    if old == now and ver == prev.get('verified', []):
        return None
    listed = {tuple(x[:2]) for x in prev.get('listed', [])}
    changed = {k for k in set(old) | set(now) if old.get(k) != now.get(k)}
    fix = lambda k: f'{k[0]}.{k[1]} {old.get(k)} -> {now.get(k)}'
    return dict(listed=len(listed), changed=sorted(fix(k) for k in listed & changed),
                kept=len(listed - changed), unlisted_fixes=sorted(fix(k) for k in changed - listed))


def weak_lines(a: Path, share: float = 0.5) -> list[dict]:
    """Lines Whisper heard less than `share` of (lyrics_aligned.json 'matched'): their words
    are placed by misheard stand-ins or guesses - ask the player where they fall (a bridge
    heard as 'snow jesus baby' came out one to two beats early, line after line)."""
    p = a / 'lyrics_aligned.json'
    lines = json.loads(p.read_text()).get('lines', []) if p.exists() else []
    return [dict(where=l.get('where'), matched=l.get('matched'),
                 start=' '.join(l['text'].split()[:3]))
            for l in lines if (l.get('matched') or 0) < share]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('data', help='the chart data file, e.g. gen_v1.py')
    ap.add_argument('--json', help='also write the questions here')
    ap.add_argument('--max', type=int, default=12)
    ap.add_argument('--no-log', action='store_true',
                    help='neither score the last round nor keep this one')
    a = ap.parse_args()
    S = runpy.run_path(a.data)['SONG']
    folder = Path(S.get('folder') or Path(a.data).resolve().parent)
    an = folder / 'analysis'
    fp = an / 'foundation.json'
    F = json.loads(fp.read_text()) if fp.exists() else {}
    when = timer(F, S)
    at = lambda key: f" at {when(key)}" if when(key) else ''
    half = lambda c: 'first' if c == 1 else 'second' if c == 2 else f'cell {c}'
    rnd, log = an / 'questions_round.json', an / 'questions_log.jsonl'
    if not a.no_log and rnd.exists():
        r = score_round(json.loads(rnd.read_text()), S)
        if r:
            with open(log, 'a') as f:
                f.write(json.dumps(r) + '\n')
            print(f"last round's list: {r['listed']} cells - {len(r['changed'])} changed, "
                  f"{r['kept']} kept" + (f"; fixes not on the list: {', '.join(r['unlisted_fixes'])}"
                                         if r['unlisted_fixes'] else '') + f' (-> {log.name})')
    mq = meter_question(F)
    if mq:
        print(mq)
    breaks = pattern_breaks(S)
    for b in breaks:
        print(f"pattern break: bar {b['bar']} ({half(b['cell'])} half, {b['section']}){at((b['bar'], b['cell']))}: "
              f"chart {b['chart']}, but the section plays {b['usual']} there every other time (bars "
              f"{', '.join(map(str, b['like']))}) -> ask: {b['chart']} / {b['usual']}?")
    qs = questions(S, an)
    asked = {(b['bar'], b['cell']) for b in breaks} | {(q['bar'], q['cell']) for q in qs}
    pars = parallel_breaks(S, an, asked)
    for p in pars:
        print(f"parallel check: bar {p['bar']} ({half(p['cell'])} half, {p['section']}){at((p['bar'], p['cell']))}: "
              f"chart {p['chart']}, the parallel section plays {p['parallel']}, no bass to "
              f"decide -> ask: {p['chart']} / {p['parallel']}?")
    if not qs:
        print('no open chord calls: every "?" is verified or in a stop bar')
    qs.sort(key=lambda q: (not any(p != q['chart'] for p in q['parallel']), q['bar'], q['cell']))
    for q in qs[:a.max]:
        par = f", parallel section: {'/'.join(q['parallel'])}" if q['parallel'] else ''
        print(f"bar {q['bar']} ({half(q['cell'])} half, {q['section']}){at((q['bar'], q['cell']))}: "
              f"chart {q['chart']}; lv-chordia {q['lv']}, triads {q['triads']}, bass "
              f"{q['bass'] or 'none'}{par} -> ask: {' / '.join(q['options'])}?")
    if len(qs) > a.max:
        print(f'... {len(qs) - a.max} more (--max)')
    weak = weak_lines(an)
    for w in weak:
        where = 'bar %d.%d' % tuple(w['where']) if w['where'] else 'unplaced'
        tm = at(tuple(w['where'])) if w['where'] else ''
        print(f"placement check: the line starting '{w['start']}…' ({where}{tm}) - Whisper heard "
              f"{w['matched']:.0%} of its words; ask where each word falls")
    if a.json:
        Path(a.json).write_text(json.dumps(qs, indent=1))
    if not a.no_log and an.is_dir():
        listed = ([[b['bar'], b['cell'], 'pattern'] for b in breaks] +
                  [[p['bar'], p['cell'], 'parallel'] for p in pars] +
                  [[q['bar'], q['cell'], 'reader'] for q in qs[:a.max]])
        rnd.write_text(json.dumps(dict(
            listed=listed, verified=sorted(map(list, {tuple(k) for k in S.get('verified', [])})),
            chords={f'{b}.{c}': lead_sheet(v) for (b, c), v in sorted(S['chords'].items())})))


if __name__ == '__main__':
    main()
