import telebot
from flask import Flask, request, abort

from src.config import settings
from src.logging import logger

app = Flask(__name__)

# Экземпляр бота — устанавливается из main.py
_bot: telebot.TeleBot | None = None


def set_bot(bot: telebot.TeleBot) -> None:
    """Установить экземпляр бота для обработки апдейтов."""
    global _bot
    _bot = bot


@app.route(f"/{settings.webhook_path}", methods=["POST"])
def webhook() -> tuple[str, int]:
    """Эндпоинт для приёма webhook-апдейтов от Telegram."""
    if _bot is None:
        logger.error("Bot instance not set")
        abort(500)

    # Проверка secret token (если задан)
    if settings.webhook_secret_token:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != settings.webhook_secret_token:
            logger.warning("Invalid secret token in webhook request")
            abort(403)

    if request.headers.get("content-type") != "application/json":
        logger.warning("Invalid content-type: %s", request.headers.get("content-type"))
        abort(400)

    json_data = request.get_data(as_text=True)
    update = telebot.types.Update.de_json(json_data)
    _bot.process_new_updates([update])

    return "OK", 200


@app.route("/health", methods=["GET"])
def health() -> tuple[str, int]:
    """Healthcheck эндпоинт."""
    return "OK", 200
