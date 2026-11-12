"""Static site + public live counters + lead drafts. Stdlib only."""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import lead

ROOT = Path(__file__).resolve().parent
STATS = lead.DATA / "stats.json"
KEYS = ("visits", "invite", "project", "wink")
_lock = threading.Lock()
lead.load_dotenv()


def empty() -> dict[str, int]:
    return {k: 0 for k in KEYS}


def load() -> dict[str, int]:
    if not STATS.exists():
        return empty()
    try:
        raw = json.loads(STATS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty()
    return {k: int(raw.get(k, 0) or 0) for k in KEYS}


def save(data: dict[str, int]) -> None:
    STATS.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATS)


def bump(key: str) -> dict[str, int]:
    if key not in KEYS:
        raise ValueError(key)
    with _lock:
        data = load()
        data[key] += 1
        save(data)
        return dict(data)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/stats":
            with _lock:
                self._json(200, load())
            return
        if path.startswith("/data/") or path.endswith((".py", ".db", ".env")):
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        n = int(self.headers.get("Content-Length") or 0)
        limit = 32768 if path == "/api/nn" else 4096
        if n > limit:
            self._json(413, {"error": "too big"})
            return
        raw = self.rfile.read(max(n, 0)).decode("utf-8", "replace") if n else ""
        if path == "/api/lead":
            code, payload = api_lead(raw)
            self._json(code, payload)
            return
        if path == "/api/nn":
            code, payload = api_nn(raw)
            self._json(code, payload)
            return
        if path != "/api/hit":
            self.send_error(404)
            return
        key = ""
        try:
            key = str((json.loads(raw) or {}).get("k") or "")
        except json.JSONDecodeError:
            self._json(400, {"error": "bad json"})
            return
        try:
            self._json(200, bump(key))
        except ValueError:
            self._json(400, {"error": "bad key"})


def api_lead(raw: str) -> tuple[int, dict]:
    try:
        body = json.loads(raw or "") or {}
    except json.JSONDecodeError:
        return 400, {"error": "bad json"}
    if not isinstance(body, dict):
        return 400, {"error": "bad json"}
    bot = lead.bot_username()
    if not bot:
        lead.log.warning("form 503 bot unset")
        return 503, {"error": "bot unset"}
    try:
        token = lead.create_lead(str(body.get("pain") or ""), str(body.get("lang") or "ru"))
    except ValueError:
        lead.log.warning("form 400 bad pain")
        return 400, {"error": "bad pain"}
    lead.log.info("form token=%s bot=%s lang=%s pain=%s", token, bot, body.get("lang") or "ru", body.get("pain"))
    return 200, {"token": token, "bot": bot}


NN_SYS = """Ты разбираешь лид. Верни JSON с полем analytics.
Пиши только по-русски. Не цитируй инструкцию. Не копируй одно поле в analytics.
analytics: роль, боль, срок, красные флаги. 4-6 коротких предложений. Без оффера и без прайса.

Пример 1
Проблема: каждую пятницу руками свожу одну таблицу
Роль: владелец
Пробовали: макросы, не взлетело
Срок: на этой неделе
{"analytics":"Владелец. Ручная сверка каждую пятницу. Срок эта неделя. Макросы уже жгли. Красный флаг: процесс живой, софт пробовали."}

Пример 2
Проблема: слишком долго реагируем на проблему на клиентском сайте
Роль: менеджер
Пробовали: -
Срок: по-хорошему завтра
{"analytics":"Менеджер, скорее не ЛПР. Боль: медленная реакция на косяки сайта. Ничего не пробовали. Ждёт завтра, можно чуть позже. Красный флаг: без того кто платит срок из пальца."}

Пример 3
Проблема: заявки из Telegram руками переношу в таблицу
Роль: техдир
Пробовали: zapier, отвалился
Срок: через месяц
{"analytics":"Техдир. Ручной перенос заявок из Telegram в таблицу. Zapier уже сгорел. Срок месяц, не горит. Красный флаг: интеграция, не просто бот."}"""
OLLAMA_TIMEOUT = 90


def _ollama_url() -> str:
    return (os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")


def _nn_model() -> str:
    return (os.environ.get("NN_MODEL") or "qwen2.5:3b").strip()


def _json_obj(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        if i < 0 or j <= i:
            return None
        try:
            data = json.loads(text[i : j + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _ask_ollama(payload: dict) -> dict:
    empty = {"analytics": ""}
    model = _nn_model()
    if not model:
        return empty
    pain = str(payload.get("problem") or "").strip()
    answers = payload.get("answers") if isinstance(payload.get("answers"), list) else []
    lines = ["Проблема: " + (pain or "нет")]
    for item in answers:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        q = lead.q_label(key) or str(item.get("q") or "").strip()
        a = str(item.get("a") or "").strip()
        if a:
            lines.append((q + ": " if q else "") + a)
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": NN_SYS},
                {"role": "user", "content": "\n".join(lines)},
            ],
            "options": {"temperature": 0.2, "num_predict": 400},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        _ollama_url() + "/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        lead.log.warning("ollama fail model=%s %s", model, exc)
        return empty
    outer = _json_obj(raw)
    if not outer:
        lead.log.warning("ollama bad json model=%s", model)
        return empty
    msg = outer.get("message") if isinstance(outer.get("message"), dict) else {}
    data = _json_obj(str(msg.get("content") or "")) or empty
    analytics = str(data.get("analytics") or "").strip()
    if analytics:
        lead.log.info("ollama model=%s analytics=%s", model, analytics)
    else:
        lead.log.info("ollama model=%s empty", model)
    return {"analytics": analytics}


def api_nn(raw: str) -> tuple[int, dict]:
    try:
        body = json.loads(raw or "") or {}
    except json.JSONDecodeError:
        return 400, {"error": "bad json"}
    if not isinstance(body, dict):
        return 400, {"error": "bad json"}
    return 200, _ask_ollama(body)


def main() -> None:
    lead.setup_log("http")
    port = 8790
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    lead.log.info("http://127.0.0.1:%s/", port)
    print(f"http://127.0.0.1:{port}/", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
