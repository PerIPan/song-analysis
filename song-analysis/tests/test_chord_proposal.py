#!/usr/bin/env python3
"""Smoke test for scripts/chord_proposal.py on a synthetic progression.

A-minor progression in 4/4 (grouping 2+2) rendered as sine triads over a sine bass.
Checks: minor chords stay minor at the default bias of 0; a first-inversion chord
(G/B, bass on the 3rd) is relaxed to G instead of forced to Bm; the harmonic-minor
V (E) is major; flat spelling in A minor; without --bass-entry-bar the bar comes
from bass_notes.json, with a warning when bass_notes suggested a later one.

Run with the analysis venv (numpy, librosa, soundfile):
    <venv>/bin/python tests/test_chord_proposal.py
"""
import json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "chord_proposal.py"
SR, BAR = 22050, 2.0                          # 120 BPM, 4/4
PROG = [  # (chord tones as MIDI, bass MIDI, expected label) per bar
    ((57, 60, 64), 45, "Am"), ((53, 57, 60), 41, "F"), ((60, 64, 67), 48, "C"),
    ((55, 59, 62), 47, "G"),                  # G/B: bass on the 3rd
    ((62, 65, 69), 50, "Dm"), ((57, 60, 64), 45, "Am"), ((56, 59, 64), 40, "E"),
    ((57, 60, 64), 45, "Am"),
]


def tone(midi, dur, amp):
    t = np.arange(int(SR * dur)) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    env = np.minimum(1, t / 0.01) * np.exp(-t * 0.8)
    return amp * env * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t))


def main():
    other = np.concatenate([sum(tone(m, BAR, 0.2) for m in ch) for ch, _, _ in PROG])
    bass = np.concatenate([tone(b, BAR, 0.5) for _, b, _ in PROG])
    rng = np.random.default_rng(0)
    other += 0.003 * rng.standard_normal(len(other))
    bass += 0.003 * rng.standard_normal(len(bass))
    with tempfile.TemporaryDirectory() as d:
        o, b, f, out = (Path(d) / n for n in ("other.wav", "bass.wav", "f.json", "o.json"))
        sf.write(o, other, SR); sf.write(b, bass, SR)
        json.dump({"downbeat_times": [i * BAR for i in range(len(PROG) + 1)],
                   "grouping": [2, 2], "key_top2": [["A minor", 0.8]]}, open(f, "w"))
        r = subprocess.run([sys.executable, str(SCRIPT), "--other", str(o), "--bass", str(b),
                            "--foundation", str(f), "--out", str(out)],
                           capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode:
            print(r.stderr); sys.exit(1)
        cells = json.load(open(out))["cells"]
        json.dump({"bass_entry_bar": 3, "suggested_entry_bar": 5}, open(Path(d) / "bass_notes.json", "w"))
        r2 = subprocess.run([sys.executable, str(SCRIPT), "--other", str(o), "--bass", str(b),
                             "--foundation", str(f), "--out", str(out), "--bias-diff", "0"],
                            capture_output=True, text=True)
        late = json.load(open(out))["cells"]
    fails = 0
    ok = (r2.returncode == 0 and "re-run it with --bass-entry-bar 5" in r2.stdout
          and all(c["bass"] is None for c in late if c["bar"] < 3)
          and any(c["bass"] for c in late if c["bar"] >= 3))
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  no --bass-entry-bar: bass_notes.json's bar 3 used, its "
          f"later suggestion (5) warned about")
    for bar, (_, _, want) in enumerate(PROG, start=1):
        got = [c["chord"] for c in cells if c["bar"] == bar]
        ok = got and all(g == want for g in got)
        fails += not ok
        extra = " (slash relaxed)" if any(c["slash_relaxed"] for c in cells if c["bar"] == bar) else ""
        print(f"{'PASS' if ok else 'FAIL'}  bar {bar}: want {want}  got {got}{extra}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
