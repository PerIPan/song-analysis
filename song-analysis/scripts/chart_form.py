#!/usr/bin/env python3
"""The chart's form, folded: each section as a repeating pattern x N plus what differs.

Why: a chart with one cell per half-bar runs 4-6 pages for a 100-bar song; band charts
(iReal Pro, a gig sheet) show the form - "verse: | Am | F | C | G | x4" - in 1-2 pages,
and iReal Pro holds at most 12 lines of 16 cells. Folding reads the chart data file's
chords as they hold (an empty cell holds the previous chord) and finds, per section, the
pattern of 1, 2, 4 or 8 bars, repeated at least twice from its first bar or after up to
four lead-in bars (a head: an outro that opens with the chorus line), that leaves the
least to write: the head, the pattern once, the bars after the last whole repeat (a tail: a
turnaround, a different last cycle) and - when near repeats are allowed (`tolerance`
bars per cycle, a gig sheet) - the bars that differ, listed by number. Each position's
pattern bar is the one most cycles play there. Exact folding (tolerance 0) is what iReal
Pro can show. A section with no repeat is kept bar by bar; sections whose bars equal an
earlier section's are marked as the same.

Library for chart_export.py (python3, standard library only):
    bars = bar_chords(S, ncells)          # {bar: (chord per cell, ...)}, holds filled in
    form = fold(S, ncells, tolerance=0)   # [Section(name, kind, b0, b1, head, pattern,
                                          #   times, tail, differs, same_as), ...]
"""
from __future__ import annotations

from dataclasses import dataclass

PERIODS = (1, 2, 4, 8)


@dataclass
class Section:
    name: str
    kind: str
    b0: int
    b1: int
    head: list           # lead-in bars before the repeat
    pattern: list        # [bar chords tuple, ...] repeated `times` times after the head
    times: int           # 1 = no repeat found: pattern is every bar
    tail: list           # bars after the last whole repeat
    differs: list        # [(bar number, bar chords), ...] inside the repeats, unlike the pattern
    same_as: str | None  # an earlier section with exactly these bars


def bar_chords(S: dict, ncells: int) -> dict:
    """{bar: tuple of each cell's chord}: an empty cell holds the chord before it (across
    bars and sections); before any chord, ''."""
    last_bar = max(sec[2] for sec in S['sections'])
    out, held = {}, ''
    for b in range(1, last_bar + 1):
        row = []
        for c in range(1, ncells + 1):
            held = S['chords'].get((b, c)) or held
            row.append(held)
        out[b] = tuple(row)
    return out


def fold_bars(bars: list, tolerance: int = 0) -> tuple[list, list, int, list, list]:
    """(head, pattern, times, tail, differs) for a list of bars: of the periods that repeat
    at least twice from the start or after a head of up to 4 bars - each later cycle
    differing in at most `tolerance` bars, and in under half the cycle (1- and 2-bar
    patterns repeat exactly) - the one leaving the least to write (head + pattern + tail +
    differing bars; on a tie a repeat starting on a phrase boundary - a head of whole
    pattern lengths - then the shorter tail, then the shorter head). differs = [(index in bars, bar), ...]. No repeat:
    ([], bars, 1, [], [])."""
    best = (len(bars), [], list(bars), 1, [], [])
    for h in range(0, min(4, len(bars)) + 1):
        best = min(best, fold_from(bars, h, tolerance),
                   key=lambda x: (x[0], len(x[1]) % max(1, len(x[2])) != 0, len(x[4]), len(x[1])))
    return best[1:]


def fold_from(bars: list, h: int, tolerance: int) -> tuple:
    """fold_bars with the repeat starting after h head bars: (cost, head, pattern, times,
    tail, differs)."""
    head, bars = list(bars[:h]), bars[h:]
    best = (h + len(bars), head, list(bars), 1, [], [])
    for p in PERIODS:
        if len(bars) < 2 * p:
            break
        allowed = min(tolerance, (p - 1) // 2)       # under half a cycle: 1- and 2-bar exact
        k, cycles = 1, [bars[:p]]
        while (k + 1) * p <= len(bars):
            nxt = bars[k * p:(k + 1) * p]
            if sum(a != b for a, b in zip(nxt, cycles[0])) > allowed:
                break
            cycles.append(nxt)
            k += 1
        if k < 2:
            continue
        pattern = [max((c[i] for c in cycles), key=[c[i] for c in cycles].count)
                   for i in range(p)]
        differs = [(h + n * p + i, c[i]) for n, c in enumerate(cycles) for i in range(p)
                   if c[i] != pattern[i]]
        if len(differs) > allowed * k:
            continue
        tail = bars[k * p:]
        cost = h + p + len(tail) + len(differs)
        if cost < best[0]:
            best = (cost, head, pattern, k, tail, differs)
    return best


def fold(S: dict, ncells: int, tolerance: int = 0) -> list[Section]:
    bars = bar_chords(S, ncells)
    out, seen = [], {}
    for name, b0, b1, kind, *_ in S['sections']:
        these = [bars[b] for b in range(b0, b1 + 1)]
        head, pattern, times, tail, differs = fold_bars(these, tolerance)
        key = tuple(these)
        out.append(Section(name, kind, b0, b1, head, pattern, times, tail,
                           [(b0 + i, bar) for i, bar in differs], seen.get(key)))
        seen.setdefault(key, name)
    return out
