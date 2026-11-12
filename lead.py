"""Lead drafts in SQLite. Shared by the site and the bot."""
from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = DATA / "leads.db"
QUESTIONS = ROOT / "bot_questions.json"
PAIN_MAX = 280
# ponytail: one lock + WAL; split processes already (http / bot), connection-per-call if writers stall
_lock = threading.Lock()
log = logging.getLogger("funnel")
log.addHandler(logging.NullHandler())


class _Tag(logging.Filter):
    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag

    def filter(self, record: logging.LogRecord) -> bool:
        record.tag = self.tag
        return True


def setup_log(tag: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    if any(isinstance(h, logging.FileHandler) for h in log.handlers):
        return
    log.setLevel(logging.INFO)
    log.handlers = [h for h in log.handlers if not isinstance(h, logging.NullHandler)]
    fmt = logging.Formatter("%(asctime)s %(tag)s %(levelname)s %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(DATA / "funnel.log", encoding="utf-8")
    sh = logging.StreamHandler()
    for h in (fh, sh):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.addFilter(_Tag(tag))
    log.propagate = False
    log.info("log -> %s", DATA / "funnel.log")


def load_dotenv() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def bot_username() -> str:
    return (os.environ.get("BOT_USERNAME") or "").lstrip("@").strip()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = _conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS leads (
                  id INTEGER PRIMARY KEY,
                  token TEXT UNIQUE NOT NULL,
                  pain TEXT NOT NULL,
                  lang TEXT NOT NULL,
                  tg_id INTEGER,
                  tg_username TEXT,
                  tg_name TEXT,
                  status TEXT NOT NULL,
                  created TEXT NOT NULL,
                  nn_json TEXT
                );
                CREATE TABLE IF NOT EXISTS answers (
                  id INTEGER PRIMARY KEY,
                  lead_id INTEGER NOT NULL,
                  q_key TEXT NOT NULL,
                  q_text TEXT NOT NULL,
                  a_text TEXT NOT NULL,
                  ts TEXT NOT NULL
                );
                """
            )
            conn.commit()
        finally:
            conn.close()


def new_token() -> str:
    init()
    with _lock:
        conn = _conn()
        try:
            for _ in range(16):
                token = secrets.token_urlsafe(6)
                if len(token) > 64:
                    token = token[:64]
                row = conn.execute("SELECT 1 FROM leads WHERE token = ?", (token,)).fetchone()
                if not row:
                    return token
        finally:
            conn.close()
    raise RuntimeError("token")


def create_lead(pain: str, lang: str) -> str:
    pain = (pain or "").strip()
    if not pain or len(pain) > PAIN_MAX:
        raise ValueError("pain")
    if lang not in ("ru", "en", "zh"):
        lang = "ru"
    token = new_token()
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO leads (token, pain, lang, status, created) VALUES (?,?,?,?,?)",
                (token, pain, lang, "draft", now),
            )
            conn.commit()
        finally:
            conn.close()
    return token


def get_lead(token: str) -> dict | None:
    if not token:
        return None
    init()
    with _lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT * FROM leads WHERE token = ?", (token,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def active_for_tg(tg_id: int) -> dict | None:
    init()
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM leads WHERE tg_id = ? AND status IN ('started','asking') ORDER BY id DESC LIMIT 1",
                (tg_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def attach_tg(token: str, tg_id: int, username: str, name: str) -> dict | None:
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """UPDATE leads SET tg_id = ?, tg_username = ?, tg_name = ?,
                   status = CASE WHEN status = 'done' THEN status ELSE 'started' END
                   WHERE token = ?""",
                (tg_id, username or "", name or "", token),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM leads WHERE token = ?", (token,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def set_status(token: str, status: str) -> None:
    with _lock:
        conn = _conn()
        try:
            conn.execute("UPDATE leads SET status = ? WHERE token = ?", (status, token))
            conn.commit()
        finally:
            conn.close()


def set_nn(token: str, phase: str, payload: dict | None) -> None:
    if not payload:
        return
    with _lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT nn_json FROM leads WHERE token = ?", (token,)).fetchone()
            blob = {}
            if row and row["nn_json"]:
                try:
                    blob = json.loads(row["nn_json"])
                except json.JSONDecodeError:
                    blob = {}
            blob[phase] = payload
            conn.execute("UPDATE leads SET nn_json = ? WHERE token = ?", (json.dumps(blob, ensure_ascii=False), token))
            conn.commit()
        finally:
            conn.close()


def save_answer(lead_id: int, q_key: str, q_text: str, a_text: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO answers (lead_id, q_key, q_text, a_text, ts) VALUES (?,?,?,?,?)",
                (lead_id, q_key, q_text, a_text, now),
            )
            conn.commit()
        finally:
            conn.close()


def answers_for(lead_id: int) -> list[dict]:
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT q_key, q_text, a_text, ts FROM answers WHERE lead_id = ? ORDER BY id",
                (lead_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def questions() -> list[dict]:
    if not QUESTIONS.exists():
        return []
    try:
        raw = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("questions") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out = []
    for i, item in enumerate(items, 1):
        if isinstance(item, str) and item.strip():
            out.append({"key": f"q{i}", "text": item.strip()})
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            out.append({"key": str(item.get("key") or f"q{i}"), "text": str(item["text"]).strip()})
    return out


def q_label(key: str) -> str:
    return {"who": "Роль", "tried": "Пробовали", "when": "Срок"}.get(key or "", key or "")
