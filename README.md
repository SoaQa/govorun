# Govorun

Telegram-бот для пересылки сообщений пользователей автору через webhook.

## Архитектура

```
Telegram → HTTPS → Nginx (TLS) → Bot (Flask/gunicorn) → Telegram API
                                    ↕            ↕
                                 Postgres      Redis
```

- **Bot** — Python + pyTelegramBotAPI, webhook-режим, Flask + gunicorn
- **Postgres** — хранение пользователей и лога сообщений
- **Redis** — rate limiting (1 сообщение в час)
- **Nginx** — TLS termination + reverse proxy

## Структура проекта

```
.
├── docker-compose.yml
├── .env.example
├── nginx/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── conf.d/
│       └── bot.conf
├── certs/                  # TLS-сертификаты (volume)
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   └── src/
│       ├── main.py
│       ├── wsgi.py
│       ├── config.py
│       ├── logging.py
│       ├── bot/
│       │   ├── handlers.py
│       │   ├── keyboards.py
│       │   ├── states.py
│       │   └── webhook_server.py
│       ├── storage/
│       │   ├── db.py
│       │   ├── models.py
│       │   ├── repo.py
│       │   └── migrations/
│       └── services/
│           ├── rate_limit.py
│           └── author_notify.py
└── volumes/                # данные Postgres и Redis (не в git)
```

## Быстрый старт

### 1. Подготовка

```bash
# Скопировать и заполнить переменные окружения
cp .env.example .env
# Отредактировать .env — BOT_TOKEN, AUTHOR_CHAT_ID, WEBHOOK_DOMAIN и т.д.
```

### 2. TLS-сертификаты

Положить сертификаты в `certs/`:

```bash
certs/fullchain.pem
certs/privkey.pem
```

Или использовать Let's Encrypt / certbot.

### 3. Запуск

```bash
docker compose up --build -d
```

Проверить:

```bash
# Логи бота
docker compose logs -f bot

# Healthcheck
curl http://localhost:8080/health
```

### 4. Миграции (Alembic)

```bash
# Внутри контейнера бота
docker compose exec bot alembic upgrade head

# Создать новую миграцию
docker compose exec bot alembic revision --autogenerate -m "description"
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Токен Telegram-бота | — (обязательно) |
| `WEBHOOK_DOMAIN` | Домен для webhook | — (обязательно) |
| `WEBHOOK_PATH` | Путь webhook (секретный) | `webhook/secret-path` |
| `WEBHOOK_SECRET_TOKEN` | Secret token для верификации запросов | — |
| `ADMIN_ID` | Telegram ID администратора | — (обязательно) |
| `NOTIFY_MODE` | Режим пересылки: `admin` / `group` / `both` | `admin` |
| `GROUP_CHAT_ID` | Chat ID группы (обязательно при `group`/`both`; узнать через `/getid`) | — |
| `POSTGRES_DSN` | DSN подключения к Postgres | `postgresql+psycopg://govorun:changeme@postgres:5432/govorun` |
| `REDIS_DSN` | DSN подключения к Redis | `redis://redis:6379/0` |
| `RATE_LIMIT_SECONDS` | Интервал rate limit (сек) | `3600` |
| `MAX_MESSAGE_LENGTH` | Макс. длина сообщения | `2000` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `APP_HOST` | Хост внутреннего сервера | `0.0.0.0` |
| `APP_PORT` | Порт внутреннего сервера | `8080` |

## Обслуживание

### Обновление

```bash
git pull
docker compose up --build -d
```

### Бэкап Postgres

```bash
docker compose exec postgres pg_dump -U govorun govorun > backup_$(date +%Y%m%d).sql
```

### Восстановление

```bash
cat backup.sql | docker compose exec -T postgres psql -U govorun govorun
```

### Логи

```bash
# Все сервисы
docker compose logs -f

# Только бот
docker compose logs -f bot
```
