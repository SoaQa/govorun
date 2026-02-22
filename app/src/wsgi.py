"""WSGI entrypoint для gunicorn."""
from src.main import create_bot, setup_webhook, run_migrations
from src.bot.webhook_server import app, set_bot
from src.logging import logger

logger.info("WSGI: Initializing application...")

run_migrations()

bot = create_bot()
set_bot(bot)
setup_webhook(bot)

logger.info("WSGI: Application ready")

# gunicorn ищет переменную `application` или `app`
application = app
