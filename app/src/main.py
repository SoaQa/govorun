import time

import sqlalchemy
import telebot
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from src.config import settings
from src.logging import logger
from src.bot.handlers import register_handlers
from src.bot.webhook_server import app, set_bot
from src.storage.db import engine


def create_bot() -> telebot.TeleBot:
    """Создать и настроить экземпляр бота."""
    bot = telebot.TeleBot(settings.bot_token, threaded=False)
    register_handlers(bot)
    return bot


def setup_webhook(bot: telebot.TeleBot) -> None:
    """Установить webhook в Telegram."""
    logger.info("Removing old webhook...")
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(0.5)

    logger.info("Setting webhook: %s", settings.webhook_url)
    bot.set_webhook(
        url=settings.webhook_url,
        secret_token=settings.webhook_secret_token or None,
    )
    logger.info("Webhook set successfully")


def run_migrations() -> None:
    """Применить все pending-миграции Alembic при старте."""
    logger.info("Running database migrations...")
    alembic_cfg = Config("alembic.ini")

    # Если таблицы уже есть, а alembic_version — нет,
    # значит БД создана через create_all; штампуем начальную ревизию.
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        current_rev = context.get_current_revision()
        has_tables = sqlalchemy.inspect(conn).has_table("users")

    if current_rev is None and has_tables:
        logger.info("Existing database without alembic_version detected, stamping 001_initial...")
        command.stamp(alembic_cfg, "001_initial")

    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied")


def main() -> None:
    logger.info("Starting govorun bot...")

    # Применяем миграции
    run_migrations()

    # Создание бота и регистрация хендлеров
    bot = create_bot()
    set_bot(bot)

    # Установка webhook
    setup_webhook(bot)

    logger.info("Starting webhook server on %s:%d", settings.app_host, settings.app_port)

    # Запуск Flask через gunicorn (в продакшене) или встроенный сервер
    app.run(host=settings.app_host, port=settings.app_port)


if __name__ == "__main__":
    main()
