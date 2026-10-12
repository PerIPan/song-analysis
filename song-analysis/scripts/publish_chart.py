#!/usr/bin/env python3
"""Publish a chart to the band: its HTML and an A4 PDF, named the band's way with WiP or OK.

Why: the delivery step was a shell loop pasted into the conversation - render, print with
headless Chrome, copy into the shared folder - re-run after every fix (46 prints in one
session) and kept only in memory. Here it is one command, and it writes nothing to the
shared folder until it is told to: without --yes it prints what it would write (and
replace), so the user can say yes first. Publish when the player says the chart is ready
for the band, not after each fix.

Names follow the band's folder: "<prefix> <Artist> - <Title> - chords - <key> <WiP|OK>"
(.html, .pdf); --prefix is the set slot ("3.3"), --status WiP (the default: not yet
checked by the band) or OK. A file of the same name with the other status is replaced
either way (OK -> a revised WiP too: the band's OK was for the old chart; the dry run says
so). The PDF is printed first: if Chrome fails, nothing is written or removed (exit 1;
--html-only publishes the page alone). The page count is reported (the band's charts run
1-3 pages).

--rerender ROOT re-renders every ROOT/*/ song's newest gen_v<N>.py in memory and lists the
charts whose HTML would change - after a renderer change - writing them only with --yes.

Destination: --to, else "publish_to" in ~/.config/music-workflow-skills/env.json, a folder
template with {artist}, e.g. "~/Dropbox/Public/Band/{artist}". The PDF needs Chrome
(or $MWS_CHROME); without it only the HTML is written, with a notice.

Usage (python3, standard library only):
    publish_chart.py <song>/gen_v1.py [--to DIR] [--status WiP|OK] [--prefix 3.3] [--yes]
        [--html-only]
    publish_chart.py --rerender ~/dev/songs [--yes]
"""
from __future__ import annotations

import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chart_html import compose, load_song, report_corrections  # noqa: E402

ENV_FILE = Path.home() / '.config' / 'music-workflow-skills' / 'env.json'
CHROME = ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
          '/Applications/Chromium.app/Contents/MacOS/Chromium')
STATUSES = ('WiP', 'OK')


def chrome() -> str | None:
    env = os.environ.get('MWS_CHROME')
    if env:
        return env
    return next((c for c in CHROME if Path(c).exists()), None) or next(
        (shutil.which(n) for n in ('google-chrome', 'chromium', 'chromium-browser')
         if shutil.which(n)), None)


def base_name(S: dict, status: str, prefix: str | None) -> str:
    """'3.3 Artist - Title - chords - E minor WiP' (no / \\ : in it)."""
    key = f" - {S['key_short']}" if S.get('key_short') else ''
    name = f"{S['artist']} - {S['title']} - chords{key} {status}"
    return re.sub(r'[\\/:]', '-', f'{prefix} {name}' if prefix else name)


def pages(pdf: Path) -> int:
    return len(re.findall(rb'/Type\s*/Page(?!s)', pdf.read_bytes()))


def print_pdf(html: Path, pdf: Path) -> str | None:
    """Headless Chrome's A4 print of html (the chart's own print CSS); None, or why not."""
    exe = chrome()
    if not exe:
        return 'no Chrome found (set $MWS_CHROME): HTML only'
    r = subprocess.run([exe, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                        f'--print-to-pdf={pdf}', html.resolve().as_uri()],
                       capture_output=True, text=True, timeout=120)
    return None if pdf.exists() and pdf.stat().st_size else f'Chrome made no PDF ({r.stderr[-200:]})'


def destination(S: dict, to: str | None) -> Path | None:
    if to:
        return Path(to).expanduser()
    conf = json.loads(ENV_FILE.read_text()) if ENV_FILE.exists() else {}
    tpl = conf.get('publish_to')
    return Path(tpl.format(artist=re.sub(r'[\\/:]', '-', S['artist']))).expanduser() if tpl else None


def publish(data: str, to: str | None, status: str, prefix: str | None, yes: bool,
            html_only: bool = False) -> int:
    S = load_song(data)
    doc, info = compose(S)
    report_corrections(info)
    if info['failed']:
        print('publish_chart: a player correction no longer holds - fix the chart first')
        return 1
    dest = destination(S, to)
    if dest is None:
        print(f'publish_chart: where to? pass --to, or set "publish_to" in {ENV_FILE}')
        return 2
    base = base_name(S, status, prefix)
    other = base_name(S, STATUSES[status == 'WiP'], prefix)
    files = [dest / f'{base}.html', dest / f'{base}.pdf']
    old = [p for ext in ('.html', '.pdf') for p in [dest / f'{other}{ext}'] if p.exists()]
    if info['n_q']:
        print(f"note: {info['n_q']} cells still marked '?' - the player hasn't checked them")
    if not yes:
        print(f"would write to {dest}:\n" + ''.join(f'  {p.name}\n' for p in files)
              + ''.join(f'  (replacing {p.name})\n' for p in old)
              + 'nothing written - ask the user, then run again with --yes')
        return 0
    with tempfile.TemporaryDirectory() as tmp:            # print first, from a local copy
        local, pdf = Path(tmp) / 'chart.html', Path(tmp) / 'chart.pdf'
        local.write_text(doc, encoding='utf-8')
        why = None if html_only else print_pdf(local, pdf)
        if why and not html_only:
            print(f'publish_chart: {why} - nothing written or removed (--html-only publishes '
                  'the page alone)')
            return 1
        dest.mkdir(parents=True, exist_ok=True)
        files[0].write_text(doc, encoding='utf-8')
        if not html_only:
            shutil.copyfile(pdf, files[1])
            n = pages(files[1])
        elif files[1].exists():
            files[1].unlink()                             # an older print of another chart
    for p in old:
        p.unlink()
    why = 'HTML only' if html_only else None
    n = 0 if html_only else n
    print(f'published {files[0].name}' + (f' and .pdf ({n} pages)' if n else f' ({why})')
          + f' to {dest}' + (f'; removed the {STATUSES[status == "WiP"]} copy' if old else ''))
    if n > 3:
        print(f'note: {n} pages - the band\'s charts run 1-3')
    return 0


def rerender(root: str, yes: bool) -> int:
    changed = 0
    for folder in sorted(p for p in Path(root).expanduser().iterdir() if p.is_dir()):
        gens = sorted(folder.glob('gen_v*.py'), key=lambda p: int(re.sub(r'\D', '', p.stem) or 0))
        if not gens:
            continue
        try:
            S = load_song(gens[-1])
            doc, info = compose(S)
        except (OSError, ValueError) as e:
            print(f'ERROR   {folder.name}: {e}')
            continue
        out = info['default_out']
        same = out.exists() and out.read_text(encoding='utf-8') == doc
        changed += not same
        bad = f" ({len(info['failed'])} corrections broken)" if info['failed'] else ''
        print(f"{'same   ' if same else 'CHANGED'} {folder.name}: {out.name}{bad}")
        if not same and yes:
            out.write_text(doc, encoding='utf-8')
    if changed and not yes:
        print(f'{changed} chart(s) would change - --yes writes them (in the song folders)')
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('data', nargs='?', help='the chart data file, e.g. <song>/gen_v1.py')
    ap.add_argument('--to', help='destination folder (default: publish_to in env.json)')
    ap.add_argument('--status', choices=STATUSES, default='WiP')
    ap.add_argument('--prefix', help="the set slot, e.g. '3.3'")
    ap.add_argument('--yes', action='store_true', help='write (the user said yes)')
    ap.add_argument('--html-only', action='store_true', help='no PDF (no Chrome here)')
    ap.add_argument('--rerender', metavar='ROOT', help='re-render every song folder under ROOT')
    a = ap.parse_args()
    sys.dont_write_bytecode = True
    if bool(a.data) == bool(a.rerender):
        ap.error('give a data file or --rerender ROOT')
    try:
        sys.exit(rerender(a.rerender, a.yes) if a.rerender else
                 publish(a.data, a.to, a.status, a.prefix, a.yes, a.html_only))
    except (OSError, ValueError) as e:
        sys.exit(f'publish_chart: {e}')


if __name__ == '__main__':
    main()
