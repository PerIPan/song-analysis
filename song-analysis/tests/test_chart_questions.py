#!/usr/bin/env python3
"""Test chart_questions.py on a synthetic chart (no audio).

A cell whose reader names another root is asked about, with the chart's chord first among
the options, what lv-chordia, the triads and the bass heard, and the parallel section's
chord - counted from the end when the parallel section is longer (a turnaround); verified
cells and stop bars are not asked; with nothing open it says so. A bass-less cell charted
unlike every parallel section is asked about; a meter Claude chose is question #1; each
cell question gives its time; the CLI keeps the round and scores it once the chart changes.
Run: python3 song-analysis/tests/test_chart_questions.py   (standard library only)
"""
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from chart_questions import questions  # noqa: E402

fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))


d = Path(tempfile.mkdtemp())
a = d / 'analysis'
a.mkdir()
chords = {(b, c): 'Am' for b in range(1, 15) for c in (1, 2)}
chords[(4, 2)] = chords[(14, 2)] = 'F#m7'                  # the turnarounds
lv = [dict(bar=b, cell=c, chord='A:min', coverage=1) for b, c in chords]
for x in lv:
    if (x['bar'], x['cell']) in ((4, 2), (2, 1), (3, 1), (12, 1)):
        x['chord'] = 'E:min/2' if x['bar'] == 4 else 'C:maj'
    if (x['bar'], x['cell']) == (14, 2):
        x['chord'] = 'F#:min7'                             # chorus 2's turnaround: agreed
(a / 'chords_lv.json').write_text(json.dumps({'cells': lv}))
(a / 'chord_proposal.json').write_text(json.dumps({'cells': [
    dict(bar=b, cell=c, chord='F#m' if (b, c) == (14, 2) else 'Am') for b, c in chords]}))
(a / 'bass_per_cell.json').write_text(json.dumps({'cells': [
    dict(bar=b, cell=c, pc_seconds={'F#': 0.4} if (b, c) in ((4, 2), (14, 2)) else {'A': 0.4})
    for b, c in chords]}))
(a / 'band_level.json').write_text(json.dumps({'cells': [[b, c, 0.05 if b == 12 else 1.0]
                                                         for b, c in chords]}))
S = dict(chords=chords, verified=[(3, 1)],
         sections=[('Chorus 1', 1, 4, 'chorus', ''), ('Verse', 5, 8, 'verse', ''),
                   ('Chorus 2', 9, 14, 'chorus', '')])
Q = questions(S, a)
got = {(q['bar'], q['cell']): q for q in Q}
check('asked: the cells a reader disputes; not the verified one, not the stop bar',
      sorted(got) == [(2, 1), (4, 2)], sorted(got))
q = got.get((4, 2), {})
check("a question carries the chart's chord first, the readers' and the bass",
      q.get('options', [None])[0] == 'F#m7' and 'Em/F#' in q.get('options', []) and
      q.get('bass') == 'F#', q)
check('the parallel section counted from its end when it is longer (turnaround 4 <-> 14)',
      q.get('parallel') == ['F#m7'], q.get('parallel'))
S['verified'] += [(2, 1), (4, 2)]
check('nothing open: no questions', questions(S, a) == [])
from chart_questions import weak_lines  # noqa: E402
(a / 'lyrics_aligned.json').write_text(json.dumps({'lines': [
    dict(text='heard every word here', matched=1.0, where=[1, 1]),
    dict(text='slow jazz is playing', matched=0.25, where=[3, 2])]}))
W = weak_lines(a)
check('a line Whisper heard under half of is a placement question (first words, where)',
      W == [dict(where=[3, 2], matched=0.25, start='slow jazz is')], W)
from chart_questions import pattern_breaks  # noqa: E402
loop = ['F#', 'F#', 'A', 'B']
ch = {(b, c): loop[(b - 1) % 4] for b in range(1, 25) for c in (1, 2)}
ch[(8, 1)] = 'A'                                           # B bar charted A: readers agreed
ch[(22, 1)] = ch[(23, 1)] = ch[(24, 1)] = 'E'              # the closing cycle: a turnaround
S2 = dict(chords=ch, sections=[('Verse', 1, 24, 'verse', '')])
P = [(x['bar'], x['cell'], x['chart'], x['usual']) for x in pattern_breaks(S2)]
check("a cell breaking its section's repeating pattern is asked about; a turnaround that "
      "closes the section is not", P == [(8, 1, 'A', 'B')], P)
S2['verified'] = [(8, 1)]
check('a verified break is not asked again', pattern_breaks(S2) == [])
from chart_questions import meter_question, parallel_breaks, score_round, timer  # noqa: E402
ch3 = {(b, c): 'G' for b in range(1, 9) for c in (1, 2)}
ch3[(3, 1)] = 'Am'                         # chorus 2 bar 7 plays G here; no bass under it
S3 = dict(chords=ch3, sections=[('Chorus 1', 1, 4, 'chorus', ''), ('Chorus 2', 5, 8, 'chorus', '')])
a3 = d / 'analysis3'
a3.mkdir()
(a3 / 'bass_per_cell.json').write_text(json.dumps({'cells': [
    dict(bar=b, cell=c, pc_seconds={} if (b, c) in ((3, 1), (7, 1)) else {'G': 0.5}) for b, c in ch3]}))
P3 = [(x['bar'], x['cell'], x['chart'], x['parallel']) for x in parallel_breaks(S3, a3)]
check('a bass-less cell charted unlike its parallel section is asked (its parallel too, '
      'which has no bass either)', P3 == [(3, 1, 'Am', 'G'), (7, 1, 'G', 'Am')], P3)
(a3 / 'bass_per_cell.json').write_text(json.dumps({'cells': [
    dict(bar=b, cell=c, pc_seconds={} if (b, c) == (3, 1) else {'G': 0.5}) for b, c in ch3]}))
P3 = [(x['bar'], x['cell']) for x in parallel_breaks(S3, a3)]
check('...a cell with bass is left to the readers', P3 == [(3, 1)], P3)
check('...a verified cell is not asked', parallel_breaks(dict(S3, verified=[(3, 1)]), a3) == [])
F3 = dict(downbeat_times=[1.0 + 2 * i for i in range(9)], grouping=[2, 2], time_signature='4/4',
          decided_by=dict(who='agent', what=['cycle', 'downbeat']))
mq = meter_question(F3) or ''
check("a meter Claude chose: asked first, with beat 1's time", "Claude's call" in mq
      and '0:01' in mq and '--decided-by player' in mq, mq)
check("...the player's or a measured meter: not asked",
      meter_question(dict(F3, decided_by=dict(who='player', what=['cycle']))) is None
      and meter_question({k: v for k, v in F3.items() if k != 'decided_by'}) is None)
when = timer(F3, S3)
check('a cell question gives its time in the recording', when((3, 2)) == '0:06.0-0:07.0'
      and when((9, 1)) == '', (when((3, 2)), when((9, 1))))
prev = dict(listed=[[3, 1, 'parallel'], [5, 2, 'reader']], verified=[],
            chords={f'{b}.{c}': v for (b, c), v in ch3.items()})
check('no change since the round: nothing scored', score_round(prev, S3) is None)
ch4 = {**ch3, (3, 1): 'G', (6, 1): 'Em'}
r = score_round(prev, dict(S3, chords=ch4, verified=[(5, 2)]))
check('the round scored: listed cells changed / kept, fixes not on the list',
      r == dict(listed=2, changed=['3.1 Am -> G'], kept=1, unlisted_fixes=['6.1 G -> Em']), r)

song = d / 'song'
(song / 'analysis').mkdir(parents=True)
for n in ('chords_lv.json', 'chord_proposal.json', 'bass_per_cell.json', 'band_level.json'):
    (song / 'analysis' / n).write_text((a / n).read_text())
(song / 'analysis' / 'foundation.json').write_text(json.dumps(dict(
    F3, downbeat_times=[2.0 * i for i in range(15)])))
gen = lambda c: (song / 'gen_v1.py').write_text(f"SONG = dict(chords={c!r}, verified=[(3, 1)], "
                                                f"sections={S['sections'][:3]!r})\n")
gen(chords)
run = lambda *x: subprocess.run([sys.executable, str(SCRIPTS / 'chart_questions.py'), 'gen_v1.py', *x],
                                capture_output=True, text=True, cwd=song)
r1 = run()
lines = r1.stdout.splitlines()
check('CLI: the meter question first, then cell questions with their times',
      lines and lines[0].startswith('meter check') and any('bar 2 (first half, Chorus 1) at 0:02.0-0:03.0'
                                                         in x for x in lines), r1.stdout + r1.stderr)
check('CLI: the round kept', (song / 'analysis' / 'questions_round.json').exists())
gen({**chords, (2, 1): 'C', (9, 1): 'Dm'})
r2 = run()
log = song / 'analysis' / 'questions_log.jsonl'
check('CLI: the next run scores it into the log', "last round's list" in r2.stdout
      and log.exists() and json.loads(log.read_text().splitlines()[-1])['changed'] == ['2.1 Am -> C']
      and json.loads(log.read_text().splitlines()[-1])['unlisted_fixes'] == ['9.1 Am -> Dm'], r2.stdout)
r3 = run('--no-log')
check('CLI --no-log: no score, log untouched', "last round" not in r3.stdout
      and len(log.read_text().splitlines()) == 1, r3.stdout)
sys.exit(1 if fails else 0)
