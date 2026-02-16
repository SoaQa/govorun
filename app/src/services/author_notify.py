from dataclasses import dataclass, field

import telebot

from src.bot.messages import FWD_HEADER, FWD_USER_ID, FWD_USERNAME, FWD_FIRST_NAME
from src.config import settings
from src.logging import logger


@dataclass
class DeliveryResult:
    """Результат доставки сообщения по всем адресатам."""
    # Хотя бы один адресат получил сообщение
    success: bool = False
    # Детали по каждому адресату: chat_id -> (ok, error_text)
    details: dict[int, tuple[bool, str]] = field(default_factory=dict)

    @property
    def error_summary(self) -> str:
        """Суммарное описание ошибок (для записи в БД)."""
        errors = [f"chat {cid}: {err}" for cid, (ok, err) in self.details.items() if not ok]
        return "; ".join(errors) if errors else ""


def format_message(user_id: int, username: str | None, first_name: str | None, text: str) -> str:
    """Форматирует сообщение для пересылки."""
    user_info = FWD_USER_ID.format(user_id=user_id)
    if username:
        user_info += FWD_USERNAME.format(username=username)
    if first_name:
        user_info += FWD_FIRST_NAME.format(first_name=first_name)

    return f"{FWD_HEADER}\n\n{user_info}\n\n{text}"


def _send_to_chat(bot: telebot.TeleBot, chat_id: int, formatted: str, label: str, user_id: int) -> tuple[bool, str]:
    """Отправить сообщение в конкретный чат. Возвращает (ok, error_text)."""
    try:
        bot.send_message(chat_id, formatted)
        logger.info("Message delivered to %s (chat %d) from user %d", label, chat_id, user_id)
        return True, ""
    except Exception as e:
        logger.error("Failed to deliver message to %s (chat %d) from user %d: %s", label, chat_id, user_id, e)
        return False, str(e)


def send_to_recipients(
    bot: telebot.TeleBot,
    user_id: int,
    username: str | None,
    first_name: str | None,
    text: str,
) -> DeliveryResult:
    """
    Отправить сообщение адресатам согласно NOTIFY_MODE.

    Режимы:
      - admin: только в ЛС админу (ADMIN_ID)
      - group: только в группу (GROUP_CHAT_ID)
      - both:  и туда, и туда
    """
    formatted = format_message(user_id, username, first_name, text)
    result = DeliveryResult()

    # Собираем список адресатов
    targets: list[tuple[int, str]] = []
    if settings.notify_mode in ("admin", "both"):
        targets.append((settings.admin_id, "admin"))
    if settings.notify_mode in ("group", "both") and settings.group_chat_id:
        targets.append((settings.group_chat_id, "group"))

    for chat_id, label in targets:
        ok, err = _send_to_chat(bot, chat_id, formatted, label, user_id)
        result.details[chat_id] = (ok, err)

    # Считаем успехом, если хотя бы один адресат получил
    result.success = any(ok for ok, _ in result.details.values())
    return result
