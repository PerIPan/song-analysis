#!/usr/bin/env python3
"""Test scripts/run.py's engine on stand-in steps (tiny python -c commands, temp folders,
no audio), and the real step table's commands built from the answers.

Checked: dependency order; the GPU lane runs one job at a time while the CPU lane runs
beside it; a second run does nothing; a changed answer re-runs its step, and a dependent
only when the step's output changed; a question (exit 2) stops what depends on it while the
rest carries on, and the answer reopens it; a failure blocks its dependents (exit 1); an
after-hook's 'redo'; --until; files made by hand are adopted; the meter flags, the bass entry
bar and the chart step come from the answers and the folder.
Run: python3 song-analysis/tests/test_run.py   (standard library only)
"""
import atexit, io, json, shutil, sys, tempfile, contextlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import run as R  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='run_'))
atexit.register(shutil.rmtree, TMP, True)
fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + ('' if cond else f'  [{info}]'))


def song():
    d = Path(tempfile.mkdtemp(dir=TMP))
    (d / 'take.wav').write_bytes(b'RIFF')
    (d / 'analysis').mkdir()
    c = R.Ctx(d, {'slug': 'take'}, {'py': sys.executable}, d / 'take.wav', log=lambda s: None)
    return c


def py(code):
    """A command: this Python running code (it may read sys.argv) in the song folder."""
    return [sys.executable, '-c', 'import json,sys,time,pathlib;P=pathlib.Path;' + code]


def step(name, needs=(), lane='cpu', code='', reads=(), writes=(), params=None, after=None,
         optional=()):
    return R.Step(name, 'py', lane, tuple(needs),
                  lambda c: [(c.a / r, ()) for r in reads],
                  lambda c: [(c.a / w, None) for w in writes],
                  lambda c: [py(code)], params=params or (lambda c: {}), after=after,
                  optional=tuple(optional))


def log_line(name, extra=''):
    """code that appends 'name start end' to analysis/order.txt, sleeping a little."""
    return (f"t0=time.time();time.sleep(0.3);open('analysis/order.txt','a').write("
            f"'{name} %f %f\\n'%(t0,time.time()));{extra}")


def order(c):
    rows = [l.split() for l in (c.a / 'order.txt').read_text().splitlines()]
    return [(n, float(a), float(b)) for n, a, b in rows]


# ---------------------------------------------------------------- order and lanes
c = song()
T = [step('a', code=log_line('a', "P('analysis/a.json').write_text(json.dumps(1))"),
          writes=['a.json']),
     step('g1', lane='gpu', code=log_line('g1', "P('analysis/g1.json').write_text('1')"),
          writes=['g1.json']),
     step('g2', lane='gpu', code=log_line('g2', "P('analysis/g2.json').write_text('1')"),
          writes=['g2.json']),
     step('b', needs=['a'], code=log_line('b', "P('analysis/b.json').write_text('1')"),
          reads=['a.json'], writes=['b.json'])]
table = {s.name: s for s in T}
code = R.run(c, table, list(table))
o = {n: (a, b) for n, a, b in order(c)}
check('all steps run, exit 0', code == 0 and set(o) == set(table), (code, o))
check('a dependent starts after what it needs', o['b'][0] >= o['a'][1], o)
g = sorted([o['g1'], o['g2']])
check('the GPU lane runs one job at a time', g[1][0] >= g[0][1] - 0.01, g)
check('the CPU lane runs beside it', o['a'][0] < max(o['g1'][1], o['g2'][1]), o)
(c.a / 'order.txt').unlink()
code = R.run(c, table, list(table))
check('a second run does nothing', code == 0 and not (c.a / 'order.txt').exists())
rs = json.loads((c.a / 'run.json').read_text())
check('state and timings kept', set(rs['steps']) == set(table)
      and len((c.a / 'timings.jsonl').read_text().splitlines()) == 4, rs.get('steps'))

# ---------------------------------------------------------------- answers and staleness
c = song()
A = step('a', code=log_line('a', "P('analysis/a.json').write_text(json.dumps(len(sys.argv)))"),
         writes=['a.json'], params=lambda c: {'x': c.answers.get('x')})
B = step('b', needs=['a'], code=log_line('b', "P('analysis/b.json').write_text('1')"),
         reads=['a.json'], writes=['b.json'])
table = {'a': A, 'b': B}
R.run(c, table, ['a', 'b'])
(c.a / 'order.txt').unlink()
c.answers['x'] = 5                     # a's answer changes; its output stays the same
st, why = R.state_of(c, A, {})
check('a changed answer makes its step stale, saying why', st == 'stale' and 'answers' in why,
      (st, why))
R.run(c, table, ['a', 'b'])
check("...it runs again; its dependent doesn't when the output is the same",
      [n for n, *_ in order(c)] == ['a'], order(c))
(c.a / 'order.txt').unlink()
(c.a / 'a.json').write_text('"edited"')
st, why = R.state_of(c, B, {})
check('an input that changed makes a dependent stale, naming the file',
      st == 'stale' and 'a.json' in why, (st, why))
(c.a / 'b.json').unlink()
check('missing outputs -> to do', R.state_of(c, B, {})[0] == 'todo')

c = song()                             # an upstream step re-runs: what follows waits for it
U = step('u', code=log_line('u', "P('analysis/u.json').write_text(json.dumps({'x': 1}))"),
         writes=['u.json'], params=lambda c: {'p': c.answers.get('p')})
W = step('w', needs=['u'], code=log_line('w', "d=json.loads(P('analysis/u.json').read_text());"
         "assert 'y' not in d;P('analysis/w.json').write_text('1')"), reads=['u.json'], writes=['w.json'])
table = {'u': U, 'w': W}
R.run(c, table, ['u', 'w'])
(c.a / 'order.txt').unlink()
c.answers['p'] = 1                     # u stale; its output will be the same; w is done
R.run(c, table, ['u', 'w'])
check('a done step waits for a stale upstream step, then is checked again (still done)',
      [n for n, *_ in order(c)] == ['u'], order(c))
(c.a / 'order.txt').unlink()
c.answers['p'] = 2
U2 = step('u', code=log_line('u', "P('analysis/u.json').write_text(json.dumps({'x': 2}))"),
          writes=['u.json'], params=lambda c: {'p': c.answers.get('p')})
R.run(c, {'u': U2, 'w': W}, ['u', 'w'])
o = order(c)
check('...and runs after it when the output changed', [n for n, *_ in o] == ['u', 'w']
      and o[1][1] >= o[0][2], o)

# ---------------------------------------------------------------- questions and failures
c = song()
Q = step('q', code="sys.stderr.write('NEEDS A DECISION: count along\\n');sys.exit(2)")
T = [Q, step('after_q', needs=['q'], code=log_line('after_q'), writes=['x.json']),
     step('free', code=log_line('free', "P('analysis/free.json').write_text('1')"),
          writes=['free.json'])]
table = {s.name: s for s in T}
logs = []
c.log = logs.append
code = R.run(c, table, list(table))
check('a question: exit 2, the rest carries on, its dependent waits',
      code == 2 and [n for n, *_ in order(c)] == ['free'], (code, order(c)))
check('...the question and the answer command are printed',
      any('QUESTION (q)' in l and 'count along' in l and 'run.py answer' in l for l in logs), logs)
check('...status shows it', R.state_of(c, Q, {})[0] == 'asks')
c.save()
with contextlib.redirect_stdout(io.StringIO()):
    R.cmd_answer(type('A', (), dict({k: None for k in R.ANSWERS}, song=str(c.song), cycle=4,
                                    decided_by=None, clear=None))())
c2 = R.context(str(c.song), need_audio=False)
check('an answer is kept (decided_by agent by default) and reopens the question',
      c2.answers == {'cycle': 4, 'decided_by': 'agent'}
      and R.state_of(c2, Q, {})[0] == 'stale', (c2.answers, R.state_of(c2, Q, {})))

c = song()
T = [step('bad', code="sys.exit(1)"), step('child', needs=['bad'], code=log_line('child')),
     step('ok', code=log_line('ok', "P('analysis/ok.json').write_text('1')"), writes=['ok.json'])]
table = {s.name: s for s in T}
code = R.run(c, table, list(table))
check('a failure: exit 1, its dependent blocked, the rest runs',
      code == 1 and [n for n, *_ in order(c)] == ['ok'], (code, order(c)))

c = song()
tries = []
def again(ctx, out):
    tries.append(1)
    if len(tries) == 1:
        ctx.answers['n'] = 2
        return 'redo'
R1 = step('r', code=log_line('r', "P('analysis/r.json').write_text('1')"), writes=['r.json'],
          params=lambda c: {'n': c.answers.get('n')}, after=again)
R.run(c, {'r': R1}, ['r'])
check("an after-hook's redo runs the step again with the new answer",
      len(order(c)) == 2 and c.answers == {'n': 2}, order(c))

c = song()
shutil.rmtree(c.a)                     # a fresh folder: no analysis/ yet
R.run(c, {'w': step('w', code="P('analysis/w.json').write_text('1')", writes=['w.json'])}, ['w'])
check('a fresh folder: analysis/ made before the first step', (c.a / 'w.json').exists())

# ---------------------------------------------------------------- review fixes (2026-10-12)
c = song()
X = step('x', code=log_line('x', "P('analysis/x.json').write_text('1')"), writes=['x.json'],
         params=lambda c: {'v': c.answers.get('v')})
R.run(c, {'x': X}, ['x'])
c.answers['v'] = 1
Xbad = step('x', code="sys.exit(1)", writes=['x.json'], params=lambda c: {'v': c.answers.get('v')})
R.run(c, {'x': Xbad}, ['x'])
check('a failed re-run is not adopted next time: its old outputs are stale',
      R.state_of(c, X, {}) == ('stale', 'its last run failed'), R.state_of(c, X, {}))
c = song()
Q2 = step('q2', code="sys.stderr.write('usage: oops\\n');sys.exit(2)")
code = R.run(c, {'q2': Q2}, ['q2'])
check('exit 2 without NEEDS A DECISION is a failure, not a question',
      code == 1 and R.state_of(c, Q2, {})[0] in ('todo', 'stale'), (code, R.state_of(c, Q2, {})))

c = song()
(c.a / 'foundation.json').write_text(json.dumps(dict(
    beat_times=[0, 1], pulse_bpm=87, downbeat_times=[0, 4], grouping=[2, 2], beats_per_bar=4,
    downbeat_pulse=2, pulse_unit=4, provenance=dict(pulse='measured (madmom DBN, 55-120 BPM)',
    cycle='user', grouping='convention', downbeat='user', pulse_unit='default (quarter)'))))
(c.a / 'bass_notes.json').write_text(json.dumps(dict(bass_entry_bar=25)))
R.adopt_answers(c)
check("adoption takes the choices the files record (legacy 'user' = Claude's call)",
      c.answers == {'max_bpm': 120.0, 'cycle': 4, 'downbeat_pulse': 2, 'decided_by': 'agent',
                    'bass_entry_bar': 25}, c.answers)
check('...so the meter re-runs with them', R.meter_flags(c) ==
      ['--cycle', '4', '--downbeat-pulse', '2', '--decided-by', 'agent'], R.meter_flags(c))
table = {s.name: s for s in R.steps()}
c.state['steps'] = {'pulse': dict(parts=dict(R.key_parts(c, table['pulse']), scripts={
    'foundation.py': 'old'}), adopted=True)}
check('an adopted step ignores a script edit', R.state_of(c, table['pulse'], {}) == ('done', ''),
      R.state_of(c, table['pulse'], {}))
c.answers.pop('bass_entry_bar')
c.set_answer('bass_entry_auto', {'bar': 5, 'grid': R.grid_fp(c)})
c.set_answer('keep_downbeat', R.grid_fp(c))
was = (R.entry_bar(c), R.kept_downbeat(c))
F = json.loads((c.a / 'foundation.json').read_text())
(c.a / 'foundation.json').write_text(json.dumps(dict(F, downbeat_times=[0.5, 4.5])))
check('a taken bass entry and --keep-downbeat hold only on the grid they were given on',
      was == (5, True) and (R.entry_bar(c), R.kept_downbeat(c)) == (None, False),
      (was, R.entry_bar(c), R.kept_downbeat(c)))
c.save()
rj = json.loads((c.a / 'run.json').read_text())
rj['answers']['language'] = 'el'                    # `run.py answer` from another shell
(c.a / 'run.json').write_text(json.dumps(rj))
c.set_answer('min_bpm', 70.0)
c.save()
check('an answer written meanwhile by another process survives this one saving',
      json.loads((c.a / 'run.json').read_text())['answers'].get('language') == 'el'
      and c.answers.get('min_bpm') == 70.0, json.loads((c.a / 'run.json').read_text())['answers'])
import subprocess, os
env = dict(os.environ, HOME=str(TMP / 'nohome'), MWS_FFMPEG='/bin/echo',
           MWS_ANALYSIS_PY=str(TMP / 'nope'))
cli = lambda *x: subprocess.run([sys.executable, str(SCRIPTS / 'run.py'), *x], capture_output=True,
                                text=True, env=env)
c = song()
c.save()
cli('answer', str(c.song), '--cycle', '4', '--decided-by', 'player')
r = cli('answer', str(c.song), '--downbeat-pulse', '0')
check("a meter answer without --decided-by is Claude's, even after a player's",
      json.loads((c.a / 'run.json').read_text())['answers'] == {'cycle': 4, 'decided_by': 'agent',
                                                                'downbeat_pulse': 0}, r.stdout)
r = cli('answer', str(c.song), '--pulse-unit', '6')
check('answers are checked like the scripts check them (--pulse-unit 4 or 8)',
      r.returncode == 2 and '4 (quarter) or 8' in r.stderr, r.stderr[-200:])
r = cli('run', str(c.song), '--until', 'pulse')
check('a missing interpreter stops the run before anything starts: exit 3',
      r.returncode == 3 and 'no interpreter for analysis' in r.stdout, r.stdout + r.stderr[-300:])

c = song()                             # a step skipped at the start is looked at again
G = step('g', code=log_line('g', "P('gen.txt').write_text('1')"), writes=['g.json'])
H = R.Step('h', 'py', 'cpu', (), lambda c: [], lambda c: [], lambda c: [py(log_line('h'))],
           skip=lambda c: None if (c.song / 'gen.txt').exists() else 'no gen.txt yet',
           optional=('g',))
R.run(c, {'g': G, 'h': H}, ['g', 'h'])
check('a step skipped for a file its upstream makes runs once that file is there',
      [n for n, *_ in order(c)] == ['g', 'h'], order(c))

# ---------------------------------------------------------------- until, adoption
table = {s.name: s for s in R.steps()}
check('--until meter: meter and what it needs, in order',
      R.closure(table, 'meter') == ['pulse', 'stems', 'sweep', 'meter'], R.closure(table, 'meter'))
c = song()
(c.a / 'foundation.json').write_text(json.dumps({'beat_times': [0, 1], 'pulse_bpm': 120}))
check('a file made by hand is adopted as done', R.state_of(c, table['pulse'], {}) ==
      ('done', 'adopted'), R.state_of(c, table['pulse'], {}))
check('meter is to do while foundation.json has no downbeats',
      R.state_of(c, table['meter'], {})[0] == 'todo')

# ---------------------------------------------------------------- the real commands
c = song()
c.env.update(analysis='/venv/py', demucs='/venv/dm', ffmpeg='ffmpeg', whisper='/venv/w',
             lvchordia='/venv/lv', demucs_device='mps')       # the same on any CI runner
c.answers.update(cycle=11, grouping='6,5', pulse_unit=8, use_alternative=True,
                 decided_by='player', bass_entry_bar=5, language='el')
m = table['meter'].argv(c)[0]
check('meter: the answers as foundation.py flags, --decided-by player',
      m[-9:] == ['--cycle', '11', '--grouping', '6,5', '--pulse-unit', '8', '--use-alternative',
                 '--decided-by', 'player'], m)
check('bass: --bass-entry-bar from the answers',
      table['bass'].argv(c)[0][-2:] == ['--bass-entry-bar', '5'], table['bass'].argv(c))
os.environ['MWS_DEMUCS_DEVICE'] = 'cpu'
check('$MWS_DEMUCS_DEVICE reaches the demucs command', R.device(R.load_env()) == ['-d', 'cpu'])
del os.environ['MWS_DEMUCS_DEVICE']
check('demucs -d: env.json demucs_device, else mps only on Apple Silicon',
      R.device({'demucs_device': 'cuda'}) == ['-d', 'cuda']
      and R.device({}) == (['-d', 'mps'] if sys.platform == 'darwin' and R.platform.machine() == 'arm64'
                           else []), R.device({}))
d = table['stems'].argv(c)
check('stems: decoded to <slug>.wav, then demucs htdemucs_ft on mps into stems/',
      d[0][0] == 'ffmpeg' and d[0][-1].endswith('take.wav') and d[1][:6] ==
      ['/venv/dm', '-m', 'demucs', '-n', 'htdemucs_ft', '-d'] and d[1][-2] == str(c.song / 'stems'), d)
check('lyrics: --language from the answers', table['lyrics'].argv(c)[0][-2:] == ['--language', 'el'])
check('no lyrics.txt: lyrics_mix and align skip', table['lyrics_mix'].skip(c) and table['align'].skip(c))
check('no gen_v<N>.py: the chart step waits for the seed, which runs',
      'seeds one' in (table['chart'].skip(c) or '') and table['seed'].skip(c) is None
      and 'seed' in table['chart'].optional)
for n in ('gen_v2.py', 'gen_v10.py'):
    (c.song / n).write_text('SONG = {}')
check('the chart step renders the newest gen_v<N>.py (10 after 2); the seed never runs then',
      table['chart'].argv(c)[0][-1] == 'gen_v10.py' and 'never overwritten'
      in (table['seed'].skip(c) or ''), table['chart'].argv(c))
c.answers['no_6s'] = True
check('no_6s: the 6-stem split and the strums skip', table['stems_6s'].skip(c)
      and table['strum'].skip(c))
sys.exit(1 if fails else 0)
