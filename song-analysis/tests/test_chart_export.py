#!/usr/bin/env python3
"""Test scripts/chart_form.py (folding the form) and scripts/chart_export.py (ChordPro, iReal
Pro, gig sheet, transposition) on invented songs (temp folders, no audio).

Folding: the period leaving the least to write, a head before the repeat, a tail after it,
near repeats only on 4+ bar patterns (and listed), held chords filled in, a section equal to
an earlier one. Export: iReal chord symbols, bars and repeats, a refused 11/8, ChordPro
environments with chords inline, transposition spelt from the new key (and capo shapes),
the gig sheet's repeats. Run: python3 song-analysis/tests/test_chart_export.py
"""
import atexit, json, shutil, subprocess, sys, tempfile, urllib.parse, re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from chart_form import bar_chords, fold, fold_bars  # noqa: E402
from chart_export import ireal_bar, ireal_chord  # noqa: E402
from chart_html import key_of, move, spelling, transposed  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='export_'))
atexit.register(shutil.rmtree, TMP, True)
fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + ('' if cond else f'  [{info}]'))


B = lambda *xs: [(x,) for x in xs]
h, p, k, t, d = fold_bars(B('Am', 'F', 'C', 'G') * 4)
check('a 4-bar loop x4', (h, p, k, t, d) == ([], B('Am', 'F', 'C', 'G'), 4, [], []), (h, p, k, t, d))
h, p, k, t, d = fold_bars(B('F#', 'F#', 'A', 'B') * 4 + B('B', 'B'))
check('the period leaving least to write, not the shortest that repeats (F# F# ...)',
      (p, k, t) == (B('F#', 'F#', 'A', 'B'), 4, B('B', 'B')), (p, k, t))
h, p, k, t, d = fold_bars(B('Cmaj7', 'Em', 'D', 'Am7') + B('G', 'Em', 'Em/D', 'Am7') * 3 + B('N.C.'))
check('a head before the repeat, a tail after', (h, p, k, t) == (
    B('Cmaj7', 'Em', 'D', 'Am7'), B('G', 'Em', 'Em/D', 'Am7'), 3, B('N.C.')), (h, p, k, t))
bars = B('Am', 'F', 'C', 'G') * 3 + B('Am', 'F', 'C', 'E')
check('an exact fold leaves a changed last cycle as the tail',
      fold_bars(bars)[2:4] == (3, B('Am', 'F', 'C', 'E')), fold_bars(bars))
h, p, k, t, d = fold_bars(bars, tolerance=1)
check('...a near fold lists the bar that differs', (p, k, d) == (B('Am', 'F', 'C', 'G'), 4, [(15, ('E',))]),
      (p, k, d))
check('near repeats never on 1- or 2-bar patterns', fold_bars(B('A', 'B', 'A', 'C'), 1)[2] == 1,
      fold_bars(B('A', 'B', 'A', 'C'), 1))
S = dict(chords={(1, 1): 'Am', (2, 1): 'F', (3, 2): 'G', (5, 1): 'Am', (6, 1): 'F', (7, 2): 'G'},
         sections=[('Verse 1', 1, 4, 'verse', ''), ('Verse 2', 5, 8, 'verse', '')])
bc = bar_chords(S, 2)
check('held chords fill empty cells across bars', bc[3] == ('F', 'G') and bc[4] == ('G', 'G'), bc)
F = fold(S, 2)
check('a section equal to an earlier one is marked', F[1].same_as == 'Verse 1' and F[0].same_as is None)

check('iReal chord symbols', [ireal_chord(c) for c in ('Am7', 'Cmaj7', 'F#m7b5', 'Bdim7', 'E7sus4',
      'Em/D', 'N.C.', 'Gsus2', 'Am')] == ['A-7', 'C^7', 'F#h7', 'Bo7', 'E7sus', 'E-/D', 'n', 'G2', 'A-'])
check('iReal bars: four cells, a held second half blank',
      [ireal_bar(('C', 'G')), ireal_bar(('C', 'C')), ireal_bar(('C',))] == ['C G ', 'C   ', 'C   '])
check('keys read', [key_of(x) for x in ('E minor', 'F♯', 'Bb major', 'C#m blues', 'nothing')]
      == [(4, True), (6, False), (10, False), (1, True), None])
check('spelling: sharps in sharp keys, flats otherwise', spelling((2, True)) [1] == 'Db'
      and spelling((4, True))[6] == 'F#' and spelling((5, False))[10] == 'Bb')
check('move: root and slash bass', move('Em/D', -2, spelling((2, True))) == 'Dm/C'
      and move('F#m7b5', 1, spelling((7, False))) == 'Gm7b5' and move('N.C.', 3, []) == 'N.C.')
T, note = transposed(dict(key_short='E minor', chords={(1, 1): 'Em', (1, 2): 'B7'}), -2, 0)
check('transpose -2 from E minor: D minor, spelt with flats where they belong',
      T['chords'] == {(1, 1): 'Dm', (1, 2): 'A7'} and note == 'in D minor (orig. E minor, -2)', (T, note))
T, note = transposed(dict(key_short='E minor', chords={(1, 1): 'Em'}), 0, 2)
check('capo 2: shapes two semitones down, said', T['chords'] == {(1, 1): 'Dm'} and 'capo 2' in note,
      (T, note))

# ---------------------------------------------------------------- the CLI on a song folder
song = TMP / 'song'
a = song / 'analysis'
a.mkdir(parents=True)
(a / 'foundation.json').write_text(json.dumps(dict(downbeat_times=[2.0 * i for i in range(13)],
                                                   grouping=[2, 2], pulse_unit=4, live_tempo=120)))
(a / 'words.json').write_text(json.dumps(dict(words=[dict(word=w, start=s) for w, s in (
    ('Salt', 8.1), ('on', 8.5), ('the', 8.9), ('rail', 9.3), ('again', 12.1))])))
chords = {(b, 1): c for b, c in zip(range(1, 13), ['Am', 'F', 'C', 'G'] * 3)}
(song / 'gen_v1.py').write_text(
    "SONG = dict(title='Paper Lanterns', artist='Nobody', key_short='A minor', words='words.json',\n"
    f"            chords={chords!r},\n"
    "            lyrics={(5, 1): ('Salt on the rail', ''), (7, 1): ('again', '')},\n"
    "            sections=[('Intro', 1, 4, 'intro', ''), ('Verse', 5, 8, 'verse', ''),\n"
    "                      ('Outro', 9, 12, 'outro', '')])\n")
run = lambda *x: subprocess.run([sys.executable, str(SCRIPTS / 'chart_export.py'), *map(str, x)],
                                capture_output=True, text=True)
r = run(song / 'gen_v1.py', '--out-dir', TMP / 'out')
files = sorted(p.name for p in (TMP / 'out').iterdir()) if (TMP / 'out').exists() else []
check('three files by default', r.returncode == 0 and files == [
    'Nobody - Paper Lanterns - A minor - Gig.html', 'Nobody - Paper Lanterns - A minor - iReal.html',
    'Nobody - Paper Lanterns - A minor.cho'], (files, r.stdout + r.stderr))
cho = (TMP / 'out' / 'Nobody - Paper Lanterns - A minor.cho').read_text() if files else ''
check('ChordPro: metadata, a verse environment, chords inline where sung, intro folded',
      '{key: Am}' in cho and '{tempo: 120}' in cho and '{start_of_verse: Verse}' in cho
      and '[Am]Salt on the rail' in cho and '{comment: Intro}' in cho
      and '[Am] | [F] | [C] | [G]' in cho, cho)
check('the lyrics are not printed', 'Salt' not in r.stdout)
page = (TMP / 'out' / 'Nobody - Paper Lanterns - A minor - iReal.html').read_text() if files else ''
url = urllib.parse.unquote(re.search(r'href="([^"]+)"', page).group(1)) if page else ''
check('iReal: title, key A-, 4/4, rehearsal marks, final bar', url.startswith(
      'irealbook://Paper Lanterns=Nobody=Pop=A-=n=T44[*iA-   |F   |C   |G   ][*V') and url.endswith('Z'), url)
gig = (TMP / 'out' / 'Nobody - Paper Lanterns - A minor - Gig.html').read_text() if files else ''
check('gig sheet: a section equal to an earlier one is "= Intro"', '= Intro' in gig, gig[:300])
(song / 'odd.py').write_text((song / 'gen_v1.py').read_text())
F11 = json.loads((a / 'foundation.json').read_text())
(a / 'foundation.json').write_text(json.dumps(dict(F11, grouping=[6, 5], pulse_unit=8)))
r = run(song / 'gen_v1.py', '--ireal', '--out-dir', TMP / 'odd')
check('11/8: no iReal export, said plainly', 'no 11/8 time signature' in r.stdout
      and not list((TMP / 'odd').glob('*iReal*')), r.stdout + r.stderr)
(a / 'foundation.json').write_text(json.dumps(F11))
r = run(song / 'gen_v1.py', '--chordpro', '--transpose', '2', '--out-dir', TMP / 'tr')
cho = next((TMP / 'tr').glob('*.cho')).read_text() if (TMP / 'tr').exists() else ''
check('--transpose 2: B minor chords, named and said in the file', '[Bm]Salt' in cho
      and 'in B minor (orig. A minor, +2)' in cho and '(in B minor)' in next((TMP / 'tr').glob('*.cho')).name,
      cho[:300])
sys.exit(1 if fails else 0)
