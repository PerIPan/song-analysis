#!/usr/bin/env python3
"""Docs vs scripts: phrases that went stale stay gone, and every flag the skills' docs show
for a repo script exists in that script.

Stale phrases are claims that were true once (Harte labels refused, the Master track out of
reach, one meter per Set, raw lv-chordia chords sent to Live, flags recorded as 'user', a
stale grid only warned about). The flag check reads each command line in SKILL.md and
references/*.md that names scripts/<name>.py (with its backslash continuations) and looks
for every --flag in that script's source.
Run: python3 tests/test_docs.py   (standard library only)
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted([*ROOT.glob('*/SKILL.md'), *ROOT.glob('*/references/*.md')])
SCRIPTS = {p.name: p for p in ROOT.glob('*/scripts/*.py')} | {
    p.name: p for p in ROOT.glob('*/bench/*.py')}
STALE = [  # (pattern, why it is wrong now)
    (r"Harte labels[^.]*are refused|they are refused", "chart_html converts Harte labels"),
    (r"❌ Effects on the \*\*Master track\*\*", "patch 2 inserts devices on the Master track"),
    (r"(?i)one meter per set", "Live allows meter changes; the build uses one"),
    (r"`chords_lv` \(checked by `chord_proposal`\)", "Live takes the chart's chords"),
    (r"recorded as `user`", "foundation.py records agent or player (--decided-by)"),
    (r"another grid is warned about", "chart_html refuses evidence from another grid"),
]


def commands(text: str):
    """(script name, the command text) for each line naming scripts/<x>.py, joined with
    its backslash continuations."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for m in re.finditer(r'scripts/([a-z_]+\.py)', line):
            cmd, j = line[m.end():], i
            while cmd.rstrip().endswith('\\') and j + 1 < len(lines):
                j += 1
                cmd = cmd.rstrip()[:-1] + ' ' + lines[j]
            nxt = re.search(r'scripts/[a-z_]+\.py|\||&&|;|`', cmd)  # up to the next command
            yield m.group(1), cmd[:nxt.start()] if nxt else cmd


def main():
    fails = 0
    def check(name, cond, info=''):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + ('' if cond else f'  [{info}]'))

    for pat, why in STALE:
        hits = [f'{d.relative_to(ROOT)}:{n}' for d in DOCS
                for n, line in enumerate(d.read_text().splitlines(), 1) if re.search(pat, line)]
        check(f'stale phrase gone: {why}', not hits, hits)
    missing, seen = [], 0
    for d in DOCS:
        for name, cmd in commands(d.read_text()):
            if name not in SCRIPTS:
                continue
            src = SCRIPTS[name].read_text()
            for flag in re.findall(r'(?<![\w-])(--[a-z][a-z0-9-]*)', cmd):
                seen += 1
                if f'"{flag}"' not in src and f"'{flag}'" not in src:
                    missing.append(f'{d.relative_to(ROOT)}: {name} {flag}')
    check(f'every documented script flag exists ({seen} checked)', seen > 30 and not missing,
          missing)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
