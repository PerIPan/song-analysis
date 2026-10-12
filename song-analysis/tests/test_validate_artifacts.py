#!/usr/bin/env python3
"""Test scripts/validate_artifacts.py on synthetic analysis folders (no audio, temp dirs).

A clean 4/4 folder passes; chord or bass cells made before beat 1 moved (their t0 off the
grid) or with another grouping fail; cells without t0 only warn; the cache check finds the
demucs (ft, 6s) and Whisper weights in a stand-in hub and names what is missing.
Run: python3 tests/test_validate_artifacts.py
"""
import atexit, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_artifacts.py"
TMP = Path(tempfile.mkdtemp(prefix="validate_"))
atexit.register(shutil.rmtree, TMP, True)


def folder(shift=0.0, grouping=(2, 2), t0=True, nbars=4, bar=2.0):
    """analysis/ with foundation.json on a 0.5 s beat grid and three bar-keyed files whose
    cells start `shift` seconds off it."""
    a = Path(tempfile.mkdtemp(dir=TMP)) / "analysis"
    a.mkdir()
    beats = [round(0.5 * i, 4) for i in range(int(nbars * bar / 0.5) + 1)]
    db = beats[::4]
    put = lambda n, o: (a / n).write_text(json.dumps(o))
    put("foundation.json", dict(beat_times=beats, step="meter", downbeat_times=db, grouping=[2, 2],
                                beats_per_bar=4, num_bars=len(db) - 1, bar_bpm=[120.0] * (len(db) - 1),
                                pulse_unit=4, tempo_drift_pct=0))
    cells = [dict(bar=b, cell=c, **({"t0": round(db[b - 1] + bar * (c - 1) / 2 + shift, 3)} if t0 else {}))
             for b in range(1, len(db)) for c in (1, 2)]
    put("chords_lv.json", dict(grouping=list(grouping), cells=[dict(x, chord="C") for x in cells]))
    put("chord_proposal.json", dict(grouping=list(grouping), cells=[dict(x, chord="C") for x in cells]))
    put("bass_per_cell.json", dict(cells=[dict(x, pc_seconds={}) for x in cells]))
    return a


def run(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True,
                          text=True, env=env)


def main():
    fails = 0
    def check(name, cond, info=""):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"  [{info}]"))

    r = run(folder())
    check("cells on the grid: ok, exit 0", r.returncode == 0 and r.stdout.strip().endswith("ok")
          and "another grid" not in r.stdout, r.stdout)
    r = run(folder(shift=1.0))
    check("beat 1 moved half a bar since: an error per bar-keyed file, exit 1",
          r.returncode == 1 and r.stdout.count("was made on another grid") == 3, r.stdout)
    r = run(folder(shift=0.03))
    check("30 ms off (rounding): still on the grid", r.returncode == 0, r.stdout)
    r = run(folder(grouping=(3, 1)))
    check("another grouping: an error naming both", r.returncode == 1
          and "grouping [3, 1], foundation.json's is [2, 2]" in r.stdout, r.stdout)
    r = run(folder(t0=False))
    check("no cell times: a warning, not an error", r.returncode == 0
          and r.stdout.count("records no cell times") == 3, r.stdout)

    hub = TMP / "hub"
    env = dict(os.environ, HF_HUB_CACHE=str(hub), HOME=str(TMP / "home"))
    r = run(folder(), "--check-cache", env=env)
    check("empty cache: ft, 6s and whisper named", "htdemucs_ft: 4 of 4" in r.stdout
          and "htdemucs_6s: 1 of 1" in r.stdout and "whisper-large-v3-turbo" in r.stdout
          and "HF_HUB_OFFLINE" not in r.stdout, r.stdout)
    for repo, files in (("adefossez--HTDemucs-ft", ["f7e0c4bc.safetensors", "d12395a8.safetensors",
                                                    "92cfc3b6.safetensors", "04573f0d.safetensors"]),
                        ("adefossez--HTDemucs-6s", ["5c90dfd2.safetensors"]),
                        ("mlx-community--whisper-large-v3-turbo", ["weights.safetensors"])):
        snap = hub / f"models--{repo}" / "snapshots" / "abc"
        snap.mkdir(parents=True)
        for f in files:
            (snap / f).write_bytes(b"")
    r = run(folder(), "--check-cache", env=env)
    check("all cached: no cache warning, offline hint", "not cached" not in r.stdout
          and "HF_HUB_OFFLINE=1" in r.stdout, r.stdout)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
