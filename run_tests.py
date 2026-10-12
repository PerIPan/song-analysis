#!/usr/bin/env python3
"""Run every test in the repo, each with the interpreter it needs - one command.

Most tests are standard library only (run with this Python). A few need the analysis
venv (numpy, librosa, madmom, soundfile) or the Whisper venv; they run when that
interpreter is known - $MWS_ANALYSIS_PY / $MWS_WHISPER_PY, or "analysis" / "whisper" in
~/.config/music-workflow-skills/env.json - and are skipped with a notice otherwise.

Usage:
    python3 run_tests.py            # everything it can run
    python3 run_tests.py --fast     # standard library only (~3 s; the pre-commit hook, CI)
    python3 run_tests.py chart      # only test files whose path contains 'chart'
Exit 1 when any test file fails.
"""
from __future__ import annotations

import argparse, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = Path.home() / '.config' / 'music-workflow-skills' / 'env.json'
TESTS = [  # (test file, interpreter role)
    ('tests/test_docs.py', 'std'),
    ('song-analysis/tests/test_foundation.py', 'std'),
    ('song-analysis/tests/test_align_lyrics.py', 'std'),
    ('song-analysis/tests/test_chart_html.py', 'std'),
    ('song-analysis/tests/test_lyrics_tab.py', 'std'),
    ('song-analysis/tests/test_chart_questions.py', 'std'),
    ('song-analysis/tests/test_fetch_audio.py', 'std'),
    ('song-analysis/tests/test_validate_artifacts.py', 'std'),
    ('song-analysis/tests/test_run.py', 'std'),
    ('song-analysis/tests/test_publish_chart.py', 'std'),
    ('song-analysis/tests/test_chart_export.py', 'std'),
    ('song-analysis/tests/test_chart_player.py', 'std'),
    ('song-analysis/tests/test_chart_seed.py', 'std'),
    ('ableton-mcp/tests/test_push_notes.py', 'std'),
    ('ableton-song-remix/tests/test_chordsym.py', 'std'),
    ('ableton-song-remix/tests/test_remix_plan.py', 'std'),
    ('ableton-song-remix/tests/test_remix_parts.py', 'std'),
    ('ableton-song-remix/tests/test_remix_build.py', 'std'),
    ('song-analysis/tests/test_detect_meter.py', 'analysis'),
    ('song-analysis/tests/test_chord_proposal.py', 'analysis'),
    ('song-analysis/tests/test_mode_test.py', 'analysis'),
    ('song-analysis/tests/test_downbeat_check.py', 'analysis'),
    ('song-analysis/tests/test_stem_activity.py', 'analysis'),
    ('song-analysis/tests/test_performance.py', 'analysis'),
    ('song-analysis/tests/test_whisper_artefacts.py', 'whisper'),
]


def interpreters() -> dict:
    """role -> interpreter path (None when unknown)."""
    conf = {}
    if ENV_FILE.exists():
        try:
            conf = json.loads(ENV_FILE.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f'run_tests: {ENV_FILE} is not JSON ({e})')
    find = lambda role: os.environ.get(f'MWS_{role.upper()}_PY') or conf.get(role)
    out = {'std': sys.executable}
    for role in ('analysis', 'whisper'):
        p = find(role)
        out[role] = str(Path(p).expanduser()) if p and Path(p).expanduser().exists() else None
    return out


def run(test: str, py: str) -> tuple[str, int, str, float]:
    t0 = time.monotonic()
    r = subprocess.run([py, test], cwd=ROOT, capture_output=True, text=True)
    return test, r.returncode, r.stdout + r.stderr, time.monotonic() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('match', nargs='?', default='', help='run only paths containing this')
    ap.add_argument('--fast', action='store_true', help='standard library tests only')
    a = ap.parse_args()
    py = interpreters()
    todo = [(t, r) for t, r in TESTS if a.match in t and (r == 'std' or not a.fast)]
    skipped = [t for t, r in todo if py[r] is None]
    jobs = [(t, py[r]) for t, r in todo if py[r]]
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as ex:
        results = list(ex.map(lambda j: run(*j), jobs))
    failed = 0
    for test, code, out, secs in results:
        passes = sum(line.startswith(('PASS', 'ok ')) for line in out.splitlines())
        print(f"{'ok  ' if code == 0 else 'FAIL'} {test}  ({passes} checks, {secs:.1f} s)")
        if code:
            failed += 1
            bad = [l for l in out.splitlines() if l.startswith(('FAIL', 'Traceback', 'Error'))]
            print('     ' + '\n     '.join((bad or out.splitlines()[-8:])[:12]))
    for t in skipped:
        role = dict(TESTS)[t]
        print(f'skip {t}  (no {role} interpreter: set $MWS_{role.upper()}_PY or {ENV_FILE})')
    print(f'{len(results) - failed}/{len(results)} test files passed'
          + (f', {len(skipped)} skipped' if skipped else ''))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
