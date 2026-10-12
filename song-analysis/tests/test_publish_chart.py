#!/usr/bin/env python3
"""Test scripts/publish_chart.py with a stand-in Chrome (a script that writes a 2-page PDF)
on a synthetic song (temp folders, no audio).

Checked: without --yes nothing is written and the would-be names are printed; with --yes
the band-style HTML and PDF land in the folder, with the page count; OK replaces the WiP
copy; a broken player correction refuses; no destination asks for one; --rerender lists
the charts whose HTML would change and writes them only with --yes.
Run: python3 song-analysis/tests/test_publish_chart.py   (standard library only)
"""
import atexit, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'publish_chart.py'
TMP = Path(tempfile.mkdtemp(prefix='publish_'))
atexit.register(shutil.rmtree, TMP, True)
fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + ('' if cond else f'  [{info}]'))


chrome = TMP / 'chrome'
chrome.write_text('#!/bin/sh\nfor a in "$@"; do case "$a" in --print-to-pdf=*) '
                  'printf "%%PDF /Type /Pages /Type /Page x /Type /Page" > "${a#--print-to-pdf=}";; '
                  'esac; done\n')
chrome.chmod(0o755)
env = dict(os.environ, MWS_CHROME=str(chrome), HOME=str(TMP / 'home'))
songs = TMP / 'songs'
song = songs / 'one'
a = song / 'analysis'
a.mkdir(parents=True)
put = lambda n, o: (a / n).write_text(json.dumps(o))
keys = [(b, c) for b in (1, 2) for c in (1, 2)]
put('foundation.json', dict(downbeat_times=[0.0, 2.0, 4.0], grouping=[2, 2], pulse_unit=4))
put('chords_lv.json', dict(cells=[dict(bar=b, cell=c, t0=2.0 * (b - 1) + (c - 1), chord='A:min')
                                  for b, c in keys]))
put('chord_proposal.json', dict(cells=[dict(bar=b, cell=c, chord='Am') for b, c in keys]))
put('bass_per_cell.json', dict(cells=[dict(bar=b, cell=c, pc_seconds={}) for b, c in keys]))
gen = lambda corr: (song / 'gen_v1.py').write_text(
    "SONG = dict(title='Paper Lanterns', artist='Nobody', key_short='A minor',\n"
    "            chords={(1, 1): 'Am', (1, 2): 'Am', (2, 1): 'F', (2, 2): 'F'},\n"
    f"            corrections=[{corr}], sections=[('Verse', 1, 2, 'verse', '')])\n")
gen("(2, 1, 'chord', 'F', 'player', '2026-10-12')")
run = lambda *x: subprocess.run([sys.executable, str(SCRIPT), *map(str, x)], capture_output=True,
                                text=True, env=env)
band = TMP / 'band'

r = run(song / 'gen_v1.py', '--to', band, '--prefix', '3.3')
check('without --yes: nothing written, the names printed', r.returncode == 0
      and not band.exists() and '3.3 Nobody - Paper Lanterns - chords - A minor WiP.pdf' in r.stdout
      and '--yes' in r.stdout, r.stdout + r.stderr)
r = run(song / 'gen_v1.py', '--to', band, '--prefix', '3.3', '--yes')
names = sorted(p.name for p in band.iterdir()) if band.exists() else []
check('--yes: HTML and PDF named the band way, page count reported', r.returncode == 0
      and names == ['3.3 Nobody - Paper Lanterns - chords - A minor WiP.html',
                    '3.3 Nobody - Paper Lanterns - chords - A minor WiP.pdf']
      and '(2 pages)' in r.stdout and '1/1 hold' in r.stdout, (names, r.stdout + r.stderr))
r = run(song / 'gen_v1.py', '--to', band, '--prefix', '3.3', '--status', 'OK')
check('OK, dry: says it replaces the WiP copy', 'replacing 3.3 Nobody - Paper Lanterns - chords '
      '- A minor WiP.pdf' in r.stdout, r.stdout)
run(song / 'gen_v1.py', '--to', band, '--prefix', '3.3', '--status', 'OK', '--yes')
names = sorted(p.name for p in band.iterdir())
check('OK replaces the WiP copy', names == ['3.3 Nobody - Paper Lanterns - chords - A minor OK.html',
                                            '3.3 Nobody - Paper Lanterns - chords - A minor OK.pdf'], names)
r = run(song / 'gen_v1.py')
check('no --to and no publish_to: asks where, exit 2', r.returncode == 2 and 'publish_to' in r.stdout,
      r.stdout)
(TMP / 'home' / '.config' / 'music-workflow-skills').mkdir(parents=True)
(TMP / 'home' / '.config' / 'music-workflow-skills' / 'env.json').write_text(
    json.dumps({'publish_to': str(TMP / 'cfg' / '{artist}')}))
r = run(song / 'gen_v1.py', '--yes')
check('publish_to from env.json, {artist} filled in', r.returncode == 0
      and (TMP / 'cfg' / 'Nobody' / 'Nobody - Paper Lanterns - chords - A minor WiP.pdf').exists(),
      r.stdout + r.stderr)
gen("(2, 1, 'chord', 'G')")
r = run(song / 'gen_v1.py', '--to', TMP / 'never', '--yes')
check('a correction that no longer holds: refused, nothing written', r.returncode == 1
      and not (TMP / 'never').exists() and 'fix the chart first' in r.stdout, r.stdout + r.stderr)

bad = TMP / 'badchrome'
bad.write_text('#!/bin/sh\nexit 1\n')
bad.chmod(0o755)
before = sorted(p.name for p in band.iterdir())
gen("(2, 1, 'chord', 'F')")
r = subprocess.run([sys.executable, str(SCRIPT), str(song / 'gen_v1.py'), '--to', str(band),
                    '--prefix', '3.3', '--yes'], capture_output=True, text=True,
                   env=dict(env, MWS_CHROME=str(bad)))
check('Chrome fails: exit 1, nothing written, the OK copy kept', r.returncode == 1
      and sorted(p.name for p in band.iterdir()) == before and 'nothing written' in r.stdout,
      (r.stdout, sorted(p.name for p in band.iterdir())))
r = subprocess.run([sys.executable, str(SCRIPT), str(song / 'gen_v1.py'), '--to', str(TMP / 'ho'),
                    '--yes', '--html-only'], capture_output=True, text=True,
                   env=dict(env, MWS_CHROME=str(bad)))
check('--html-only: the page alone', r.returncode == 0 and sorted(
      p.suffix for p in (TMP / 'ho').iterdir()) == ['.html'], r.stdout + r.stderr)
r = run(song / 'gen_v1.py', '--to', TMP / 'tr', '--transpose', '-2', '--capo', '3')
check("transposed: named 'key of G minor, capo 3' the band's way",
      '3.3' not in r.stdout and 'Nobody - Paper Lanterns - chords - key of G minor, capo 3 WiP.pdf'
      in r.stdout, r.stdout + r.stderr)
sys.path.insert(0, str(SCRIPT.parent))
from publish_chart import base_name  # noqa: E402
check('names: a transposition with no readable key says the semitones; capo alone says capo',
      base_name(dict(artist='A', title='T'), 'WiP', None, dict(transpose=2, capo=0)) == 'A - T - chords - +2 semitones WiP'
      and base_name(dict(artist='A', title='T', key_short='E minor'), 'OK', None, dict(transpose=0, capo=3,
      sounding='E minor')) == 'A - T - chords - capo 3 OK')
r = run('--rerender', songs)
check('--rerender: a chart never rendered is listed as changed, not written', r.returncode == 0
      and 'CHANGED one' in r.stdout and not (song / 'Nobody - Paper Lanterns - Chords.html').exists(),
      r.stdout + r.stderr)
run('--rerender', songs, '--yes')
r = run('--rerender', songs)
check('...--yes writes it; then it is the same', 'same    one' in r.stdout
      and (song / 'Nobody - Paper Lanterns - Chords.html').exists(), r.stdout)
sys.exit(1 if fails else 0)
