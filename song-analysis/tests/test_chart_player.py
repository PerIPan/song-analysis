#!/usr/bin/env python3
"""Test scripts/chart_player.py on an invented song with a generated silent WAV.

The page: every cell carries its bar, cell and start time in page order; the audio link is
relative; the printed chart hides the controls. Then, when Chrome is installed, the page's
script runs headless with simulated clicks and keys: a click plays from a bar before the
cell, L loops the section, a note lands in the list and marks its cell.
Run: python3 song-analysis/tests/test_chart_player.py   (standard library only)
"""
import atexit, json, os, re, shutil, subprocess, sys, tempfile, wave
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from publish_chart import chrome  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='player_'))
atexit.register(shutil.rmtree, TMP, True)
fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + ('' if cond else f'  [{info}]'))


song = TMP / 'my song'                                  # a space in the path, on purpose
a = song / 'analysis'
a.mkdir(parents=True)
with wave.open(str(song / 'take one.wav'), 'wb') as w:
    w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
    w.writeframes(b'\0\0' * 8000 * 20)                  # 20 s of silence
keys = [(b, c) for b in range(1, 9) for c in (1, 2)]
put = lambda n, o: (a / n).write_text(json.dumps(o))
put('foundation.json', dict(downbeat_times=[1.0 + 2.0 * i for i in range(9)], grouping=[2, 2],
                            pulse_unit=4))
put('chords_lv.json', dict(cells=[dict(bar=b, cell=c, t0=1.0 + 2.0 * (b - 1) + (c - 1),
                                       chord='A:min') for b, c in keys]))
put('chord_proposal.json', dict(cells=[dict(bar=b, cell=c, chord='Am') for b, c in keys]))
put('bass_per_cell.json', dict(cells=[dict(bar=b, cell=c, pc_seconds={}) for b, c in keys]))
(song / 'gen_v1.py').write_text(
    "SONG = dict(title='Paper Lanterns', artist='Nobody', chords={(1, 1): 'Am', (3, 1): 'F'},\n"
    "            sections=[('Verse', 1, 4, 'verse', ''), ('Chorus', 5, 8, 'chorus', '')])\n")
r = subprocess.run([sys.executable, str(SCRIPTS / 'chart_player.py'), str(song / 'gen_v1.py')],
                   capture_output=True, text=True)
page = song / 'Nobody - Paper Lanterns - Player.html'
doc = page.read_text() if page.exists() else ''
check('written beside the chart, naming the audio', r.returncode == 0 and 'take one.wav' in r.stdout,
      r.stdout + r.stderr)
tags = re.findall(r'data-b="(\d+)" data-c="(\d+)" data-t="([\d.]+)"', doc)
check('every cell has its bar, cell and start, in page order', [(int(b), int(c)) for b, c, _ in tags]
      == keys and float(tags[2][2]) == 3.0, tags[:3])
check('a relative, encoded audio link', 'src="take%20one.wav"' in doc)
check('the controls do not print', '@media print{#pl,#notes{display:none}' in doc)
exe = chrome()
if not exe:
    print('skip  the page script (no Chrome)')
else:
    harness = """<script>setTimeout(() => {
      const A = document.getElementById('aud'), cells = [...document.querySelectorAll('.half[data-t]')];
      const r = {ready: document.body.dataset.player};
      cells[5].click();                                   // bar 3, second half
      r.seek = A.currentTime;
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'l'}));
      r.loop = cells.filter(c => c.classList.contains('loop')).map(c => c.dataset.b + '.' + c.dataset.c);
      document.getElementById('ntext').value = 'G, not Am';
      document.getElementById('nadd').click();
      r.notes = [...document.querySelectorAll('#nlist li')].map(li => li.textContent);
      r.noted = document.querySelectorAll('.half.noted').length;
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));
      cells[cells.length - 3].click();                  // the last section, then L: loop to the end
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'l'}));
      r.wrapped = [window.PLAYER.wrapTo(16.9), window.PLAYER.wrapTo(17.0)];   // the end: 17.0 s
      r.loop2 = cells.filter(c => c.classList.contains('loop')).length;
      document.body.dataset.result = JSON.stringify(r);
    }, 400);</script></body>"""
    test = song / 'harness.html'
    test.write_text(doc.replace('</body>', harness, 1))
    out = subprocess.run([exe, '--headless=new', '--disable-gpu', '--autoplay-policy=no-user-gesture-required',
                          '--virtual-time-budget=3000', '--dump-dom', test.as_uri()],
                         capture_output=True, text=True, timeout=120).stdout
    m = re.search(r'data-result="([^"]*)"', out)
    res = json.loads(m.group(1).replace('&quot;', '"')) if m else {}
    check('the script starts', res.get('ready') == 'ready', res or out[-300:])
    check('a click plays from one bar before the cell (bar 2 at 3.0 s)',
          abs(res.get('seek', -1) - 2.95) < 0.06, res.get('seek'))
    check('L loops the section the cell is in (Verse: bars 1-4)',
          res.get('loop') == [f'{b}.{c}' for b in range(1, 5) for c in (1, 2)], res.get('loop'))
    check('a loop that ends on the last cell wraps back (not out of the song)',
          res.get('wrapped') == [None, 9.0] and res.get('loop2') == 8, (res.get('wrapped'), res.get('loop2')))
    check('a note is listed against its cell and marks it',
          res.get('notes', [''])[0].startswith('bar 3.2 (0:06.0): G, not Am') and res.get('noted') == 1,
          (res.get('notes'), res.get('noted')))
sys.exit(1 if fails else 0)
