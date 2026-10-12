#!/usr/bin/env python3
"""Phase 7 cross-check: chroma + bass-root constraint with slash relaxation.

One proposal per cell, where cells are the metric groups of each bar (the
`grouping` in foundation.json: 4/4 -> [2, 2], 11/8 as 6+5 -> [6, 5]). Scores
all 24 major/minor triads against the cell's chroma on the harmonic stem; when
the bass sustains one pitch class, prefers triads on that root unless that
costs more than RELAX (then the bass is a non-root chord tone - a slash chord).

MAJOR_BIAS defaults to 0 and is never gated on the key. A second pass at
--bias-diff (default 0.05) reports how many cells the bias would flip: a large
count means near-ties, so say the quality call is uncertain.

Usage (analysis venv; needs numpy + librosa):
    <venv>/bin/python chord_proposal.py --other stems/htdemucs_ft/<song>/other.wav \
        --bass stems/htdemucs_ft/<song>/bass.wav --foundation analysis/foundation.json \
        [--grouping 6,5] [--bass-entry-bar 5] [--out analysis/chord_proposal.json]

Without --bass-entry-bar the bar comes from bass_notes.json next to foundation.json (the
bar bass_notes.py used), with a warning when bass_notes suggested a later one.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
import librosa

RELAX = 0.85
HOP = 512
SR = 22050
PC_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PC_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SHARP_MAJOR = {"G", "D", "A", "E", "B", "F#", "C#"}
SHARP_MINOR = {"E", "B", "F#", "C#", "G#", "D#", "A#"}


def templates():
    """24 binary triads (root, 3rd, 5th), sum-normalised. Key: (root_pc, '' | 'm')."""
    out = {}
    for root in range(12):
        for quality, ivs in (("", (0, 4, 7)), ("m", (0, 3, 7))):
            v = np.zeros(12)
            v[[(root + i) % 12 for i in ivs]] = 1
            out[(root, quality)] = v / v.sum()
    return out


def spelling_for(key_top2):
    """Sharp names in sharp keys, flat names otherwise. key_top2 as foundation.py writes it:
    [["F# minor", 0.61], ["A major", 0.2]] - the top entry decides."""
    if not key_top2:
        return PC_FLAT
    tonic, mode = key_top2[0][0].split()
    return PC_SHARP if tonic in (SHARP_MINOR if mode == "minor" else SHARP_MAJOR) else PC_FLAT


def cells_of(downbeats, grouping):
    """(bar, cell, t0, t1) for every metric group of every bar."""
    bpb = sum(grouping)
    edges = np.concatenate([[0], np.cumsum(grouping)]) / bpb
    for i, (b0, b1) in enumerate(zip(downbeats[:-1], downbeats[1:])):
        for k in range(len(grouping)):
            yield i + 1, k + 1, b0 + (b1 - b0) * edges[k], b0 + (b1 - b0) * edges[k + 1]


def propose(cell_chroma, bass_pc, T, major_bias):
    """Ranked [(score, key)], chosen key, and whether the bass constraint was relaxed."""
    ranked = sorted(((float(np.dot(cell_chroma, v)), k) for k, v in T.items()), reverse=True)
    order, relaxed = ranked, False
    if bass_pc is not None:
        on_bass = [x for x in ranked if x[1][0] == bass_pc]
        if on_bass and on_bass[0][0] >= RELAX * ranked[0][0]:
            order = on_bass + [x for x in ranked if x[1][0] != bass_pc]
        else:
            relaxed = True                          # bass is the 3rd/5th: slash chord
    top = order[0]
    if major_bias > 0 and top[1][1] == "m":         # optional; default 0
        maj = next((x for x in order if x[1] == (top[1][0], "")), None)
        if maj and top[0] - maj[0] < major_bias:
            top = maj
    return order, top, relaxed


def entry_from_bass_notes(path):
    """The bass entry bar bass_notes.py used (1 without the file); warns when it suggested
    a later bar than it used - the bass notes before it are probably stem bleed."""
    if not path.exists():
        return 1
    B = json.load(open(path))
    used, hint = B.get("bass_entry_bar", 1), B.get("suggested_entry_bar", 1)
    if hint > used:
        print(f"WARNING: bass_notes.py suggests the bass enters at bar {hint} but ran from bar "
              f"{used}: re-run it with --bass-entry-bar {hint} first (or pass "
              f"--bass-entry-bar here)")
    elif used > 1:
        print(f"bass entry bar {used} (from {path.name})")
    return used


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--other", required=True, help="harmonic stem (other.wav)")
    ap.add_argument("--bass", help="bass stem; without it there is no root constraint")
    ap.add_argument("--foundation", required=True, help="foundation.json")
    ap.add_argument("--grouping", help="override, e.g. 2,2 or 6,5")
    ap.add_argument("--bass-entry-bar", type=int,
                    help="ignore the bass before this bar (pre-entry content is bleed); "
                         "default: bass_notes.json's, else 1")
    ap.add_argument("--major-bias", type=float, default=0.0)
    ap.add_argument("--bias-diff", type=float, default=0.05,
                    help="second pass with this bias; reports flips (0 = skip)")
    ap.add_argument("--out", help="write per-cell JSON here")
    a = ap.parse_args()

    F = json.load(open(a.foundation))
    if a.bass_entry_bar is None:
        a.bass_entry_bar = entry_from_bass_notes(Path(a.foundation).with_name("bass_notes.json"))
    grouping = [int(x) for x in a.grouping.split(",")] if a.grouping else F.get("grouping")
    if not grouping:
        sys.exit("No grouping. Run detect_meter.py first and set foundation.json "
                 "'grouping' (4/4 -> [2, 2]) or pass --grouping. Never assume 4/4.")
    downbeats = F["downbeat_times"]
    PC = spelling_for(F.get("key_top2"))
    T = templates()

    y, _ = librosa.load(a.other, sr=SR, mono=True)
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP, bins_per_octave=36)
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    onset_ref = float(np.median(onset)) or 1e-9
    if a.bass:
        yb, _ = librosa.load(a.bass, sr=SR, mono=True)
        bchroma = librosa.feature.chroma_cqt(y=yb, sr=SR, hop_length=HOP, bins_per_octave=36)

    cells = []
    for bar, cell, t0, t1 in cells_of(downbeats, grouping):
        f0 = int(t0 * SR / HOP); f1 = max(int(t1 * SR / HOP), f0 + 1)
        c = chroma[:, f0:f1].mean(axis=1)
        if c.sum() <= 0:
            continue
        c = c / c.sum()
        bass_pc, bass_rms = None, 0.0
        if a.bass and bar >= a.bass_entry_bar:
            bass_rms = float(np.sqrt(np.mean(yb[int(t0 * SR):int(t1 * SR)] ** 2)))
            bass_pc = int(np.argmax(bchroma[:, f0:f1].mean(axis=1)))
        attack = float(onset[max(f0 - 2, 0):f0 + 3].max()) / onset_ref
        cells.append(dict(bar=bar, cell=cell, t0=round(t0, 3), t1=round(t1, 3),
                          chroma=c, bass_pc=bass_pc, bass_rms=bass_rms,
                          re_attack=bool(attack > 2.0)))

    if a.bass:                                      # quiet cells: no bass decision
        floor = np.percentile([x["bass_rms"] for x in cells if x["bass_pc"] is not None]
                              or [0.0], 35)
        for x in cells:
            if x["bass_pc"] is not None and x["bass_rms"] <= floor:
                x["bass_pc"] = None

    name = lambda k: PC[k[0]] + k[1]
    out, flips = [], []
    for x in cells:
        order, top, relaxed = propose(x["chroma"], x["bass_pc"], T, a.major_bias)
        second = next(s for s in order if s[1] != top[1])
        rec = dict(bar=x["bar"], cell=x["cell"], t0=x["t0"], t1=x["t1"],
                   chord=name(top[1]), score=round(top[0], 4),
                   margin=round(top[0] - second[0], 4),       # small = near-tie
                   alts=[name(s[1]) for s in order if s[1] != top[1]][:2],
                   bass=PC[x["bass_pc"]] if x["bass_pc"] is not None else None,
                   slash_relaxed=relaxed, re_attack=x["re_attack"])
        if a.bias_diff > 0:
            _, biased, _ = propose(x["chroma"], x["bass_pc"], T, a.bias_diff)
            if biased[1] != top[1]:
                rec["biased"] = name(biased[1])
                flips.append((x["bar"], x["cell"], rec["chord"], rec["biased"]))
        out.append(rec)

    bars = {}
    for r in out:
        bars.setdefault(r["bar"], []).append(r["chord"])
    line = " ".join("|".join(dict.fromkeys(v)) for _, v in sorted(bars.items()))
    print(f"{len(out)} cells over {len(bars)} bars, grouping {grouping}, "
          f"spelling {'sharp' if PC is PC_SHARP else 'flat'}")
    print("bars:", line)
    near = sum(r["margin"] < 0.01 for r in out)
    print(f"near-ties (margin < 0.01): {near}/{len(out)} cells")
    if a.bias_diff > 0:
        print(f"major-bias {a.bias_diff} would flip {len(flips)}/{len(out)} cells"
              + (" - quality calls are uncertain there; say so" if flips else ""))
    if a.out:
        json.dump(dict(grouping=grouping, major_bias=a.major_bias, relax=RELAX,
                       bias_diff=a.bias_diff, flips=flips, cells=out),
                  open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
