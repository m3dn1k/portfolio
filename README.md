# site

Живая версия: [https://m3dn1k.tech](https://m3dn1k.tech)

Личный сайт Ильи Медникова: автоматизация процессов, форма заявки и Telegram-бот, который уточняет задачу и присылает разбор. По желанию лид разбирает локальная модель через Ollama.

Стек: Python 3 (только стандартная библиотека), HTML/CSS/JS, Telegram Bot API, SQLite, Ollama.

## Запуск

1. Скопируйте `.env.example` в `.env` и заполните токены ботов и `ADMIN_CHAT_ID`.
2. `python server.py` поднимает сайт на [http://127.0.0.1:8790/](http://127.0.0.1:8790/).
3. `python bot.py` запускает бота заявок (и отдельного бота для пакетов администратору, если задан `TRIGGER_BOT_TOKEN`).

Файл `.env` и база `data/leads.db` в git не попадают. В `.env.example` только пустые ключи.

## Тесты

```bash
python tests/test_i18n.py
python tests/test_lead.py
python tests/test_live.py
python tests/test_layout.py
```

`test_layout.py` гоняет живую страницу в Chrome или Edge: телефон, планшет, 16:9 и широкий экран.

## Кейсы на сайте

- Диагностический модуль рабочих мест (desktop и portable): текст и скриншоты интерфейса на главной.
- [JobHunter](https://github.com/m3dn1k/jobhunter): Telegram-бот подбора вакансий.
- [tg-channel-assistant](https://github.com/m3dn1k/tg-channel-assistant): бот, который отвечает на вопросы по постам канала.

## License

MIT. Copyright (c) 2026 Ilya Mednikov.

---

Live site: https://m3dn1k.tech. Personal site of Ilya Mednikov: process automation, a lead form and a Telegram bot, with an optional local LLM via Ollama. Copy `.env.example` to `.env`, run `python server.py` and `python bot.py`. Do not commit `.env` or `data/leads.db`.
