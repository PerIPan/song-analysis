#!/usr/bin/env python3
"""Test scripts/chart_seed.py on an invented song's analysis (temp folders, no audio).

Sections: an Intro before the first sung line, repeated labels numbered, an Interlude where
the voice stops four or more bars before the next section, an Outro after the last, a song
without lyrics as one section. Chords: lv-chordia's labels in lead-sheet form, every cell.
Lyrics at the cell where each line starts; unplaced lines listed as questions. It never
overwrites a data file, --out writes elsewhere, and the draft renders.
Run: python3 song-analysis/tests/test_chart_seed.py   (standard library only)
"""
import atexit, json, runpy, shutil, subprocess, sys, tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
TMP = Path(tempfile.mkdtemp(prefix='seed_'))
atexit.register(shutil.rmtree, TMP, True)
fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + ('' if cond else f'  [{info}]'))


def folder(lyrics=True):
    d = Path(tempfile.mkdtemp(dir=TMP)) / 'song'
    a = d / 'analysis'
    a.mkdir(parents=True)
    put = lambda n, o: (a / n).write_text(json.dumps(o))
    nb = 30
    put('foundation.json', dict(downbeat_times=[2.0 * i for i in range(nb + 1)], grouping=[2, 2],
                                time_signature='4/4', live_tempo=120.0, tempo_drift_pct=1.0,
                                key_top2=[['A minor', 0.6]], provenance=dict(cycle='measured', downbeat='measured')))
    loop = ['A:min', 'F:maj', 'C:maj', 'G:maj/3']
    put('chords_lv.json', dict(grouping=[2, 2], cells=[
        dict(bar=b, cell=1, t0=2.0 * (b - 1), chord=loop[(b - 1) % 4], status='agree')
        for b in range(1, nb + 1)]))             # second halves missing: holds filled in
    put('mode.json', dict(song=dict(tonic='A', mode='aeolian')))
    (d / 'source.json').write_text(json.dumps(dict(artist='Nobody', song='Paper Lanterns',
                                                   url='https://example.org/x', channel='Nobody')))
    if lyrics:
        put('sections.json', dict(sections=[
            dict(label='Verse', where=[5, 1], t=8.0), dict(label='Chorus', where=[9, 1], t=16.0),
            dict(label='Verse', where=[17, 1], t=32.0), dict(label='Chorus', where=[21, 1], t=40.0)]))
        lines = [dict(text='salt on the rail', section=0, start=8.0, end=10.0, matched=1.0, where=[5, 1]),
                 dict(text='lanterns of paper', section=1, start=16.0, end=17.5, matched=1.0, where=[9, 1]),
                 dict(text='a long way home', section=2, start=32.0, end=34.0, matched=0.2, where=[17, 1]),
                 dict(text='lanterns again', section=3, start=40.0, end=43.0, matched=1.0, where=[21, 1]),
                 dict(text='never heard', section=3, start=None, end=None, matched=0.0, where=None)]
        put('lyrics_aligned.json', dict(lines=lines, source='analysis/lyrics_mix.json',
                                        words_matched='9/12'))
        put('lyrics_mix.json', dict(words=[]))
    put('chord_proposal.json', dict(cells=[]))
    put('bass_per_cell.json', dict(cells=[]))
    return d


run = lambda *x: subprocess.run([sys.executable, str(SCRIPTS / 'chart_seed.py'), *map(str, x)],
                                capture_output=True, text=True)
d = folder()
r = run(d)
S = runpy.run_path(str(d / 'gen_v1.py'))['SONG'] if (d / 'gen_v1.py').exists() else {}
check('writes gen_v1.py and says it renders, no lyrics printed', r.returncode == 0
      and 'renders' in r.stdout and 'salt' not in r.stdout, r.stdout + r.stderr)
check('sections: Intro, numbered repeats, an Interlude in the gap, an Outro after',
      [s[:4] for s in S.get('sections', [])] == [
          ('Intro', 1, 4, 'intro'), ('Verse 1', 5, 8, 'verse'), ('Chorus 1', 9, 9, 'chorus'),
          ('Interlude', 10, 16, 'inst'), ('Verse 2', 17, 20, 'verse'), ('Chorus 2', 21, 22, 'chorus'),
          ('Outro', 23, 30, 'outro')], [s[:4] for s in S.get('sections', [])])
check('chords: lead-sheet labels, every cell, holds filled in',
      S['chords'][(1, 1)] == 'Am' and S['chords'][(1, 2)] == 'Am' and S['chords'][(4, 1)] == 'G/B'
      and len(S['chords']) == 60, (S['chords'].get((4, 1)), len(S['chords'])))
check('lyrics at the cell where each line starts; the words file named',
      S['lyrics'][(5, 1)] == ('salt on the rail', '') and len(S['lyrics']) == 4
      and S['words'] == 'lyrics_mix.json', (len(S['lyrics']), S.get('words')))
check('header facts and an unchecked provenance', dict(S['facts'])['Key'] == 'A aeolian'
      and 'not yet checked by a player' in S['provenance'], S['facts'])
q = S['notes'][0][1]
check('open questions: the unplaced line, the weak line, the form',
      'not placed' in q and 'barely heard' in q and 'The form' in q, q)
r = run(d)
check('never overwrites a data file', r.returncode == 1 and 'never overwritten' in r.stderr, r.stderr)
r = run(d, '--out', TMP / 'draft.py', '--title', 'Other')
check('--out writes elsewhere (title from the flag)', r.returncode == 0
      and runpy.run_path(str(TMP / 'draft.py'))['SONG']['title'] == 'Other', r.stdout + r.stderr)
d2 = folder(lyrics=False)
r = run(d2)
S2 = runpy.run_path(str(d2 / 'gen_v1.py'))['SONG'] if (d2 / 'gen_v1.py').exists() else {}
check('no lyrics: one section to split by ear, no lyrics key', r.returncode == 0
      and [s[:3] for s in S2.get('sections', [])] == [('Song', 1, 30)] and 'lyrics' not in S2,
      r.stdout + r.stderr)
sys.exit(1 if fails else 0)
