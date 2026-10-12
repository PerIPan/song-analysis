#!/usr/bin/env python3
"""Run song-analysis Phases 1-8 on one song folder, skipping what is done.

Every step runs with its interpreter, in order, on two lanes, and stops at the first question.

Why: by hand a song took ~20 commands across six interpreters, values copied between them
(the bass entry bar, the meter flags), polling for stems, and resuming after a usage limit
from notes and file times. Here each step declares what it reads and writes; a step runs
again only when one of its inputs, its answers or its script changed. The GPU lane (demucs,
Whisper) runs one job at a time beside the CPU lane (madmom, lv-chordia, the rest), so the
stems and the pulse start together. A step that asks (foundation.py meter's NEEDS A
DECISION, bass_notes' DOWNBEAT CHECK) stops everything that depends on its answer - the
rest carries on - and the question is printed with the `run.py answer` that settles it:
the answer flags are the scripts' own (--cycle, --grouping, --downbeat-pulse,
--use-alternative, --pulse-unit, --min-bpm, --max-bpm, --bass-entry-bar, --language).
Every step's summary lines are printed as the script wrote them; full logs go to
analysis/logs/, times to analysis/timings.jsonl, state and answers to analysis/run.json.

The audio is the song folder's one recording (source.json's file when Phase 0 fetched it;
--audio once otherwise). Lyrics: lyrics.txt in the folder (Phases 5b and 6 skip without
it). The stems go to stems/htdemucs_ft/<slug>/ (and htdemucs_6s, unless --no-6s); a
folder analysed by hand is picked up as it is - steps whose outputs exist are adopted as
done, and validate_artifacts.py still checks them against the grid. The chart step renders
the newest gen_v<N>.py and lists the player's questions; without one it says to write it.

Interpreters: $MWS_<ROLE>_PY, else ~/.config/music-workflow-skills/env.json, roles
analysis, demucs, lvchordia, whisper, adtof (the venvs of references/environment-setup.md;
`run.py doctor` checks them, ffmpeg and the model caches, and prints a template).

Usage (python3, standard library only):
    run.py status <song>                     # each step: done / stale (why) / to do / waits
    run.py run <song> [--until STEP] [--redo STEP ...] [--audio FILE]
    run.py answer <song> [--cycle 4 --grouping 2,2 --decided-by player ...] [--clear KEY]
    run.py doctor
Steps: pulse, stems, stems_6s, sweep, meter, bass, lyrics, lyrics_mix, align, mode,
chords, chords_lv, tab, drums, strum, activity, validate, chart.
Exit: 0 done, 1 a step failed, 2 stopped at a question, 3 environment (an interpreter,
ffmpeg or the audio missing).
"""
from __future__ import annotations

import argparse, hashlib, json, os, re, shutil, subprocess, sys, time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ENV_FILE = Path.home() / '.config' / 'music-workflow-skills' / 'env.json'
ROLES = ('analysis', 'demucs', 'lvchordia', 'whisper', 'adtof')
AUDIO = ('.wav', '.mp3', '.m4a', '.flac', '.aiff', '.aif')
LANES = {'gpu': 1, 'cpu': 2}                  # jobs at once per lane (16 GB: one GPU model)
PULSE = ('beat_times', 'pulse_bpm')           # foundation.json fields each phase reads
METER = ('downbeat_times', 'grouping', 'beats_per_bar', 'pulse_unit')
NOISE = re.compile(r'\w+Warning:|warnings\.warn|^\s*warn\(|%\||it/s\]|^\s*$')  # libraries' chatter
ANSWERS = {  # answer -> (type, help); the meter / pulse / bass ones are the scripts' flags
    'cycle': (int, 'pulses per bar (foundation.py meter)'),
    'grouping': (str, 'e.g. 6,5 (foundation.py meter)'),
    'downbeat_pulse': (int, "beat index of the first '1' (foundation.py meter)"),
    'use_alternative': (bool, "take the sweep's alternative beat 1 (foundation.py meter)"),
    'pulse_unit': (int, '4 or 8 (foundation.py meter)'),
    'decided_by': (str, 'agent (Claude chose) or player (the player counted / confirmed)'),
    'min_bpm': (float, 'force a faster tempo octave (foundation.py pulse)'),
    'max_bpm': (float, 'force a slower tempo octave (foundation.py pulse)'),
    'bass_entry_bar': (int, 'bass notes before this bar are bleed (bass_notes.py)'),
    'keep_downbeat': (bool, 'the harmony is pushed on purpose: keep beat 1 (DOWNBEAT CHECK)'),
    'language': (str, 'force the Whisper language, e.g. en, el'),
    'no_6s': (bool, 'skip the htdemucs_6s split (a chart only, no guitar/piano parts)'),
    'performance': (bool, "Phase 4b: the drummer's hits and the guitar's strums"),
}


# ------------------------------------------------------------------ context

@dataclass
class Ctx:
    song: Path
    state: dict
    env: dict
    audio: Path | None = None
    log: Callable[[str], None] = print

    @property
    def a(self) -> Path:
        return self.song / 'analysis'

    @property
    def answers(self) -> dict:
        return self.state.setdefault('answers', {})

    @property
    def slug(self) -> str:
        return self.state['slug']

    def stem(self, name: str, model: str = 'htdemucs_ft') -> Path:
        return self.song / 'stems' / model / self.slug / f'{name}.wav'

    def save(self) -> None:
        self.a.mkdir(exist_ok=True)
        (self.a / 'run.json').write_text(json.dumps(self.state, indent=1))


def load_env() -> dict:
    conf = {}
    if ENV_FILE.exists():
        try:
            conf = json.loads(ENV_FILE.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f'run.py: {ENV_FILE} is not JSON ({e})')
    out = {}
    for role in ROLES:
        p = os.environ.get(f'MWS_{role.upper()}_PY') or conf.get(role)
        out[role] = str(Path(p).expanduser()) if p else None
    out['py'] = sys.executable
    out['ffmpeg'] = os.environ.get('MWS_FFMPEG') or conf.get('ffmpeg') or shutil.which('ffmpeg')
    return out


def find_audio(song: Path, state: dict, given: str | None) -> Path | None:
    if given:
        state['audio'] = given
    if state.get('audio'):
        return song / state['audio']
    src = song / 'source.json'
    if src.exists():
        f = json.loads(src.read_text()).get('file')
        if f and (song / f).exists():
            state['audio'] = f
            return song / f
    cands = [p for p in song.iterdir() if p.suffix.lower() in AUDIO and not p.name.startswith('.')]
    if len(cands) == 1:
        state['audio'] = cands[0].name
        return cands[0]
    return None


def find_slug(song: Path, audio: Path) -> str:
    """An existing htdemucs_ft folder with a bass stem (a song analysed by hand), else the
    audio's name without spaces or punctuation."""
    ft = song / 'stems' / 'htdemucs_ft'
    have = sorted(p.name for p in ft.glob('*') if (p / 'bass.wav').exists()) if ft.is_dir() else []
    return have[0] if have else re.sub(r'[^A-Za-z0-9]+', '', audio.stem) or 'song'


# ------------------------------------------------------------------ fingerprints

def fingerprint(path: Path, fields: tuple = ()) -> str | None:
    """What a step read from a file: the listed JSON fields, else the whole file (content for
    small files, size and time for audio). None when it is missing."""
    if not path.exists():
        return None
    if fields:
        try:
            d = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return hashlib.sha1(json.dumps([d.get(k) for k in fields], sort_keys=True)
                            .encode()).hexdigest()[:16]
    st = path.stat()
    if st.st_size < 4_000_000:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:16]
    return f'{st.st_size}-{st.st_mtime_ns}'


def has(path: Path, field_: str | None = None) -> bool:
    if not path.exists():
        return False
    if field_ is None:
        return True
    try:
        return field_ in json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


# ------------------------------------------------------------------ steps

@dataclass
class Step:
    name: str
    role: str                                   # interpreter role, or 'py' (this Python)
    lane: str                                   # 'gpu' or 'cpu'
    needs: tuple                                # steps that must be done first
    reads: Callable                             # ctx -> [(path, fields)]
    writes: Callable                            # ctx -> [(path, field or None)]
    argv: Callable                              # ctx -> [[...]] commands, run in order
    params: Callable = lambda c: {}             # ctx -> the answers it depends on
    skip: Callable = lambda c: None             # ctx -> why it doesn't run, or None
    scripts: tuple = ()                         # repo scripts it runs (their changes count)
    after: Callable | None = None               # (ctx, stdout) -> None | ('ask', q) | 'redo'
    optional: tuple = ()                        # steps waited for only if they run


def S(name: str) -> str:
    return str(HERE / name)


def meter_flags(c: Ctx) -> list:
    A, out = c.answers, []
    for k in ('cycle', 'grouping', 'downbeat_pulse', 'pulse_unit'):
        if A.get(k) is not None:
            out += [f"--{k.replace('_', '-')}", str(A[k])]
    if A.get('use_alternative'):
        out.append('--use-alternative')
    return out + ['--decided-by', A.get('decided_by') or 'agent']


def bass_after(c: Ctx, out: str):
    """DOWNBEAT CHECK is a question unless kept on purpose; a suggested later bass entry is
    taken (recorded in the answers) and the step runs again with it."""
    if 'DOWNBEAT CHECK' in out and not c.answers.get('keep_downbeat'):
        line = next(l for l in out.splitlines() if 'DOWNBEAT CHECK' in l)
        k = re.search(r'--downbeat-pulse (\d+)', line)
        return ('ask', f'{line}\n  answer: run.py answer "{c.song}" --downbeat-pulse '
                       f'{k.group(1) if k else "K"} [--cycle/--grouping as before] '
                       f'(--decided-by player if the player confirmed), or --keep-downbeat '
                       f'if the harmony is pushed on purpose')
    B = json.loads((c.a / 'bass_notes.json').read_text())
    hint = B.get('suggested_entry_bar', 1)
    if hint > B.get('bass_entry_bar', 1) and 'bass_entry_bar' not in c.answers:
        c.answers['bass_entry_bar'] = hint
        c.log(f'  -> bass enters at bar {hint}: running again with --bass-entry-bar {hint} '
              f'(run.py answer --bass-entry-bar N to change)')
        return 'redo'
    return None


def chart_file(c: Ctx) -> Path | None:
    gens = sorted(c.song.glob('gen_v*.py'), key=lambda p: int(re.sub(r'\D', '', p.stem) or 0))
    return gens[-1] if gens else None


def steps() -> list[Step]:
    A = lambda c, n: c.a / n
    lyr = lambda c: c.song / 'lyrics.txt'
    found = lambda fields: (lambda c: [(A(c, 'foundation.json'), fields)])
    ff = lambda c, *x: [(A(c, 'foundation.json'), METER), *[(p, ()) for p in x]]
    six = lambda c: c.answers.get('no_6s')
    return [
        Step('pulse', 'analysis', 'cpu', (),
             lambda c: [(c.audio, ())], lambda c: [(A(c, 'foundation.json'), 'beat_times')],
             lambda c: [[c.env['analysis'], S('foundation.py'), 'pulse', str(c.audio), '--out',
                         'analysis/foundation.json']
                        + sum(([f'--{k.replace("_", "-")}', str(c.answers[k])]
                               for k in ('min_bpm', 'max_bpm') if c.answers.get(k)), [])],
             params=lambda c: {k: c.answers.get(k) for k in ('min_bpm', 'max_bpm')},
             scripts=('foundation.py',)),
        Step('stems', 'demucs', 'gpu', (),
             lambda c: [(c.audio, ())],
             lambda c: [(c.stem(s), None) for s in ('bass', 'drums', 'vocals', 'other')],
             lambda c: demucs(c, 'htdemucs_ft')),
        Step('stems_6s', 'demucs', 'gpu', ('stems',),
             lambda c: [(c.audio, ())],
             lambda c: [(c.stem(s, 'htdemucs_6s'), None) for s in ('guitar', 'piano')],
             lambda c: demucs(c, 'htdemucs_6s'),
             skip=lambda c: 'no_6s answered (a chart only)' if six(c) else None),
        Step('sweep', 'analysis', 'cpu', ('pulse', 'stems'),
             lambda c: [(c.audio, ()), (A(c, 'foundation.json'), PULSE)]
                       + [(c.stem(s), ()) for s in ('drums', 'bass', 'other')],
             lambda c: [(A(c, 'meter.json'), None)],
             lambda c: [[c.env['analysis'], S('detect_meter.py'), str(c.audio),
                         '--drums', str(c.stem('drums')), '--bass', str(c.stem('bass')),
                         '--other', str(c.stem('other')), '--foundation',
                         'analysis/foundation.json', '--json', 'analysis/meter.json']],
             scripts=('detect_meter.py',)),
        Step('meter', 'analysis', 'cpu', ('sweep',),
             lambda c: [(A(c, 'foundation.json'), PULSE), (A(c, 'meter.json'), ())],
             lambda c: [(A(c, 'foundation.json'), 'downbeat_times')],
             lambda c: [[c.env['analysis'], S('foundation.py'), 'meter', '--foundation',
                         'analysis/foundation.json', '--meter', 'analysis/meter.json',
                         *meter_flags(c)]],
             params=lambda c: {'flags': meter_flags(c)}, scripts=('foundation.py',)),
        Step('bass', 'analysis', 'cpu', ('meter', 'stems'),
             lambda c: ff(c, c.stem('bass')),
             lambda c: [(A(c, n), None) for n in ('bass_notes.json', 'bass_per_cell.json')],
             lambda c: [[c.env['analysis'], S('bass_notes.py'), str(c.stem('bass')),
                         '--foundation', 'analysis/foundation.json', '--outdir', 'analysis']
                        + (['--bass-entry-bar', str(c.answers['bass_entry_bar'])]
                           if c.answers.get('bass_entry_bar') else [])],
             params=lambda c: {k: c.answers.get(k) for k in ('bass_entry_bar', 'keep_downbeat')},
             scripts=('bass_notes.py',), after=bass_after),
        Step('lyrics', 'whisper', 'gpu', ('stems',),
             lambda c: [(c.stem('vocals'), ())], lambda c: [(A(c, 'lyrics.json'), None)],
             lambda c: [[c.env['whisper'], S('whisper_gated.py'), str(c.stem('vocals')),
                         '--out', 'analysis/lyrics.json'] + lang(c)],
             params=lambda c: {'language': c.answers.get('language')},
             scripts=('whisper_gated.py',)),
        Step('lyrics_mix', 'whisper', 'gpu', ('stems',),
             lambda c: [(c.stem('vocals'), ()), (c.audio, ())],
             lambda c: [(A(c, 'lyrics_mix.json'), None)],
             lambda c: [[c.env['whisper'], S('whisper_gated.py'), str(c.stem('vocals')),
                         '--mix', str(c.audio), '--out', 'analysis/lyrics_mix.json'] + lang(c)],
             params=lambda c: {'language': c.answers.get('language')},
             skip=lambda c: None if lyr(c).exists() else 'no lyrics.txt',
             scripts=('whisper_gated.py',)),
        Step('align', 'py', 'cpu', ('lyrics', 'meter'),
             lambda c: ff(c, lyr(c), A(c, 'lyrics.json'), A(c, 'lyrics_mix.json')),
             lambda c: [(A(c, n), None) for n in ('lyrics_aligned.json', 'sections.json')],
             lambda c: [[c.env['py'], S('align_lyrics.py'), '--lyrics', 'lyrics.txt',
                         '--words', 'analysis/lyrics.json']
                        + (['--words', 'analysis/lyrics_mix.json']
                           if A(c, 'lyrics_mix.json').exists() else [])
                        + ['--foundation', 'analysis/foundation.json']],
             skip=lambda c: None if lyr(c).exists() else 'no lyrics.txt',
             scripts=('align_lyrics.py',), optional=('lyrics_mix',)),
        Step('mode', 'analysis', 'cpu', ('bass', 'stems'),
             lambda c: ff(c, c.stem('other'), A(c, 'bass_per_cell.json'), A(c, 'sections.json')),
             lambda c: [(A(c, 'mode.json'), None)],
             lambda c: [[c.env['analysis'], S('mode_test.py'), '--other', str(c.stem('other')),
                         '--foundation', 'analysis/foundation.json', '--bass-cells',
                         'analysis/bass_per_cell.json']
                        + (['--sections', 'analysis/sections.json']
                           if A(c, 'sections.json').exists() else [])
                        + ['--out', 'analysis/mode.json']],
             scripts=('mode_test.py',), optional=('align',)),
        Step('chords', 'analysis', 'cpu', ('bass', 'stems'),
             lambda c: ff(c, c.stem('other'), c.stem('bass'))
                       + [(A(c, 'bass_notes.json'), ('bass_entry_bar', 'suggested_entry_bar'))],
             lambda c: [(A(c, 'chord_proposal.json'), None)],
             lambda c: [[c.env['analysis'], S('chord_proposal.py'), '--other',
                         str(c.stem('other')), '--bass', str(c.stem('bass')), '--foundation',
                         'analysis/foundation.json', '--out', 'analysis/chord_proposal.json']],
             scripts=('chord_proposal.py',)),
        Step('chords_lv', 'lvchordia', 'cpu', ('chords',),
             lambda c: ff(c, c.audio, A(c, 'chord_proposal.json')),
             lambda c: [(A(c, 'chords_lv.json'), None)],
             lambda c: [[c.env['lvchordia'], S('lv_chords.py'), str(c.audio), '--foundation',
                         'analysis/foundation.json', '--compare', 'analysis/chord_proposal.json',
                         '--out', 'analysis/chords_lv.json']],
             scripts=('lv_chords.py',)),
        Step('tab', 'py', 'cpu', ('chords_lv', 'align'),
             lambda c: [(A(c, n), ()) for n in ('tab_chords.json', 'chords_lv.json',
                                               'sections.json', 'bass_per_cell.json')],
             lambda c: [],
             lambda c: [[c.env['py'], S('tab_compare.py'), '--tab', 'analysis/tab_chords.json',
                         '--chords', 'analysis/chords_lv.json', '--sections',
                         'analysis/sections.json', '--bass', 'analysis/bass_per_cell.json']],
             skip=lambda c: (None if A(c, 'tab_chords.json').exists() and lyr(c).exists()
                             else 'no chord tab (lyrics_from_page.py --chords-out)'),
             scripts=('tab_compare.py',)),
        Step('drums', 'adtof', 'cpu', ('meter', 'stems'),
             lambda c: ff(c, c.stem('drums')),
             lambda c: [(A(c, 'drum_hits.json'), None)],
             lambda c: [[c.env['adtof'], S('drum_transcribe.py'), str(c.stem('drums')),
                         '--foundation', 'analysis/foundation.json']],
             skip=lambda c: None if c.answers.get('performance') else 'performance not asked',
             scripts=('drum_transcribe.py',)),
        Step('strum', 'analysis', 'cpu', ('meter', 'stems_6s'),
             lambda c: ff(c, c.stem('guitar', 'htdemucs_6s'), A(c, 'sections.json')),
             lambda c: [(A(c, 'strum.json'), None)],
             lambda c: [[c.env['analysis'], S('strum_pattern.py'),
                         str(c.stem('guitar', 'htdemucs_6s')), '--foundation',
                         'analysis/foundation.json']
                        + (['--sections', 'analysis/sections.json']
                           if A(c, 'sections.json').exists() else [])],
             skip=lambda c: ('performance not asked' if not c.answers.get('performance') else
                             'no htdemucs_6s guitar (no_6s answered)' if six(c) else None),
             scripts=('strum_pattern.py',), optional=('align',)),
        Step('activity', 'analysis', 'cpu', ('meter', 'stems'),
             lambda c: ff(c, *[c.stem(s) for s in ('bass', 'drums', 'vocals', 'other')]),
             lambda c: [(A(c, n), None) for n in ('stem_activity.json', 'band_level.json')],
             lambda c: [[c.env['analysis'], S('stem_activity.py'), str(c.stem('bass').parent),
                         '--foundation', 'analysis/foundation.json', '--out',
                         'analysis/stem_activity.json']],
             scripts=('stem_activity.py',)),
        Step('validate', 'py', 'cpu', ('meter', 'bass', 'chords', 'chords_lv'),
             lambda c: ff(c, *[A(c, n) for n in ('chords_lv.json', 'chord_proposal.json',
                                                 'bass_per_cell.json', 'lyrics_aligned.json',
                                                 'sections.json')]),
             lambda c: [],
             lambda c: [[c.env['py'], S('validate_artifacts.py'), 'analysis']],
             scripts=('validate_artifacts.py',), optional=('align',)),
        Step('chart', 'py', 'cpu', ('validate', 'activity'),
             lambda c: [(chart_file(c), ())] + ff(c, *[A(c, n) for n in (
                 'chords_lv.json', 'chord_proposal.json', 'bass_per_cell.json',
                 'stem_activity.json', 'band_level.json', 'lyrics_mix.json', 'lyrics.json')]),
             lambda c: [],
             lambda c: [[c.env['py'], S('chart_html.py'), chart_file(c).name],
                        [c.env['py'], S('chart_questions.py'), chart_file(c).name]],
             skip=lambda c: (None if chart_file(c) else
                             'no gen_v1.py yet: write the chart data file '
                             '(Phase 8, references/chart-and-lyrics.md), then run again'),
             scripts=('chart_html.py', 'chart_questions.py'), optional=('align', 'mode', 'tab')),
    ]


def lang(c: Ctx) -> list:
    return ['--language', c.answers['language']] if c.answers.get('language') else []


def demucs(c: Ctx, model: str) -> list:
    """Decode (or copy) to a WAV named by the slug - MP3 read by demucs starts 25 ms late,
    and the stems folder takes the input's name - then separate on the GPU."""
    tmp = Path(os.environ.get('TMPDIR', '/tmp')) / 'mws' / f'{c.slug}.wav'
    tmp.parent.mkdir(parents=True, exist_ok=True)
    return [[c.env['ffmpeg'] or 'ffmpeg', '-v', 'error', '-y', '-i', str(c.audio),
             '-c:a', 'pcm_s16le', str(tmp)],
            [c.env['demucs'], '-m', 'demucs', '-n', model, '-d', 'mps', '-o',
             str(c.song / 'stems'), str(tmp)]]


# ------------------------------------------------------------------ engine

def key_parts(c: Ctx, st: Step) -> dict:
    return {'reads': {str(p.relative_to(c.song) if p and p.is_relative_to(c.song) else p):
                      fingerprint(p, f) if p else None for p, f in st.reads(c)},
            'params': st.params(c),
            'scripts': {s: fingerprint(HERE / s) for s in st.scripts}}


def state_of(c: Ctx, st: Step, done: dict) -> tuple[str, str]:
    """('skip' | 'done' | 'stale' | 'todo' | 'asks', why)."""
    rec = c.state.setdefault('steps', {}).get(st.name)
    outs_ok = all(has(p, f) for p, f in st.writes(c))
    why = st.skip(c)
    if why and not (st.writes(c) and outs_ok):          # made before (by hand): keep it
        return 'skip', why
    if rec and rec.get('question') and not answered(c, rec):
        return 'asks', rec['question'].splitlines()[0]
    if not outs_ok:
        return 'todo', 'outputs missing'
    now = key_parts(c, st)
    if rec is None:
        return ('done', 'adopted') if st.writes(c) else ('todo', 'never run')
    changed = [k for k in now['reads'] if now['reads'][k] != rec['parts']['reads'].get(k)]
    changed += [f'answers {now["params"]}'] if now['params'] != rec['parts']['params'] else []
    changed += [f'script {s}' for s in now['scripts']
                if now['scripts'][s] != rec['parts']['scripts'].get(s)]
    return ('stale', 'changed: ' + ', '.join(changed)) if changed else ('done', '')


def answered(c: Ctx, rec: dict) -> bool:
    return bool(rec.get('resolved_by') and c.answers.get(rec['resolved_by']))


def show(name: str, secs: float, out: str, err: str, code: int) -> str:
    lines = [l for l in out.splitlines() if not NOISE.search(l)]
    lines += [l for l in err.splitlines() if re.match(r'\s*(warning|WARN|NEEDS A DECISION)', l)]
    if code not in (0, 2):
        lines += [l for l in err.splitlines() if not NOISE.search(l)][-12:]
    body = ''.join(f'  {l}\n' for l in lines[:40])
    more = f'  ... {len(lines) - 40} more lines in analysis/logs/{name}.log\n' if len(lines) > 40 else ''
    return f'-- {name} ({secs:.1f} s){"" if code == 0 else f" exit {code}"}\n{body}{more}'


def execute(c: Ctx, cmds: list, name: str) -> tuple[int, str, str, float]:
    t0, out, err, code = time.monotonic(), '', '', 0
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    if c.state.get('offline'):
        env['HF_HUB_OFFLINE'] = '1'
    for argv in cmds:
        r = subprocess.run([str(x) for x in argv], cwd=c.song, capture_output=True, text=True,
                           env=env)
        out, err, code = out + r.stdout, err + r.stderr, r.returncode
        if code:
            break
    (c.a / 'logs').mkdir(parents=True, exist_ok=True)
    (c.a / 'logs' / f'{name}.log').write_text(f'$ {cmds}\n{out}\n--- stderr\n{err}')
    return code, out, err, time.monotonic() - t0


def closure(table: dict, until: str | None) -> list[str]:
    if until is None:
        return list(table)
    need, todo = set(), [until]
    while todo:
        n = todo.pop()
        if n not in need:
            need.add(n)
            todo += list(table[n].needs) + list(table[n].optional)
    return [n for n in table if n in need]


def run(c: Ctx, table: dict, targets: list, redo: set = frozenset()) -> int:
    """Run the targets in dependency order on the two lanes. 0 all done, 1 a failure, 2 a
    question pending. A done step waits while anything upstream runs again, then is
    checked once more (pulse rewrites foundation.json: the meter must follow it)."""
    c.a.mkdir(exist_ok=True)                              # a fresh folder: the scripts write here
    status = {}
    for n in targets:
        s, why = state_of(c, table[n], status)
        status[n] = 'todo' if n in redo and s in ('done', 'stale', 'asks') else s
        if s == 'done' and why == 'adopted' and n not in redo:
            c.state['steps'][n] = dict(parts=key_parts(c, table[n]), adopted=True)
    deps = lambda n: [d for d in table[n].needs + table[n].optional if d in status]
    moving = ('todo', 'stale', 'wait', 'running')
    for n in targets:                                     # table order is dependency order
        if status[n] in ('done', 'stale') and n not in redo and \
                any(status[d] in moving for d in deps(n)):
            status[n] = 'wait'                            # judged once upstream has run
    for n in targets:
        if status[n] == 'skip':
            c.log(f'-- {n}: skipped ({table[n].skip(c)})')
    failed, asked, running = [], [], {}

    def block(n):
        for m in targets:
            if n in deps(m) and status[m] in ('todo', 'stale', 'wait'):
                status[m] = 'blocked'
                block(m)

    def ask(n, q, rec):
        c.state['steps'][n] = rec
        asked.append((n, q))
        status[n] = 'asks'
        block(n)

    for n in targets:
        if status[n] == 'asks':
            asked.append((n, c.state['steps'][n]['question']))
            block(n)
    with ThreadPoolExecutor(max_workers=sum(LANES.values())) as ex:
        while True:
            moved = False
            busy = {lane: sum(table[n].lane == lane for n in running.values()) for lane in LANES}
            for n in targets:
                st = table[n]
                if status[n] not in ('todo', 'stale', 'wait') or \
                        any(status[d] not in ('done', 'skip') for d in deps(n)):
                    continue
                if status[n] == 'wait':                   # upstream settled: look again
                    s, _ = state_of(c, st, status)
                    moved = True
                    if s in ('done', 'skip'):
                        status[n] = s
                        continue
                    if s == 'asks':
                        ask(n, c.state['steps'][n]['question'], c.state['steps'][n])
                        continue
                    status[n] = s
                if busy[st.lane] >= LANES[st.lane]:
                    continue
                if st.role != 'py' and not (c.env.get(st.role) and Path(c.env[st.role]).exists()):
                    failed.append((n, f'no {st.role} interpreter (run.py doctor)'))
                    status[n] = 'failed'
                    block(n)
                    moved = True
                    continue
                busy[st.lane] += 1
                status[n] = 'running'
                running[ex.submit(execute, c, st.argv(c), n)] = n
                moved = True
            if not running:
                if moved:
                    continue
                break
            done_f, _ = wait(running, return_when=FIRST_COMPLETED)
            for f in done_f:
                n = running.pop(f)
                st = table[n]
                code, out, err, secs = f.result()
                c.log(show(n, secs, out, err, code))
                with open(c.a / 'timings.jsonl', 'a') as tf:
                    tf.write(json.dumps(dict(step=n, seconds=round(secs, 1), exit=code,
                                             at=time.strftime('%Y-%m-%dT%H:%M:%S'))) + '\n')
                if code == 2 or 'NEEDS A DECISION' in err:
                    q = '\n'.join(l for l in err.splitlines() if l.strip()) or out.strip()
                    q += (f'\n  answer: run.py answer "{c.song}" <the flags it names> '
                          f'(--decided-by player if the player counted), then run again')
                    ask(n, q, dict(parts=key_parts(c, st), question=q))
                    continue
                if code:
                    failed.append((n, f'exit {code} (analysis/logs/{n}.log)'))
                    status[n] = 'failed'
                    c.state['steps'].pop(n, None)
                    block(n)
                    continue
                verdict = st.after(c, out) if st.after else None
                if verdict == 'redo':
                    c.save()
                    status[n] = 'todo'
                    continue
                rec = dict(parts=key_parts(c, st), seconds=round(secs, 1))
                if isinstance(verdict, tuple):
                    ask(n, verdict[1], dict(rec, question=verdict[1], resolved_by='keep_downbeat'))
                else:
                    status[n] = 'done'
                    c.state['steps'][n] = rec
                c.save()
    c.save()
    for n, q in asked:
        c.log(f'QUESTION ({n}): {q}')
    for n, why in failed:
        c.log(f'FAILED ({n}): {why}')
    waiting = [n for n in targets if status[n] == 'blocked']
    if waiting:
        c.log(f'waiting on that: {", ".join(waiting)}')
    if not failed and not asked:
        c.log('all done' + (f' up to {targets[-1]}' if targets else ''))
    return 1 if failed else 2 if asked else 0


# ------------------------------------------------------------------ commands

def context(song: str, audio: str | None = None, need_audio: bool = True) -> Ctx:
    p = Path(song).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f'run.py: {p} is not a song folder')
    rj = p / 'analysis' / 'run.json'
    state = json.loads(rj.read_text()) if rj.exists() else {}
    c = Ctx(p, state, load_env())
    c.audio = find_audio(p, state, audio)
    if c.audio is None or not c.audio.exists():
        if need_audio:
            names = [x.name for x in p.iterdir() if x.suffix.lower() in AUDIO]
            print(f'run.py: which recording? pass --audio (found: {names or "none"})')
            sys.exit(3)
    else:
        state.setdefault('slug', find_slug(p, c.audio))
    return c


def cmd_status(a) -> int:
    c = context(a.song)
    table = {s.name: s for s in steps()}
    st = {}
    for n, s in table.items():
        st[n] = state_of(c, s, st)
    for n, (s, why) in st.items():
        waits = [d for d in table[n].needs if st[d][0] not in ('done', 'skip')]
        if s in ('todo', 'stale') and waits:
            s, why = 'waits', f'for {", ".join(waits)}'
        print(f'{n:<11} {s:<6} {why}')
    for n, (s, _) in st.items():
        if s == 'asks':
            print(f'\nQUESTION ({n}): {c.state["steps"][n]["question"]}')
    print(f'\nanswers: {c.answers or "none"}')
    todo = [n for n, (s, _) in st.items() if s in ('todo', 'stale')]
    print(f'next: run.py run "{c.song}"' if todo else 'next: nothing to run')
    return 0


def cmd_run(a) -> int:
    c = context(a.song, a.audio)
    if c.env.get('ffmpeg') is None:
        print('run.py: ffmpeg not found (brew install ffmpeg, or MWS_FFMPEG)')
        return 3
    sys.path.insert(0, str(HERE))
    import validate_artifacts as V                       # the model caches: offline if all
    V.warnings.clear()
    V.check_cache()
    c.state['offline'] = not any('not cached' in w for w in V.warnings)
    for w in V.warnings:
        print(f'note: {w}')
    table = {s.name: s for s in steps()}
    bad = [n for n in [a.until, *a.redo] if n and n not in table]
    if bad:
        print(f'run.py: unknown step {bad}; steps: {", ".join(table)}')
        return 3
    print(f'{c.song.name}: {c.audio.name} -> stems/htdemucs_ft/{c.slug}/'
          + (' (models cached: offline)' if c.state['offline'] else ''))
    return run(c, table, closure(table, a.until), set(a.redo))


def cmd_answer(a) -> int:
    c = context(a.song, need_audio=False)
    for k, (typ, _) in ANSWERS.items():
        v = getattr(a, k)
        if v is not None and v is not False:
            c.answers[k] = v
    if a.decided_by is None and any(getattr(a, k) is not None for k in
                                    ('cycle', 'grouping', 'downbeat_pulse', 'pulse_unit')):
        c.answers.setdefault('decided_by', 'agent')
    for k in a.clear or []:
        c.answers.pop(k.replace('-', '_'), None)
    for n, rec in list(c.state.get('steps', {}).items()):   # an answer reopens its question
        if rec.get('question') and not answered(c, rec):
            rec.pop('question', None)
            rec['parts'] = {'reads': {}, 'params': None, 'scripts': {}}   # -> stale: re-run
    c.save()
    print(f'answers: {c.answers}\nnext: run.py run "{c.song}"')
    return 0


def cmd_doctor(a) -> int:
    env, bad = load_env(), 0
    for role in ROLES:
        p = env.get(role)
        ok = bool(p and Path(p).exists())
        bad += not ok and role != 'adtof'
        print(f"{'ok  ' if ok else 'MISS'} {role:<10} {p or '-'}"
              + ('' if ok or role != 'adtof' else '  (optional: Phase 4b drums)'))
    print(f"{'ok  ' if env['ffmpeg'] else 'MISS'} ffmpeg     {env['ffmpeg'] or '-'}")
    bad += not env['ffmpeg']
    sys.path.insert(0, str(HERE))
    import validate_artifacts as V
    V.warnings.clear()
    V.check_cache()
    for w in V.warnings or ['models cached']:
        print(f"{'note' if V.warnings else 'ok  '} {w}")
    if bad:
        print(f'\nWrite {ENV_FILE} (or set $MWS_<ROLE>_PY), e.g.:\n' + json.dumps(
            {r: f'<venv for {r}>/bin/python' for r in ROLES}, indent=1)
            + '\n(the venvs: references/environment-setup.md)')
    return 3 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('status')
    p.add_argument('song')
    p = sub.add_parser('run')
    p.add_argument('song')
    p.add_argument('--until', help='stop after this step (and what it needs)')
    p.add_argument('--redo', action='append', default=[], help='run this step again')
    p.add_argument('--audio', help="the recording's file name in the song folder")
    p = sub.add_parser('answer')
    p.add_argument('song')
    for k, (typ, hlp) in ANSWERS.items():
        flag = f"--{k.replace('_', '-')}"
        if typ is bool:
            p.add_argument(flag, action='store_true', default=None, help=hlp)
        elif k == 'decided_by':
            p.add_argument(flag, choices=('agent', 'player'), help=hlp)
        else:
            p.add_argument(flag, type=typ, help=hlp)
    p.add_argument('--clear', action='append', help='forget an answer, e.g. --clear cycle')
    sub.add_parser('doctor')
    a = ap.parse_args()
    sys.exit({'status': cmd_status, 'run': cmd_run, 'answer': cmd_answer,
              'doctor': cmd_doctor}[a.cmd](a))


if __name__ == '__main__':
    main()
