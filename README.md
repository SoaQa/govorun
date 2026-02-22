# Govorun

Telegram-бот обратной связи: пользователи пишут боту, сообщения пересылаются администратору (в ЛС, в группу или и туда, и туда). Администратор может отвечать пользователям и блокировать их — всё прямо из Telegram.

## Возможности

### Для пользователей

- `/start` — приветствие и кнопка «✉️ Написать автору»
- Нажатие кнопки переводит бота в режим ожидания текста
- Сообщение валидируется (не пустое, не длиннее `MAX_MESSAGE_LENGTH` символов) и пересылается администратору
- Rate limit — не более одного сообщения в час (настраивается через `RATE_LIMIT_SECONDS`)
- Заблокированные пользователи получают отказ при попытке написать

### Для администратора

- **Ответ пользователю** — ответить (reply) на пересланное сообщение в ЛС с ботом, текст уйдёт обратно пользователю
- `/ban` — ответить на пересланное сообщение командой `/ban` (работает и в ЛС, и в группе) — пользователь блокируется
- `/unban` — аналогично, разблокировка
- `/getid` — показывает ID и тип текущего чата (работает в ЛС, группе, супергруппе). Удобно для получения `GROUP_CHAT_ID`
- Администратор не ограничен rate limit'ом

### Режимы пересылки (`NOTIFY_MODE`)

| Режим | Куда пересылаются сообщения |
|---|---|
| `admin` | Только в ЛС администратору (`ADMIN_ID`) |
| `group` | Только в группу (`GROUP_CHAT_ID`) |
| `both` | И в ЛС, и в группу одновременно |

При режиме `both` сообщение считается доставленным, если дошло хотя бы до одного адресата.

### Маппинг сообщений

Бот запоминает связь «пересланное сообщение → пользователь» в Redis (TTL 30 дней). Благодаря этому администратор может ответить на любое пересланное сообщение, и ответ уйдёт именно тому пользователю. `/ban` и `/unban` тоже работают через reply на пересланное сообщение.

### Хранение данных

- **PostgreSQL** — таблицы `users` (telegram_id, username, is_blocked, ...) и `author_messages` (текст, статус доставки, ошибки)
- **Redis** — rate limiting (`SET NX EX`), маппинг пересланных сообщений

## Архитектура

```
Telegram → HTTPS:8443 → Nginx (TLS) → Bot (Flask/gunicorn:8080) → Telegram API
                                          ↕              ↕
                                       Postgres         Redis
```

- **Bot** — Python 3.12 + pyTelegramBotAPI, webhook-режим, Flask + gunicorn
- **Postgres 16** — пользователи и лог сообщений
- **Redis 7** — rate limit + маппинг feedback-сообщений
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
│       ├── main.py          # точка входа, инициализация
│       ├── wsgi.py           # WSGI entrypoint для gunicorn
│       ├── config.py         # Pydantic Settings (env override)
│       ├── logging.py        # единый логгер
│       ├── bot/
│       │   ├── handlers.py   # все хендлеры бота
│       │   ├── keyboards.py  # клавиатуры
│       │   ├── messages.py   # все тексты (русский)
│       │   ├── states.py     # FSM (idle / waiting_message)
│       │   └── webhook_server.py  # Flask-приложение
│       ├── storage/
│       │   ├── db.py         # SQLAlchemy engine + session
│       │   ├── models.py     # ORM-модели (User, AuthorMessage)
│       │   ├── repo.py       # репозиторий (CRUD)
│       │   └── migrations/   # Alembic
│       └── services/
│           ├── rate_limit.py      # Redis rate limiting
│           └── author_notify.py   # пересылка, маппинг, бан-сервис
└── volumes/                # данные Postgres и Redis (не в git)
```

## Быстрый старт

### 1. Подготовка

```bash
cp .env.example .env
```

Заполнить в `.env`:
- `BOT_TOKEN` — токен из @BotFather
- `ADMIN_ID` — ваш Telegram ID (можно узнать через @userinfobot)
- `WEBHOOK_DOMAIN` — домен сервера
- `WEBHOOK_PATH` — секретный путь (длинная случайная строка)

### 2. TLS-сертификаты

Положить сертификаты в `certs/`:

```
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

### 4. Настройка группы (опционально)

Если хотите пересылать сообщения в группу:

1. Добавьте бота в группу
2. Напишите `/getid` в группе (доступно только админу)
3. Скопируйте ID из ответа бота
4. Укажите в `.env`:
   ```
   GROUP_CHAT_ID=-100xxxxxxxxxx
   NOTIFY_MODE=group   # или both
   ```
5. Перезапустите: `docker compose up --build -d`

### 5. Миграции (Alembic)

```bash
# Применить миграции
docker compose exec bot alembic upgrade head

# Создать новую миграцию
docker compose exec bot alembic revision --autogenerate -m "description"
```

## Команды бота

| Команда | Кто может | Где работает | Описание |
|---|---|---|---|
| `/start` | Все | ЛС с ботом | Приветствие + кнопка |
| `/getid` | Админ | Везде | Показать ID чата |
| `/ban` | Админ | ЛС / группа (reply) | Заблокировать пользователя |
| `/unban` | Админ | ЛС / группа (reply) | Разблокировать пользователя |

`/ban` и `/unban` работают как ответ (reply) на пересланное ботом сообщение.

## Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Токен Telegram-бота | — (обязательно) |
| `WEBHOOK_DOMAIN` | Домен для webhook | — (обязательно) |
| `WEBHOOK_PORT` | Внешний порт HTTPS | `8443` |
| `WEBHOOK_PATH` | Путь webhook (секретный) | `webhook/secret-path` |
| `WEBHOOK_SECRET_TOKEN` | Secret token для верификации запросов Telegram | — |
| `ADMIN_ID` | Telegram ID администратора | — (обязательно) |
| `NOTIFY_MODE` | Режим пересылки: `admin` / `group` / `both` | `admin` |
| `GROUP_CHAT_ID` | Chat ID группы (при `group`/`both`) | — |
| `POSTGRES_DSN` | DSN подключения к PostgreSQL | `postgresql+psycopg://govorun:changeme@postgres:5432/govorun` |
| `POSTGRES_USER` | Пользователь PostgreSQL | `govorun` |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL | `changeme` |
| `POSTGRES_DB` | Имя базы данных | `govorun` |
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
