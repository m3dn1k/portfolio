"""Lead funnel: short token, POST draft, /start without token, NN down keeps the row."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bot
import lead
import nn_client
import server


def _tmp() -> Path:
    d = Path(tempfile.mkdtemp())
    lead.DB = d / "leads.db"
    lead.QUESTIONS = d / "bot_questions.json"
    lead.QUESTIONS.write_text('{"questions": []}', encoding="utf-8")
    lead.init()
    return d


def _msg(text: str, tg_id: int = 7, chat_id: int = 7, **extra) -> dict:
    message = {
        "chat": {"id": chat_id},
        "from": {"id": tg_id, "username": "lead", "first_name": "Лид"},
        "text": text,
    }
    message.update(extra)
    return {"message": message}


def main() -> int:
    assert lead.DB == ROOT / "data" / "leads.db"
    _tmp()
    token = lead.new_token()
    assert 1 <= len(token) <= 64, token
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token), token

    os.environ["BOT_USERNAME"] = "ilya_lead_bot"
    code, payload = server.api_lead(json.dumps({"pain": "свожу таблицу руками", "lang": "ru"}))
    assert code == 200, (code, payload)
    assert payload["bot"] == "ilya_lead_bot"
    assert 1 <= len(payload["token"]) <= 64
    row = lead.get_lead(payload["token"])
    assert row and row["status"] == "draft" and row["pain"] == "свожу таблицу руками" and row["tg_id"] is None

    code, err = server.api_lead("{")
    assert code == 400, err
    code, err = server.api_lead(json.dumps({"pain": ""}))
    assert code == 400, err

    sent: list[tuple[int, str]] = []
    noted: list[tuple[int, str]] = []

    def send(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    def notify(chat_id: int, text: str) -> None:
        noted.append((chat_id, text))

    def hu(msg: dict, **kw) -> None:
        bot.handle_update(msg, send=send, notify=notify, **kw)

    sent.clear()
    hu(_msg("/start"), nn=lambda p: (_ for _ in ()).throw(RuntimeError("nn")))
    assert sent and sent[0][1] == bot.NEED_SITE

    sent.clear()
    hu(_msg("старт"), nn=lambda p: None)
    assert sent and sent[0][1] == bot.NEED_SITE

    os.environ["NN_URL"] = "http://127.0.0.1:1"
    assert nn_client.analyze({"lead_id": "x", "problem": "y", "tg": {}, "answers": []}) is None
    tok = lead.create_lead("боль осталась", "ru")
    assert lead.get_lead(tok)
    os.environ["ADMIN_CHAT_ID"] = "99"
    sent.clear()
    noted.clear()
    hu(_msg("/start " + tok), nn=lambda p: None)
    assert lead.get_lead(tok)["status"] == "done"
    assert any(t == bot.GREET for _, t in sent)
    assert any(t == bot.BYE for _, t in sent)
    assert not any(c == 99 for c, t in sent)
    assert any(c == 99 and "нейронка молчит" in t for c, t in noted)
    assert lead.get_lead(tok)["pain"] == "боль осталась"

    trig: list[tuple[int, str]] = []
    bot.handle_trigger_update(_msg("/start", chat_id=77, tg_id=77), send=lambda c, t: trig.append((c, t)))
    assert trig == [(77, "77")]

    def boom(_payload: dict):
        raise RuntimeError("nn down")

    tok2 = lead.create_lead("вторая боль", "ru")
    sent.clear()
    noted.clear()
    hu(_msg("/start " + tok2, tg_id=8, chat_id=8), nn=boom)
    assert lead.get_lead(tok2)["status"] == "done"
    assert lead.get_lead(tok2)["pain"] == "вторая боль"

    lead.QUESTIONS.write_text(
        json.dumps({"questions": [{"key": "who", "text": "Чем занимаетесь?"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    tok3 = lead.create_lead("третья боль", "ru")
    sent.clear()
    noted.clear()
    hu(_msg("/start " + tok3, tg_id=9, chat_id=9), nn=lambda p: (_ for _ in ()).throw(RuntimeError("nn")))
    assert lead.get_lead(tok3)["status"] == "asking"
    assert any(t == "Чем занимаетесь?" for _, t in sent)
    sent.clear()
    noted.clear()
    hu(_msg("пекарня", tg_id=9, chat_id=9), nn=lambda p: {"analytics": "a", "offer": "b"})
    done = lead.get_lead(tok3)
    assert done["status"] == "done"
    ans = lead.answers_for(done["id"])
    assert ans and ans[0]["a_text"] == "пекарня"
    assert any("Аналитика: a" in t for _, t in noted)
    assert any("Роль: пекарня" in t for _, t in noted)
    assert not any("Чем занимаетесь?" in t for _, t in noted)
    assert not any("Что предложить:" in t for _, t in noted)
    assert not any("Аналитика: a" in t for _, t in sent)

    stubs = json.loads((ROOT / "bot_questions.json").read_text(encoding="utf-8"))
    assert len(stubs["questions"]) == 3
    lead.QUESTIONS.write_text(json.dumps(stubs, ensure_ascii=False), encoding="utf-8")

    def nn_round(payload: dict) -> dict:
        return {"analytics": "итог %d" % len(payload.get("answers") or [])}

    tok4 = lead.create_lead("три ответа", "ru")
    sent.clear()
    noted.clear()
    hu(_msg("/start " + tok4, tg_id=10, chat_id=10), nn=nn_round)
    assert lead.get_lead(tok4)["status"] == "asking"
    user_out = [t for _, t in sent]
    replies = ["владелец", "-", "через неделю"]
    for i, a in enumerate(replies, 1):
        sent.clear()
        noted.clear()
        hu(_msg(a, tg_id=10, chat_id=10), nn=nn_round)
        user_out.extend(t for _, t in sent)
        row = lead.get_lead(tok4)
        if i < 3:
            assert row["status"] == "asking", row
        else:
            assert row["status"] == "done", row
    ans = lead.answers_for(lead.get_lead(tok4)["id"])
    assert [x["a_text"] for x in ans] == replies
    blob = json.loads(lead.get_lead(tok4)["nn_json"] or "{}")
    assert "start" not in blob
    assert "итог 3" in (blob.get("done") or {}).get("analytics", "")
    assert any("Аналитика: итог 3" in t for _, t in noted)
    assert any("Роль: владелец" in t and "Пробовали: -" in t and "Срок: через неделю" in t for _, t in noted)
    assert not any("Кто вы в компании" in t for _, t in noted)
    assert not any("Что предложить:" in t for _, t in noted)
    assert not any(c == 99 for c, t in sent)
    assert not any("Аналитика:" in t or "Что предложить:" in t for t in user_out)

    assert lead.q_label("who") == "Роль" and lead.q_label("tried") == "Пробовали" and lead.q_label("when") == "Срок"

    os.environ["OLLAMA_URL"] = "http://127.0.0.1:1"
    code, out = server.api_nn("{")
    assert code == 400, out
    code, out = server.api_nn(json.dumps({"problem": "x", "answers": []}))
    assert code == 200 and out == {"analytics": ""}, out

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore and "leads.db" in gitignore
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "BOT_TOKEN=" in example and "TRIGGER_BOT_TOKEN=" in example and "ADMIN_CHAT_ID=" in example
    assert "NN_URL=" in example and "OLLAMA_URL=" in example and "NN_MODEL=" in example

    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
