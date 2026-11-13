"""Fail if i18n keys drift or dark theme sneaks back."""
from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parent.parent
html = (root / "index.html").read_text(encoding="utf-8")
js = (root / "i18n.js").read_text(encoding="utf-8")
css = (root / "styles.css").read_text(encoding="utf-8")


def keys_for(lang: str) -> set[str]:
    m = re.search(rf"\b{lang}:\s*\{{(.*?)\n  \}}", js, re.S)
    assert m, f"missing {lang} block"
    return set(re.findall(r"^\s+(\w+):", m.group(1), re.M))


def main() -> int:
    assert "theme-toggle" not in html, "dark toggle still in html"
    assert "[data-theme" not in css, "dark theme tokens still in css"
    assert "#f3eee4" in css, "milk beige backup missing"
    assert "#e6ebf1" in css, "gray-blue token missing"
    assert "#c8d0db" in css
    # Em dash only in the RU hero: "Я — Илья Медников,"
    assert html.count("—") == 1 and "Я&nbsp;— " in html
    assert js.count("—") == 1 and "Я\\u00a0— " in js
    assert "–" not in html and "–" not in js

    ru, en, zh = keys_for("ru"), keys_for("en"), keys_for("zh")
    assert ru == en == zh, (sorted(ru - en), sorted(en - zh), sorted(zh - ru))

    html_keys = set(re.findall(r'data-i18n(?:-alt|-aria|-placeholder)?="([^"]+)"', html))
    missing = html_keys - ru
    assert not missing, missing

    assert "try-form" in html
    assert "novalidate" in html
    assert "try-err" in html
    assert "tryErr" in js
    assert "try-label" not in html
    assert "Временная заглушка, автор лень" in html and "Временная заглушка, автор лень" in js
    assert "поле не должно быть пустым" not in html and "поле не должно быть пустым" not in js
    assert "Temporary placeholder, the author got lazy" in js
    assert "临时占位，作者偷懒了" in js
    assert "Напиши, что уже достало" not in html and "Напиши, что уже достало" not in js
    assert "try-err-bang" in html
    assert html.find('class="try-field"') < html.find("try-err") < html.find("</form>")
    assert "setTimeout(hideErr, 1000)" in html
    assert "fade ? 4000 : 5000" in html
    assert "is-fade" in html
    assert "is-fade" in css
    assert "Заполните это поле" not in html
    assert "заполните данные" not in js
    assert "case-metrics" in html
    assert html.find("</figure>") < html.find('class="case-copy"') < html.find('class="case-metrics"')
    assert 'class="metrics"' not in html
    assert html.count("img/case1-") == 1
    assert "case1-1.png" not in html and "case1-2.png" in html
    assert (root / "img" / "case1-2.png").is_file()
    assert "case-dots" not in html
    assert 'data-shots>' not in html and "data-shots=" not in html
    assert "case1alt3" not in js
    assert "Разработал диагностический модуль" in js
    assert "desktop и portable" in js
    assert "на подпись с клиентом" in html and "на подпись с клиентом" in js
    assert "case1p1" not in js and "case1p5" not in js
    assert "case-points" not in html and "case-points" not in css
    assert "case-shot-photo" in html
    assert "case-shot-ui" not in html
    assert "case1when" not in html and "case1when" not in js
    assert "case-when" not in html and "case-when" not in css
    assert "margin-top: auto" in css
    assert "aspect-ratio: 4 / 3" in css
    assert "align-self: start" in css
    assert "align-items: stretch" in css.split(".case-top {", 2)[-1][:200]
    assert "min-width: 0" in css
    assert "x10" not in js and "x10" not in html
    assert "< 10 мес." not in js and "&lt; 10 мес." not in html
    assert "сис. админов" not in js
    assert "case1m1v" not in js and "case1m2v" not in js
    assert "case1alt1" not in js and "case1alt1" not in html
    assert 'data-i18n="case1ndaA"' in html and 'data-i18n="case1ndaB"' in html
    assert "case-nda-ico" in html
    assert "Информация под NDA" in html and "Подробности на созвоне" in html
    assert "Информация под NDA" in js and "Подробности на созвоне" in js
    assert "Under NDA" in js and "Details on a call" in js
    assert "相关信息受保密协议约束" in js and "详情可在通话中沟通" in js
    assert "90%" not in js and "42 ч" not in js
    assert "30 компаний" not in js
    assert "case-dots button" not in html
    assert "case1dot" not in js and "case1shots" not in js
    assert ", 3000)" not in html
    assert "4500" not in html
    assert "x5" not in html and "SaaS" not in html and "Saas" not in html
    assert "Разработала CRM" not in html
    assert "СТЕК" not in html and "STECK" not in html

    assert "Мой гитхаб" in html
    assert "Обсудить проект" not in html
    assert "Заказать проект" not in html
    assert "Захотели обсудить со мной проект" not in html and "Захотели обсудить со мной проект" not in js
    assert "Wanted to talk about a project" not in js
    assert "想跟我谈项目" not in js
    assert "Заценили мой гитхаб" in html and "Заценили мой гитхаб" in js
    assert "Checked out my GitHub" in js
    assert "浏览过我的 GitHub" in js
    assert 'class="live"' in html
    assert 'data-live="wink"' in html
    assert html.find('class="live"') < html.find("</footer>")
    assert html.find("hero-side") < html.find('class="live"')
    assert "position: fixed" not in css.split(".live {", 1)[1][:200]
    nav = css.split(".nav {", 1)[1][:280]
    assert "position: sticky" in nav and "top: 0" in nav
    assert "#eef2f6" in nav
    assert 'class="wrap nav-in"' in html
    assert "scrollbar-width: thin" in css
    assert "::-webkit-scrollbar-button" in css
    assert "@supports not selector(::-webkit-scrollbar)" in css
    assert css.count("#7a8592") >= 2
    assert "::-webkit-scrollbar-thumb" in css
    thumb = css.split("::-webkit-scrollbar-thumb {", 1)[1][:120]
    assert "#7a8592" in thumb
    assert "var(--line)" not in thumb
    assert "liveKicker" in js
    assert "fact1a" in js and "fact1b" in js
    assert 'fill="#f4f7fa"' in html and "M16 2a14 14 0 1 0 0 28" in html
    assert 'data-i18n="fact1"' not in html
    assert "grid-area: note" in css
    assert "ai-note" in html
    assert "white-space: pre-line" in css
    assert "\\nКроме меня. Я настоящий." in js
    assert "\\nКроме меня.\\n" not in js

    hrefs = re.findall(r'class="pill[^"]*" href="([^"]+)"', html)
    assert hrefs == ["tg://resolve?domain=m3dn1kkk", "https://github.com/m3dn1k"], hrefs
    assert "https://t.me/" not in html
    assert "tg://resolve?domain=m3dn1kkk&text=" not in html
    assert 'fetch("/api/lead"' in html
    assert 'action="/api/lead"' in html

    assert "repeat(auto-fit" in css
    assert "avatar-eye" not in html and "avatar-pupil" not in html
    assert "avatar-eye" not in css and "avatar-pupil" not in css
    assert "resize: none" in css
    assert "::-webkit-resizer" in css
    assert "Бот задаст пару вопросов" in js
    assert "в течение часа" in js
    assert "втечение" not in js
    assert "try-mic" in html
    assert "try-send" in html
    assert "try-note" not in html
    assert "tryNote" not in js
    assert html.find("try-form") < html.find("try-kit")
    assert "workTitle" not in html and "workTitle" not in js
    assert "Мои топовые решения" not in html
    assert "work-photo" not in html
    assert "case1lead" in js
    assert "case1t" not in js
    assert "bench.png" not in html
    assert "Часто бывает так" in html
    assert "Уже делал" not in html
    assert "tryHit1p" in js
    assert "calc(100% - 48px)" in css
    assert "calc(100% - 96px)" in css
    assert "SpeechRecognition" in html
    qjson = (root / "bot_questions.json").read_text(encoding="utf-8")
    assert "—" not in qjson and "–" not in qjson
    assert len(json.loads(qjson)["questions"]) == 3
    assert "/api/nn" in (root / "server.py").read_text(encoding="utf-8")
    assert "object-fit: cover" in css.split(".case-shots img {", 1)[1].split("}", 1)[0]
    assert 'href="styles.css?v=114"' in html
    faces = set(re.findall(r'font-family: "([^"]+)"', css.split(":root", 1)[0]))
    assert faces == {"Manrope Variable", "IBM Plex Mono"}, faces
    assert "YaHei" not in css and "PingFang" not in css
    assert "fact-scribble-stars" not in html and "fact-scribble-stars" not in css
    assert "i18n.js?v=68" in html
    assert "tryApiErr" in js
    assert "showErr(true)" in html
    assert "base = pain.value" in html
    assert 'send.setAttribute("aria-busy", "true")' in html
    assert "document.hidden) clearInterval(timer)" not in html
    assert 'fact1b: "2025"' in js
    assert "2024" not in js and ">2024<" not in html
    assert "case-shot-ui" not in html
    assert "border-radius: inherit" not in css.split(".case-shots img {", 1)[1].split("}", 1)[0]
    from PIL import Image
    import numpy as np
    shot = np.array(Image.open(root / "img" / "case1-2.png").convert("RGB"))
    assert shot.shape[0] * 4 == shot.shape[1] * 3, shot.shape
    rowdiff = np.abs(shot[-40:].astype(np.int16) - shot[-41:-1].astype(np.int16)).mean()
    assert rowdiff > 0.5, rowdiff
    assert (shot[:280, :280].max(axis=2) < 18).sum() < 80
    assert "background: #cdd2dd" in css
    assert "padding: 6%" not in css
    assert "me-stage" in html
    assert html.count("me-cell") == 4
    assert "me-ico" not in html
    assert html.count("me-mark") == 4
    assert "to-top" not in html and "Наверх" not in html
    assert "toStars" in js and "через тернии к звездам" in html
    assert "stack-tag" not in html
    assert "Инструменты, не витрина" not in html and "Инструменты, не витрина" not in js
    assert "Tools, not a showcase" not in js and "不是橱窗" not in js
    assert "fact-scribble" not in html
    assert 'data-i18n="liveKicker"' in html and "Сколько:" not in html
    assert "<h2" in html and "live-kicker" in html
    assert "live.js?v=2" in html
    assert "nav-menu" in html and "nav-burger" in html
    assert "hero-intro" in html
    assert "data-reveal" in html
    assert "js-reveal" in css
    assert "unobserve" not in html
    assert "atEnd" in html and "scrollHeight" in html
    assert 'class="hero-side" data-reveal' not in html
    assert 'class="hero-facts" data-reveal' not in html
    assert 'class="foot wrap" data-reveal' not in html
    assert "me-motto" in html
    assert html.find("me1t") < html.find("me1b") < html.find("me1m")
    assert html.find("me1m") < html.find("me2t") < html.find("me3t") < html.find("me4t")
    assert "me4t" in js
    assert "Ответственность" in html
    assert "Если я пообещал" in js
    assert "meSlotT" not in html
    assert "meSlotT" not in js
    assert "me3t" in js
    assert "Тайм-менеджмент" in html
    assert "приоритизировать" in js
    assert "приоретезировать" not in html and "приоретезировать" not in js
    assert "me2t" in js
    assert "Работа в команде" in html
    assert "слушать и быть услышанным" in js
    assert "me1t" in js
    assert "Коммуникация" in html
    assert "человеки человечатся" in js
    assert "селовеки" not in html and "селовеки" not in js
    assert "me-cut" not in html
    assert "img/me.png" not in html
    assert not (root / "img" / "me.png").exists()
    assert "meAlt" not in js
    assert "Приоритизация" not in html

    assert "github.com/m3dn1k/jobhunter" in html
    assert "github.com/m3dn1k/tg-channel-assistant" in html
    assert "case2link" not in js and "case3link" not in js
    assert "case2body" not in js and "case3body" not in js
    assert "case2alt1" not in js and "case3alt1" not in js
    assert "Код на GitHub" not in html and "Код на GitHub" not in js
    assert "case-link" not in html
    assert "case-gh" in html and "caseGh" in js
    assert "GitHub →" in html and "GitHub →" in js
    assert "case2lead" in js and "case3lead" in js
    assert "case2m1v" in js and "case3m1v" in js
    assert "Сделал бота под поиск работы" in html
    assert "Собрал бота по архиву канала" in html
    assert "img/case2-1.png" not in html and "img/case3-1.png" not in html
    assert not (root / "img" / "case2-1.png").exists()
    assert not (root / "img" / "case3-1.png").exists()
    assert html.count("case-plain") == 2
    assert html.count('class="case-top"') + html.count('class="case-top ') == 3 or html.count("case-top") == 3
    assert html.count('class="case') >= 3

    print("ok", len(ru), "keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
