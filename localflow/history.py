"""Transcription history — every successful dictation, stored locally.

SQLite at ~/.config/localflow/history.db. Raw ASR text is kept alongside the
formatted text: it costs nothing and is the training data for the future
learn-from-corrections feature.
"""

from __future__ import annotations

import html
import sqlite3
import time
from pathlib import Path

from .config import CONFIG_DIR

DB_FILE = CONFIG_DIR / "history.db"
LIBRARY_FILE = CONFIG_DIR / "library.html"

SCHEMA = """
CREATE TABLE IF NOT EXISTS dictations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    app_name TEXT,
    bundle_id TEXT,
    raw_text TEXT NOT NULL,
    final_text TEXT NOT NULL,
    audio_seconds REAL,
    elapsed_seconds REAL
)
"""


def _connect(db_path: Path = DB_FILE) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    return conn


def add(
    final_text: str,
    raw_text: str = "",
    app_name: str | None = None,
    bundle_id: str | None = None,
    audio_seconds: float = 0.0,
    elapsed_seconds: float = 0.0,
    db_path: Path = DB_FILE,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO dictations (ts, app_name, bundle_id, raw_text, final_text,"
            " audio_seconds, elapsed_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), app_name, bundle_id, raw_text, final_text,
             audio_seconds, elapsed_seconds),
        )


def recent(limit: int = 10, db_path: Path = DB_FILE) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ts, app_name, final_text FROM dictations ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"ts": ts, "app_name": app, "text": text} for ts, app, text in rows]


def count(db_path: Path = DB_FILE) -> int:
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM dictations").fetchone()[0]


def clear(db_path: Path = DB_FILE) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM dictations")


LIBRARY_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>LocalFlow Library</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 -apple-system, sans-serif; max-width: 760px;
         margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.3rem; }} h1 small {{ font-weight: 400; opacity: .6; }}
  #q {{ width: 100%; padding: .6rem .8rem; font-size: 1rem; border-radius: 8px;
       border: 1px solid #8884; margin-bottom: 1.2rem; }}
  .day {{ font-weight: 600; margin: 1.4rem 0 .4rem; opacity: .7; }}
  .row {{ padding: .55rem .7rem; border-radius: 8px; margin-bottom: .3rem;
         background: #8881; display: flex; gap: .8rem; align-items: baseline; }}
  .meta {{ white-space: nowrap; font-size: .8rem; opacity: .55; min-width: 7.5rem; }}
  .text {{ flex: 1; }}
  button {{ border: none; background: #8882; border-radius: 6px; padding: .2rem .55rem;
           cursor: pointer; font-size: .8rem; }}
  button:hover {{ background: #8884; }}
</style></head><body>
<h1>LocalFlow Library <small>{count} dictations · stored only on this Mac</small></h1>
<input id="q" type="search" placeholder="Search your dictations…" autofocus>
<div id="list">{rows}</div>
<script>
  const q = document.getElementById('q');
  q.addEventListener('input', () => {{
    const needle = q.value.toLowerCase();
    document.querySelectorAll('.row').forEach(r =>
      r.style.display = r.dataset.text.includes(needle) ? '' : 'none');
    document.querySelectorAll('.day').forEach(d => {{
      let n = d.nextElementSibling, any = false;
      while (n && n.classList.contains('row')) {{
        if (n.style.display !== 'none') any = true; n = n.nextElementSibling;
      }}
      d.style.display = any ? '' : 'none';
    }});
  }});
  function cp(btn) {{
    navigator.clipboard.writeText(btn.closest('.row').dataset.full);
    btn.textContent = '✓'; setTimeout(() => btn.textContent = 'Copy', 900);
  }}
</script></body></html>
"""


def render_library(db_path: Path = DB_FILE, out_path: Path = LIBRARY_FILE) -> Path:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ts, app_name, final_text FROM dictations ORDER BY id DESC"
        ).fetchall()
    parts: list[str] = []
    current_day = None
    for ts, app, text in rows:
        local = time.localtime(ts)
        day = time.strftime("%A %d %B %Y", local)
        if day != current_day:
            parts.append(f'<div class="day">{day}</div>')
            current_day = day
        escaped = html.escape(text)
        parts.append(
            f'<div class="row" data-text="{html.escape(text.lower(), quote=True)}"'
            f' data-full="{html.escape(text, quote=True)}">'
            f'<span class="meta">{time.strftime("%H:%M", local)} · {html.escape(app or "?")}</span>'
            f'<span class="text">{escaped}</span>'
            f'<button onclick="cp(this)">Copy</button></div>'
        )
    out_path.write_text(LIBRARY_TEMPLATE.format(count=len(rows), rows="\n".join(parts)))
    return out_path
