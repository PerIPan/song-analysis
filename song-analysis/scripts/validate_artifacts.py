#!/usr/bin/env python3
"""Check the analysis folder's artifacts agree with each other before building on them.

Catches the silent hand-off errors: downbeats that aren't on the beat grid, a
grouping that doesn't sum to the bar, chord cells missing bars or made on another grid
(their t0 off the current downbeats: beat 1 or the bars moved since - the costly one,
since every (bar, cell) key shifts), times running backwards, a model that would
download silently. Exit 1 on any error.

Usage (any Python 3.8+):  validate_artifacts.py [analysis] [--check-cache]

--check-cache: the htdemucs_ft and htdemucs_6s checkpoints and Whisper large-v3-turbo
(mlx) in the Hugging Face / torch hub caches. lv-chordia, madmom and ADTOF ship their
weights in the package. With all cached, run the model steps with HF_HUB_OFFLINE=1.
"""
import argparse, json, os, sys
from pathlib import Path

errors, warnings = [], []


def err(msg): errors.append(msg)
def warn(msg): warnings.append(msg)


def monotonic(xs, name, tol=0.0):
    bad = [i for i in range(1, len(xs)) if xs[i] < xs[i - 1] - tol]
    if bad:
        err(f"{name}: times go backwards at {len(bad)} place(s), first at index {bad[0]}")


def cell_starts(db, grouping):
    """{(bar, cell): start} on this grid - the cells every bar-keyed script cuts."""
    bpb, out = sum(grouping), {}
    for i, (b0, b1) in enumerate(zip(db[:-1], db[1:])):
        acc = 0
        for k, g in enumerate(grouping):
            out[(i + 1, k + 1)] = b0 + (b1 - b0) * acc / bpb
            acc += g
    return out


def off_grid(d, starts, grouping, tol=0.05):
    """Why a bar-keyed file isn't on this grid (another grouping, or a cell starting
    elsewhere), None when it is, '' when it can't tell (no t0 recorded)."""
    if d.get("grouping") and list(d["grouping"]) != list(grouping):
        return f"grouping {d['grouping']}, foundation.json's is {grouping}"
    timed = [c for c in d["cells"] if "t0" in c and (c["bar"], c["cell"]) in starts]
    for c in timed:
        if abs(c["t0"] - starts[(c["bar"], c["cell"])]) > tol:
            return (f"bar {c['bar']} cell {c['cell']} starts at {c['t0']:.2f} s, on the grid "
                    f"{starts[(c['bar'], c['cell'])]:.2f} s")
    return None if timed else ""


CACHE = (  # (model, checkpoint hashes, HF hub repo) - demucs 4.0 used the torch hub
    ("htdemucs_ft", ["f7e0c4bc", "d12395a8", "92cfc3b6", "04573f0d"], "adefossez--HTDemucs-ft"),
    ("htdemucs_6s", ["5c90dfd2"], "adefossez--HTDemucs-6s"))


def check_cache():
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get(
        "HF_HOME", os.path.expanduser("~/.cache/huggingface"))) / "hub")
    for model, hashes, repo in CACHE:
        dirs = [Path(os.path.expanduser("~/.cache/torch/hub/checkpoints")),
                *(hub / f"models--{repo}" / "snapshots").glob("*")]
        names = [p.name for d in dirs if d.is_dir() for p in d.iterdir()]
        have = [h for h in hashes if any(n.startswith(h) and n.endswith((".th", ".safetensors"))
                                         for n in names)]
        if len(have) < len(hashes):
            warn(f"{model}: {len(hashes) - len(have)} of {len(hashes)} checkpoints not cached - "
                 f"demucs will download ~{84 * (len(hashes) - len(have))} MB silently")
    if not list(hub.glob("models--mlx-community--whisper-large-v3-turbo/snapshots/*/weights.*")):
        warn("whisper-large-v3-turbo (mlx) not cached - whisper_gated.py will download ~1.5 GB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("analysis", nargs="?", default="analysis")
    ap.add_argument("--check-cache", action="store_true",
                    help="also check the demucs (ft, 6s) and Whisper weights are cached")
    a = ap.parse_args()
    A = Path(a.analysis)
    rd = lambda n: json.load(open(A / n)) if (A / n).exists() else None

    F = rd("foundation.json")
    if not F:
        err("foundation.json missing - run foundation.py pulse")
    else:
        bt = F["beat_times"]
        monotonic(bt, "beat_times")
        if F.get("step") != "meter":
            warn("foundation.json has no meter yet - run detect_meter.py, then foundation.py meter")
        else:
            db, g, n = F["downbeat_times"], F["grouping"], F["beats_per_bar"]
            monotonic(db, "downbeat_times")
            if sum(g) != n:
                err(f"grouping {g} sums to {sum(g)}, not beats_per_bar {n}")
            on_grid = set(round(b, 4) for b in bt)
            if any(round(d, 4) not in on_grid for d in db):
                err("some downbeat_times are not on the beat grid")
            if len(F["bar_bpm"]) != F["num_bars"] or F["num_bars"] != len(db) - 1:
                err(f"num_bars {F['num_bars']}, bar_bpm {len(F['bar_bpm'])} and "
                    f"downbeats-1 {len(db) - 1} disagree")
            if F.get("pulse_unit") not in (4, 8):
                err(f"pulse_unit {F.get('pulse_unit')} is not 4 or 8")
            if F.get("tempo_drift_pct", 0) > 3:
                warn(f"tempo drifts {F['tempo_drift_pct']}% - place notes through the beat grid")
            starts = cell_starts(db, g)
            for art in ("chords_lv.json", "chord_proposal.json", "bass_per_cell.json"):
                d = rd(art)
                if not d:
                    continue
                why = off_grid(d, starts, g)
                if why:
                    err(f"{art} was made on another grid ({why}): beat 1 or the bars moved "
                        f"since - re-run it before anything keyed by bar")
                elif why == "":
                    warn(f"{art} records no cell times (made before they were written): "
                         f"its grid can't be checked - re-run it to be sure")
                have = {(c["bar"], c["cell"]) for c in d["cells"]}
                want = {(b, k) for b in range(1, F["num_bars"] + 1) for k in range(1, len(g) + 1)}
                missing = want - have
                if len(missing) > 0.05 * len(want):
                    err(f"{art}: {len(missing)} of {len(want)} (bar, cell) cells missing - "
                        f"made with a different foundation? re-run it")
                elif missing:
                    warn(f"{art}: {len(missing)} cells missing (silent cells are skipped)")
                ts = [c["t0"] for c in d["cells"] if "t0" in c]
                monotonic(ts, art)

    L = rd("lyrics.json")
    if L:
        monotonic([w["start"] for w in L["words"]], "lyrics.json words", tol=0.05)
    AL = rd("lyrics_aligned.json")
    if AL:
        monotonic([l["start"] for l in AL["lines"] if l["start"] is not None], "lyrics_aligned lines")
        weak = sum(l["matched"] < 0.3 for l in AL["lines"])
        if weak:
            warn(f"{weak} lyric lines under 30% matched - their times are interpolated")
    S = rd("sections.json")
    if S:
        monotonic([s["t"] for s in S["sections"]], "sections.json")

    if a.check_cache:
        check_cache()
        if not any("not cached" in w for w in warnings):
            print("models cached: run the model steps with HF_HUB_OFFLINE=1")

    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print("ok" if not errors else f"{len(errors)} error(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
