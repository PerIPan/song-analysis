#!/usr/bin/env python3
"""The chart with the recording under it: play along, loop, slow down, note fixes by ear.

Why: a player checked a chart by playing the record in another app and reading bar numbers
off a static page - two dozen single-cell messages in an hour and a half, and mix-ups over
which bar was meant. Here the chart follows the recording: the cell sounding now is lit,
a click plays from one bar before a cell, shift-click marks a loop from the last cell
clicked (L loops the section), the speed drops to 50% without changing pitch, and a fix is
typed against the cell it belongs to and collected in a list to copy back in one message
("bar 12.1 (0:41): G, not Am"). The printed chart is unchanged; the controls don't print.

Writes "<artist> - <title> - Player.html" next to the chart (or --out), the page the
renderer makes plus each cell's time, an <audio> of the song's recording (a relative link:
keep the page beside the audio, it is a local tool - not for the band's shared folder) and
a small script. Notes stay in the browser (localStorage) until copied.

Keys: space play/pause · ←/→ a bar back/on · L loop the section (again: off) · [ ] slower /
faster · N note the cell playing now · Esc clear the loop.

Usage (python3, standard library only):
    chart_player.py <song>/gen_v1.py [--audio FILE] [--out PATH]
"""
from __future__ import annotations

import argparse, html, json, os, re, sys, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chart_html import Grid, compose, load_json, load_song  # noqa: E402

AUDIO = ('.wav', '.mp3', '.m4a', '.flac', '.aiff', '.aif', '.ogg')
CSS = """
#pl{position:sticky;top:0;z-index:9;display:flex;flex-wrap:wrap;gap:.4em .8em;align-items:center;background:#1f2937;color:#f3f4f6;padding:.45em .8em;margin:0 -.8em .6em;font-size:.8em}
#pl button,#pl select{font:inherit;background:#374151;color:#f3f4f6;border:1px solid #4b5563;border-radius:4px;padding:.15em .6em;cursor:pointer}
#pl button.on{background:#b03030;border-color:#b03030}
#pl .t{font-family:Menlo,monospace;min-width:7.5em}
#pl .hint{color:#9ca3af;font-size:.9em}
.half{cursor:pointer}
.half.now{box-shadow:inset 0 0 0 3px #2563eb;background:#eff6ff !important}
.half.loop{background:#fff7ed !important}
.half.noted::before{content:"✎";position:absolute;left:.3em;bottom:.15em;font-size:.75em;color:#b58632}
#notes{position:fixed;right:.8em;bottom:.8em;width:22em;max-width:90vw;max-height:45vh;overflow:auto;background:#fff;border:1px solid #d4d4d0;border-radius:6px;box-shadow:0 4px 18px rgba(0,0,0,.15);padding:.6em .7em;font-size:.8em;z-index:10}
#notes h3{margin:0 0 .4em;font-size:.95em}
#notes input{flex:1;min-width:0;box-sizing:border-box;font:inherit;padding:.25em .4em;margin:.2em 0}
#notes ol{padding-left:1.3em;margin:.4em 0}
#notes li button{border:none;background:none;color:#b03030;cursor:pointer}
#notes .row{display:flex;gap:.4em}
@media print{#pl,#notes{display:none}.half.now,.half.loop{box-shadow:none;background:inherit !important}.half.noted::before{content:none}}
"""
JS = r"""
(() => {
  const A = document.getElementById('aud'), cells = [...document.querySelectorAll('.half[data-t]')];
  const T = cells.map(c => +c.dataset.t), D = window.PLAYER;
  const key = 'chart-notes:' + D.title;
  let notes = []; try { notes = JSON.parse(localStorage.getItem(key) || '[]'); } catch (e) {}
  let loop = null, anchor = null, now = -1;
  const $ = id => document.getElementById(id);
  const mmss = t => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`;
  const idx = t => { let lo = 0, hi = T.length - 1, r = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (T[m] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; };
  const barStart = i => cells.findIndex(c => c.dataset.b === cells[i].dataset.b);
  const save = () => { try { localStorage.setItem(key, JSON.stringify(notes)); } catch (e) {} };
  const label = c => `bar ${c.dataset.b}.${c.dataset.c} (${mmss(+c.dataset.t)})`;
  function paintNotes() {
    cells.forEach(c => c.classList.toggle('noted', notes.some(n => n.b == c.dataset.b && n.c == c.dataset.c)));
    $('nlist').innerHTML = notes.map((n, i) => `<li>${n.label}: ${n.text.replace(/[<&]/g, s => s == '<' ? '&lt;' : '&amp;')} <button data-i="${i}" title="remove">×</button></li>`).join('');
    $('ncount').textContent = notes.length;
  }
  function setLoop(a, b) {
    loop = a == null ? null : [Math.min(a, b), Math.max(a, b)];
    cells.forEach((c, i) => c.classList.toggle('loop', !!loop && i >= loop[0] && i <= loop[1]));
    $('bloop').classList.toggle('on', !!loop);
  }
  function seekCell(i, preroll) {
    const j = preroll ? Math.max(0, barStart(i) - (cells.filter(c => c.dataset.b === cells[i].dataset.b).length)) : i;
    A.currentTime = Math.max(0, T[Math.max(0, j)] - (j === 0 ? 0 : 0.05));
  }
  function tick() {
    const i = idx(A.currentTime);
    if (loop && (i > loop[1] || i < loop[0]) && !A.paused) { A.currentTime = T[loop[0]]; }
    if (i !== now) {
      if (now >= 0) cells[now].classList.remove('now');
      now = i;
      if (i >= 0) { cells[i].classList.add('now');
        const r = cells[i].getBoundingClientRect();
        if (r.top < 60 || r.bottom > innerHeight - 20) cells[i].scrollIntoView({block: 'center', behavior: 'smooth'}); }
      $('ncell').textContent = i >= 0 ? label(cells[i]) : '-';
    }
    $('time').textContent = mmss(A.currentTime) + ' / ' + mmss(A.duration || 0);
    requestAnimationFrame(tick);
  }
  cells.forEach((c, i) => c.addEventListener('click', e => {
    if (e.shiftKey && anchor != null) { setLoop(anchor, i); A.currentTime = T[loop[0]]; A.play(); return; }
    anchor = i; $('ncell').textContent = label(c); $('ncell').dataset.i = i;
    seekCell(i, true); A.play();
  }));
  const speed = $('speed');
  A.preservesPitch = A.mozPreservesPitch = A.webkitPreservesPitch = true;
  speed.addEventListener('change', () => { A.playbackRate = +speed.value; });
  const step = d => { const o = [...speed.options].findIndex(o => +o.value === A.playbackRate);
    const n = Math.min(speed.options.length - 1, Math.max(0, o + d)); speed.selectedIndex = n; A.playbackRate = +speed.value; };
  $('bplay').addEventListener('click', () => A.paused ? A.play() : A.pause());
  A.addEventListener('play', () => $('bplay').textContent = 'Pause');
  A.addEventListener('pause', () => $('bplay').textContent = 'Play');
  function loopSection() {
    if (loop) { setLoop(null); return; }
    const i = Math.max(0, now), row = cells[i].closest('.row'), sec = [];
    let r = row; while (r && !r.classList.contains('section-start')) r = r.previousElementSibling;
    for (let x = r; x && (x === r || !x.classList.contains('section-start')); x = x.nextElementSibling)
      x.querySelectorAll('.half[data-t]').forEach(c => sec.push(cells.indexOf(c)));
    if (sec.length) setLoop(sec[0], sec[sec.length - 1]);
  }
  $('bloop').addEventListener('click', loopSection);
  function addNote() {
    const inp = $('ntext'), i = +($('ncell').dataset.i ?? now);
    if (!inp.value.trim() || !(i >= 0)) return;
    const c = cells[i]; notes.push({b: c.dataset.b, c: c.dataset.c, label: label(c), text: inp.value.trim()});
    inp.value = ''; save(); paintNotes();
  }
  $('nadd').addEventListener('click', addNote);
  $('ntext').addEventListener('keydown', e => { if (e.key === 'Enter') addNote(); e.stopPropagation(); });
  $('nlist').addEventListener('click', e => { if (e.target.dataset.i != null) { notes.splice(+e.target.dataset.i, 1); save(); paintNotes(); } });
  $('ncopy').addEventListener('click', () => {
    const text = `${D.title} - fixes by ear:\n` + notes.map(n => `${n.label}: ${n.text}`).join('\n');
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
      () => { $('ncopy').textContent = 'Copied'; setTimeout(() => $('ncopy').textContent = 'Copy all', 1500); },
      () => { const t = document.createElement('textarea'); t.value = text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove(); });
  });
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    const bars = cells.map(c => c.dataset.b), cur = Math.max(0, now);
    if (e.key === ' ') { e.preventDefault(); A.paused ? A.play() : A.pause(); }
    else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault();
      const b = +bars[cur] + (e.key === 'ArrowRight' ? 1 : -1), j = bars.indexOf(String(b)); if (j >= 0) A.currentTime = T[j]; }
    else if (e.key === 'l' || e.key === 'L') loopSection();
    else if (e.key === '[') step(-1); else if (e.key === ']') step(1);
    else if (e.key === 'Escape') setLoop(null);
    else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); $('ncell').dataset.i = cur; $('ncell').textContent = label(cells[cur]); $('ntext').focus(); }
  });
  paintNotes(); requestAnimationFrame(tick);
  document.body.dataset.player = 'ready';
})();
"""


def find_audio(folder: Path, given: str | None) -> Path:
    if given:
        p = Path(given)
        return p if p.is_absolute() else folder / p
    src = folder / 'source.json'
    if src.exists():
        f = json.loads(src.read_text()).get('file')
        if f and (folder / f).exists():
            return folder / f
    run = folder / 'analysis' / 'run.json'
    if run.exists():
        f = json.loads(run.read_text()).get('audio')
        if f and (folder / f).exists():
            return folder / f
    cands = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO)
    if len(cands) != 1:
        raise ValueError(f'which recording? pass --audio (found: {[p.name for p in cands]})')
    return cands[0]


def cell_times(S: dict) -> list[tuple[int, int, float]]:
    """(bar, cell, start) for every chart cell in page order (sections run in bar order)."""
    F = load_json(Path(S['folder']) / 'analysis' / 'foundation.json')
    grouping = list(S.get('grouping') or F['grouping'])
    db = list(F['downbeat_times'])
    last = max(sec[2] for sec in S['sections'])
    if last == len(db):
        end = S.get('duration_s') or 0
        db.append(end if end > db[-1] else 2 * db[-1] - db[-2])
    g = Grid(db, grouping)
    return [(b, c, round(g.start((b, c)), 3)) for b in range(1, last + 1)
            for c in range(1, len(grouping) + 1)]


def player(S: dict, audio: Path, out: Path) -> str:
    doc, info = compose(S)
    times = cell_times(S)
    it = iter(times)

    def tag(m):
        b, c, t = next(it)
        return f'{m.group(0)[:-1]} data-b="{b}" data-c="{c}" data-t="{t}">'
    doc, n = re.subn(r'<div class="half[^"]*">', tag, doc)
    if n != len(times):
        raise ValueError(f'{n} cells on the page, {len(times)} on the grid')
    src = urllib.parse.quote(os.path.relpath(audio, out.parent))
    title = f"{S['artist']} — {S['title']}"
    bar = (f'<div id="pl"><button id="bplay">Play</button><span class="t" id="time">0:00.0</span>'
           f'<label>speed <select id="speed">' + ''.join(
               f'<option value="{v}"{" selected" if v == 1 else ""}>{int(v * 100)}%</option>'
               for v in (0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1)) + '</select></label>'
           '<button id="bloop" title="L">Loop section</button>'
           '<span class="hint">click a cell: play from a bar before · shift-click: loop to it · '
           'N: note · ←/→ bars · [ ] speed</span>'
           f'<audio id="aud" preload="auto" src="{html.escape(src)}"></audio></div>')
    notes = ('<div id="notes"><h3>Fixes by ear (<span id="ncount">0</span>)</h3>'
             '<div>at <b id="ncell">-</b></div><div class="row"><input id="ntext" '
             'placeholder="e.g. G, not Am · word on the next half"><button id="nadd">Add</button>'
             '</div><ol id="nlist"></ol><button id="ncopy">Copy all</button></div>')
    data = json.dumps({'title': title})
    doc = doc.replace('</style></head><body>', CSS + '</style></head><body>', 1)
    doc = re.sub(r'(<body>\n?)', lambda m: m.group(1) + bar, doc, count=1)
    doc = doc.replace('</body></html>', f'{notes}<script>window.PLAYER={data};{JS}</script>'
                      '</body></html>', 1)
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('data', help='the chart data file, e.g. gen_v1.py')
    ap.add_argument('--audio', help="the recording (default: the song folder's)")
    ap.add_argument('--out', help='default: "<artist> - <title> - Player.html" in the song folder')
    a = ap.parse_args()
    sys.dont_write_bytecode = True
    try:
        S = load_song(a.data)
        folder = Path(S['folder'])
        audio = find_audio(folder, a.audio)
        name = re.sub(r'[\\/:]', '-', f"{S['artist']} - {S['title']} - Player.html")
        out = Path(a.out) if a.out else folder / name
        out.write_text(player(S, audio, out), encoding='utf-8')
        print(f'wrote {out.name}: plays {audio.name} (keep it beside the audio; a local tool)')
    except (OSError, ValueError) as e:
        sys.exit(f'chart_player: {e}')


if __name__ == '__main__':
    main()
