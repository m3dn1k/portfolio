"""Telegram lead bot + send-only trigger bot for lead packets."""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request

import lead
import nn_client

GREET = "Здравствуйте, это бот Ильи, давайте проясним пару моментов насчет вашей ситуации."
BYE = "Спасибо. В течение часа я с вами свяжусь."
NEED_SITE = "Чтобы начать, отправьте задачу через форму на сайте."
API = "https://api.telegram.org/bot"


def _token() -> str:
    return (os.environ.get("BOT_TOKEN") or "").strip()


def _trigger_token() -> str:
    return (os.environ.get("TRIGGER_BOT_TOKEN") or "").strip()


def _send_with(tok: str, chat_id: int, text: str) -> None:
    if not tok or not text:
        lead.log.warning("send skip chat=%s empty tok or text", chat_id)
        return
    body = json.dumps({"chat_id": chat_id, "text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API + tok + "/sendMessage",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        lead.log.warning("send fail chat=%s %s", chat_id, exc)


def telegram_send(chat_id: int, text: str) -> None:
    _send_with(_token(), chat_id, text)


def trigger_send(chat_id: int, text: str) -> None:
    _send_with(_trigger_token(), chat_id, text)


def _api(tok: str, method: str, payload: dict) -> dict | None:
    if not tok:
        return None
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API + tok + "/" + method,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _from_user(msg: dict) -> tuple[int, str, str]:
    u = msg.get("from") or {}
    tg_id = int(u.get("id") or msg.get("chat", {}).get("id") or 0)
    username = str(u.get("username") or "")
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()
    return tg_id, username, name


def _nn_payload(row: dict) -> dict:
    ans = lead.answers_for(row["id"])
    return {
        "lead_id": row["token"],
        "problem": row["pain"],
        "tg": {
            "id": row["tg_id"],
            "username": row["tg_username"] or "",
            "name": row["tg_name"] or "",
        },
        "answers": [{"key": a["q_key"], "q": lead.q_label(a["q_key"]), "a": a["a_text"]} for a in ans],
    }


def _run_nn(row: dict, phase: str, nn) -> dict | None:
    try:
        out = nn(_nn_payload(row))
    except Exception as exc:
        lead.log.warning("nn crash token=%s %s", row.get("token"), exc)
        return None
    lead.set_nn(row["token"], phase, out)
    if out and out.get("analytics"):
        lead.log.info("nn token=%s analytics=%s", row["token"], out.get("analytics"))
    else:
        lead.log.info("nn token=%s silent", row["token"])
    return out


def _nn_blob(row: dict) -> dict:
    if not row.get("nn_json"):
        return {}
    try:
        data = json.loads(row["nn_json"])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _admin_text(row: dict, answers: list[dict]) -> str:
    name = row.get("tg_name") or ""
    user = row.get("tg_username") or ""
    handle = ("@" + user) if user else "без username"
    lines = [
        "Новый лид",
        f"TG: {name} {handle} id={row.get('tg_id')}",
        f"Проблема: {row.get('pain')}",
    ]
    for a in answers:
        lines.append(f"{lead.q_label(a['q_key'])}: {a['a_text']}")
    blob = _nn_blob(lead.get_lead(row["token"]) or row)
    nn = blob.get("done") or blob.get("start")
    if isinstance(nn, dict) and nn.get("analytics"):
        lines.append("Аналитика: " + str(nn["analytics"]))
    else:
        lines.append("нейронка молчит, сырой лид")
    return "\n".join(lines)


def _ask_or_finish(row: dict, chat_id: int, send, notify, nn) -> None:
    qs = lead.questions()
    got = lead.answers_for(row["id"])
    if len(got) < len(qs):
        q = qs[len(got)]
        lead.set_status(row["token"], "asking")
        lead.log.info("ask token=%s key=%s", row["token"], q["key"])
        send(chat_id, q["text"])
        return
    lead.set_status(row["token"], "done")
    send(chat_id, BYE)
    _run_nn(row, "done", nn)
    packet = _admin_text(row, lead.answers_for(row["id"]))
    lead.log.info("done token=%s\n%s", row["token"], packet)
    admin = (os.environ.get("ADMIN_CHAT_ID") or "").strip()
    if admin:
        lead.log.info("admin send chat=%s token=%s", admin, row["token"])
        notify(int(admin), packet)
    else:
        lead.log.warning("admin skip token=%s ADMIN_CHAT_ID empty", row["token"])


def _start(token: str, msg: dict, send, notify, nn) -> None:
    chat_id = int(msg["chat"]["id"])
    if not token:
        lead.log.info("start no token chat=%s", chat_id)
        send(chat_id, NEED_SITE)
        return
    row = lead.get_lead(token)
    if not row:
        lead.log.info("start unknown token=%s chat=%s", token, chat_id)
        send(chat_id, NEED_SITE)
        return
    if row["status"] == "done":
        lead.log.info("start already done token=%s chat=%s", token, chat_id)
        send(chat_id, BYE)
        return
    tg_id, username, name = _from_user(msg)
    row = lead.attach_tg(token, tg_id, username, name) or row
    lead.log.info("start token=%s tg=%s @%s status=%s", token, tg_id, username, row.get("status"))
    send(chat_id, GREET)
    _ask_or_finish(row, chat_id, send, notify, nn)


def _answer_text(msg: dict) -> str:
    contact = msg.get("contact") or {}
    if contact.get("phone_number"):
        phone = str(contact["phone_number"])
        who = str(contact.get("first_name") or "").strip()
        return (who + " " + phone).strip()
    return str(msg.get("text") or "").strip()


def parse_cmd(text: str) -> tuple[str, str]:
    t = (text or "").strip()
    if not t:
        return "empty", ""
    low = t.lower()
    if low == "/id" or low.startswith("/id@"):
        return "id", ""
    if low.startswith("/start"):
        return "start", t[6:].strip()
    if low.startswith("старт"):
        return "start", t[5:].strip()
    if low.startswith("start") and (len(t) == 5 or t[5:6].isspace()):
        return "start", t[5:].strip()
    return "text", t


def handle_update(update: dict, send=telegram_send, notify=trigger_send, nn=nn_client.analyze) -> None:
    msg = update.get("message") or update.get("edited_message") or {}
    if not msg or not msg.get("chat"):
        return
    chat_id = int(msg["chat"]["id"])
    text = str(msg.get("text") or "")
    kind, arg = parse_cmd(text)
    if kind == "id":
        send(chat_id, str(chat_id))
        return
    if kind == "start":
        _start(arg, msg, send, notify, nn)
        return
    body = _answer_text(msg)
    if not body:
        return
    tg_id, _, _ = _from_user(msg)
    row = lead.active_for_tg(tg_id)
    if not row:
        lead.log.info("answer no active lead tg=%s", tg_id)
        send(chat_id, NEED_SITE)
        return
    qs = lead.questions()
    got = lead.answers_for(row["id"])
    if len(got) >= len(qs):
        _ask_or_finish(row, chat_id, send, notify, nn)
        return
    q = qs[len(got)]
    lead.log.info("answer token=%s key=%s text=%s", row["token"], q["key"], body[:160])
    lead.save_answer(row["id"], q["key"], q["text"], body)
    _ask_or_finish(row, chat_id, send, notify, nn)


def handle_trigger_update(update: dict, send=trigger_send) -> None:
    msg = update.get("message") or {}
    if not msg or not msg.get("chat"):
        return
    kind, _ = parse_cmd(str(msg.get("text") or ""))
    if kind not in ("id", "start"):
        return
    chat_id = int(msg["chat"]["id"])
    lead.log.info("trigger id chat=%s", chat_id)
    send(chat_id, str(chat_id))


def _poll_forever(tok: str, handler, label: str) -> None:
    offset = 0
    lead.log.info("%s polling", label)
    while True:
        data = _api(tok, "getUpdates", {"timeout": 50, "offset": offset, "allowed_updates": ["message"]})
        if not data or not data.get("ok"):
            continue
        for upd in data.get("result") or []:
            offset = max(offset, int(upd.get("update_id") or 0) + 1)
            try:
                handler(upd)
            except Exception as exc:
                lead.log.exception("%s update failed %s", label, exc)


def poll() -> None:
    lead.load_dotenv()
    lead.init()
    lead.setup_log("bot")
    if not _token():
        raise SystemExit("BOT_TOKEN empty")
    trig = _trigger_token()
    if trig:
        threading.Thread(
            target=_poll_forever,
            args=(trig, handle_trigger_update, "trigger"),
            daemon=True,
        ).start()
    _poll_forever(_token(), handle_update, "lead")


if __name__ == "__main__":
    poll()
