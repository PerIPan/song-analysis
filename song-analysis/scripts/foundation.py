#!/usr/bin/env python3
"""Write analysis/foundation.json in two steps: pulse + key first, meter after the sweep.

    foundation.py pulse <song.mp3> --out analysis/foundation.json
        madmom beats with NO bar assumption, pulse BPM, madmom CNN key (top two).

    foundation.py meter --foundation analysis/foundation.json --meter analysis/meter.json
        [--cycle N] [--grouping 6,5] [--downbeat-pulse K] [--use-alternative]
        [--pulse-unit 4|8] [--decided-by agent|player]
        Adds the meter from detect_meter.py --json: beats_per_bar, pulse_unit,
        grouping, downbeat_times, num_bars, bar_bpm, tempo_drift_pct, live_tempo.

The meter step refuses to guess. It stops with the question to ask the user when
the sweep was INCONCLUSIVE, found a phrase-length cycle (8/16/24) or a bare duple
(2), could not tell which of two accents is beat 1, or found an odd cycle without
a stated pulse unit (11/8 and 11/4 differ by 2x in Live's tempo). A question exits 2
with "NEEDS A DECISION: ..." on stderr; 1 is an error.

Who chose what the flags set is recorded: --decided-by player when the player counted
or confirmed it, agent (the default) when Claude chose - the provenance then says so,
and chart_questions.py asks the player to confirm the meter and beat 1 first. A meter
measured at LOW confidence is kept but listed under to_confirm for the same question: on
one song two stem separations moved beat 1 by three pulses (snare band, then bass band).

Run with the analysis venv (madmom + numpy; the meter step needs only numpy).
"""
import argparse, json, sys

CONVENTION = {2: [2], 3: [3], 4: [2, 2], 6: [3, 3], 8: [4, 4], 9: [3, 3, 3], 12: [3, 3, 3, 3]}


def ask(msg):
    """Stop with the question the agent should put to the user: exit 2 (1 is an error)."""
    print(f"NEEDS A DECISION: {msg}", file=sys.stderr)
    sys.exit(2)


def repair_grid(beats):
    """Fill beat gaps of ~2x or ~3x the median interval (a tracker octave switch).

    madmom can drop to half time for a stretch - one song's grid went half-time for
    100 s, turning 19 of 73 bars into double bars. Gaps of 1.8-2.25x get one beat
    inserted, 2.7-3.3x get two; the 1.5x (3:2) gaps of aksak groupings are left
    alone. Assumes most of the song is tracked at the right rate (the median).
    """
    import numpy as np
    beats = np.asarray(beats, float)
    ibi = np.diff(beats)
    med = float(np.median(ibi))
    out, spans = [beats[0]], []
    for b0, b1, g in zip(beats[:-1], beats[1:], ibi):
        n = 2 if 1.8 <= g / med <= 2.25 else 3 if 2.7 <= g / med <= 3.3 else 1
        out.extend(b0 + g * j / n for j in range(1, n))
        out.append(b1)
        if n > 1:
            if spans and b0 - spans[-1][1] <= 3 * med:
                spans[-1][1] = b1
            else:
                spans.append([b0, b1])
    return np.array(out), len(out) - len(beats), spans


def cmd_pulse(a):
    import numpy as np
    from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
    from madmom.features.key import CNNKeyRecognitionProcessor, KEY_LABELS
    beats = DBNBeatTrackingProcessor(fps=100, min_bpm=a.min_bpm, max_bpm=a.max_bpm)(
        RNNBeatProcessor()(a.audio))                                # beats only, no bars
    inserted, spans = 0, []
    if not a.no_repair:
        beats, inserted, spans = repair_grid(beats)
        for s0, s1 in spans:
            print(f"GRID REPAIR: filled beats {s0:.1f}-{s1:.1f}s (tracker dropped a tempo octave)")
    probs = CNNKeyRecognitionProcessor()(a.audio)[0]
    key_top2 = [[KEY_LABELS[i], round(float(probs[i]), 2)] for i in np.argsort(probs)[::-1][:2]]
    bpm = round(60.0 / float(np.median(np.diff(beats))), 2)
    octave = ("fast: probably eighth notes (quarter ~%.0f)" % (bpm / 2) if bpm > 160 else
              "slow: may be half-time - the meter sweep will also try a 2x grid" if bpm < 70
              else "ok")
    F = dict(audio=a.audio, pulse_bpm=bpm, tempo_octave=octave,
             beat_times=[round(float(b), 4) for b in beats], key_top2=key_top2, step="pulse",
             grid_repair=dict(inserted=inserted, spans=[[round(x, 2) for x in s] for s in spans]),
             provenance=dict(pulse="measured (madmom DBN, %g-%g BPM)" % (a.min_bpm, a.max_bpm)
                             + (f"; {inserted} beats filled in" if inserted else ""),
                             key_top2="measured (madmom CNN; melody's key)"))
    json.dump(F, open(a.out, "w"), indent=1)
    if octave != "ok":
        print(f"TEMPO OCTAVE: {bpm} BPM is {octave}. Force another octave with "
              f"--min-bpm/--max-bpm if the user's count disagrees.")
    print(f"pulse {F['pulse_bpm']} BPM, {len(beats)} beats; key {key_top2[0][0]} "
          f"(p={key_top2[0][1]}), then {key_top2[1][0]} (p={key_top2[1][1]}) - the melody's "
          f"key; check it against the bass pedal later")


def cmd_meter(a):
    F = json.load(open(a.foundation))
    cons = json.load(open(a.meter)).get("consensus")
    bt = F["beat_times"]

    if cons is None and not a.cycle:
        ask("the meter sweep was INCONCLUSIVE. Ask the user to count along with the kick, "
            "then re-run with --cycle N --grouping a,b [--downbeat-pulse K].")
    found = cons["cycle"] if cons else None
    if found in (8, 16, 24) and not a.cycle:
        fast = F["pulse_bpm"] > 140
        ask(f"the sweep found {found} pulses - usually {found // 4} bars of 4/4, not one bar"
            + (f", unless the {F['pulse_bpm']} BPM pulse is eighth notes (then it is one bar: "
               f"--cycle {found} --pulse-unit 8)" if fast else "")
            + f". Re-run with --cycle 4 (4/4 with a {found // 4}-bar pattern) or --cycle "
              f"{found} to keep it as one bar (an aksak {found} such as 3+3+2 needs "
              f"--grouping too).")
    if found == 2 and not a.cycle:
        ask("the sweep found a duple pulse (2) - it can't tell 2/4 from 4/4. Ask the user to "
            "count, then re-run with --cycle 2 or --cycle 4.")
    cycle = a.cycle or found

    if a.downbeat_pulse is not None:
        dp = a.downbeat_pulse
    elif cons and a.use_alternative and "alternative" in cons:
        dp = cons["alternative"]["downbeat_pulse"]
    elif cons:
        if "alternative" in cons and not a.grouping and cycle == found:
            alt = cons["alternative"]
            ask(f"beat 1 is ambiguous - pulse {cons['downbeat_pulse']} "
                f"({'+'.join(map(str, cons['grouping']))}) or pulse {alt['downbeat_pulse']} "
                f"({'+'.join(map(str, alt['grouping']))}). Ask which kick hit is '1', then "
                f"re-run with --use-alternative or --grouping a,b --downbeat-pulse K.")
        dp = cons["downbeat_pulse"] % cycle
    else:
        ask("no downbeat to anchor on - pass --downbeat-pulse K (the beat index the user "
            "counts as '1').")

    if a.grouping:
        grouping = [int(x) for x in a.grouping.split(",")]
    elif cons and cycle == found:
        grouping = (cons["alternative"]["grouping"] if a.use_alternative and "alternative" in cons
                    else cons["grouping"])
    elif cycle in CONVENTION:
        grouping = CONVENTION[cycle]
    else:
        ask(f"no grouping for a {cycle}-pulse bar - pass --grouping (e.g. 3,2 or 6,5).")
    if sum(grouping) != cycle:
        sys.exit(f"grouping {grouping} sums to {sum(grouping)}, not the cycle {cycle}")

    if a.pulse_unit is None and cycle % 2 == 1 and cycle not in (3, 9):
        ask(f"is the pulse an eighth ({cycle}/8) or a quarter ({cycle}/4)? It doubles Live's "
            f"tempo. At {F['pulse_bpm']} BPM "
            f"{'an eighth is likely' if F['pulse_bpm'] >= 140 else 'a quarter is likely'}. "
            f"Re-run with --pulse-unit 8 or 4.")
    unit = a.pulse_unit or 4

    downbeats = bt[dp::cycle]
    bar_bpm = []
    for d0, d1 in zip(downbeats[:-1], downbeats[1:]):
        inside = [b for b in bt if d0 <= b <= d1]
        gaps = sorted(y - x for x, y in zip(inside[:-1], inside[1:]))
        bar_bpm.append(round(60.0 / gaps[len(gaps) // 2], 2))
    srt = sorted(bar_bpm)
    med = srt[len(srt) // 2]
    pct = lambda q: srt[min(len(srt) - 1, int(q * len(srt)))]
    outliers = [i + 1 for i, v in enumerate(bar_bpm) if abs(v / med - 1) > 0.05]
    conf = (f"measured (sweep, {cons.get('confidence', '?')} {cons.get('margin', '?')}x)"
            if cons else None)
    who = a.decided_by                     # who chose what a flag set: agent or player
    prov = dict(F.get("provenance", {}))
    prov.update(
        cycle=who if a.cycle and a.cycle != found else conf,
        grouping=(who if a.grouping else f"{who} chose the alternative" if a.use_alternative
                  else f"measured ({cons.get('grouping_source', 'accents')})" if cons and cycle == found
                  else "convention"),
        downbeat=(who if a.downbeat_pulse is not None or a.use_alternative
                  else f"measured ({cons.get('anchor_band', 'kick')} band)" if cons else who),
        pulse_unit=who if a.pulse_unit else "default (quarter)")
    chosen = [k for k in ("cycle", "grouping", "downbeat", "pulse_unit")
              if prov[k].startswith(who)]
    F.pop("decided_by", None)
    if chosen:
        F["decided_by"] = dict(who=who, what=chosen)
    weak = cons is not None and cons.get("confidence") == "LOW" and who != "player"
    confirm = [k for k in ("cycle", "downbeat") if weak and prov[k].startswith("measured")]
    F.pop("to_confirm", None)
    if confirm:
        F["to_confirm"] = confirm
    F.update(provenance=prov, beats_per_bar=cycle, pulse_unit=unit, time_signature=f"{cycle}/{unit}",
             grouping=grouping, downbeat_pulse=dp, pickup_pulses=dp,
             downbeat_times=downbeats, num_bars=len(downbeats) - 1, bar_bpm=bar_bpm,
             # spread of the middle 90% of bars: one ritardando bar shouldn't make a
             # steady song look like it drifts - those are listed separately
             tempo_drift_pct=round((pct(0.95) - pct(0.05)) / med * 100, 1),
             tempo_outlier_bars=outliers,
             live_tempo=round(med * 4 / unit, 3), step="meter")
    json.dump(F, open(a.foundation, "w"), indent=1)
    print(f"{cycle}/{unit} as {'+'.join(map(str, grouping))}, {F['num_bars']} bars from "
          f"{downbeats[0]:.2f}s ({dp} pickup pulses); bar tempo {min(bar_bpm)}-{max(bar_bpm)} "
          f"(drift {F['tempo_drift_pct']}%); Live tempo {F['live_tempo']}")
    if F["tempo_drift_pct"] > 3:
        print("  drift > 3%: place notes through the beat grid, not one BPM")
    if outliers:
        print(f"  bars more than 5% off the median tempo: {outliers[:12]}"
              f"{' ...' if len(outliers) > 12 else ''} (ritardando, fermata or a tracking slip)")
    if chosen and who == "agent":
        print(f"  {', '.join(chosen)}: Claude's call, not the player's - say so, and ask the "
              f"player to count along before the chart goes to the band "
              f"(re-run with --decided-by player once they confirm)")
    if confirm:
        print(f"  {' and '.join(confirm)} measured at LOW confidence "
              f"({cons.get('anchor_band', '?')} band, {cons.get('margin', '?')}x): kept - ask "
              f"the player to count along (chart_questions.py asks first)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pulse")
    p.add_argument("audio")
    p.add_argument("--out", default="analysis/foundation.json")
    p.add_argument("--min-bpm", type=float, default=55.0, help="force a faster tempo octave")
    p.add_argument("--max-bpm", type=float, default=215.0, help="force a slower tempo octave")
    p.add_argument("--no-repair", action="store_true", help="keep madmom's grid as tracked")
    m = sub.add_parser("meter")
    m.add_argument("--foundation", default="analysis/foundation.json")
    m.add_argument("--meter", default="analysis/meter.json")
    m.add_argument("--cycle", type=int, help="pulses per bar, overriding the sweep")
    m.add_argument("--grouping", help="e.g. 6,5 or 2,2,3")
    m.add_argument("--downbeat-pulse", type=int, help="beat index of the first '1'")
    m.add_argument("--use-alternative", action="store_true",
                   help="take the sweep's alternative beat 1 / grouping")
    m.add_argument("--pulse-unit", type=int, choices=(4, 8))
    m.add_argument("--decided-by", choices=("agent", "player"), default="agent",
                   help="who chose what the flags set (default agent: Claude's call)")
    a = ap.parse_args()
    cmd_pulse(a) if a.cmd == "pulse" else cmd_meter(a)


if __name__ == "__main__":
    main()
