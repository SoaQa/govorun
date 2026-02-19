import json
from dataclasses import dataclass, field
from typing import Callable

import telebot
from sqlalchemy.orm import Session

from src.bot.messages import FWD_HEADER, FWD_USER_ID, FWD_USERNAME, FWD_FIRST_NAME
from src.config import settings
from src.logging import logger
from src.services.rate_limit import get_redis
from src.storage.db import get_session
from src.storage.repo import Repository


@dataclass(frozen=True)
class BanUpdateResult:
    success: bool
    found: bool


class BanService:
    """Сервис блокировки пользователей (персистентно в БД)."""

    def __init__(self, session_factory: Callable[[], Session] = get_session):
        self._session_factory = session_factory

    def is_banned(self, user_telegram_id: int) -> bool:
        session = None
        try:
            session = self._session_factory()
            repo = Repository(session)
            return repo.is_user_blocked(user_telegram_id)
        except Exception as e:
            logger.error("Failed to check block status for user %d: %s", user_telegram_id, e)
            return False
        finally:
            if session is not None:
                session.close()

    def ban_user(self, user_telegram_id: int) -> BanUpdateResult:
        return self._set_blocked(user_telegram_id, blocked=True)

    def unban_user(self, user_telegram_id: int) -> BanUpdateResult:
        return self._set_blocked(user_telegram_id, blocked=False)

    def _set_blocked(self, user_telegram_id: int, blocked: bool) -> BanUpdateResult:
        session = None
        try:
            session = self._session_factory()
            repo = Repository(session)
            found = repo.set_user_blocked(user_telegram_id, blocked)
            return BanUpdateResult(success=True, found=found)
        except Exception as e:
            logger.error(
                "Failed to update block status for user %d (blocked=%s): %s",
                user_telegram_id,
                blocked,
                e,
            )
            return BanUpdateResult(success=False, found=False)
        finally:
            if session is not None:
                session.close()


@dataclass(frozen=True)
class FeedbackIdentity:
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None


@dataclass(frozen=True)
class FeedbackRoute:
    user_telegram_id: int
    feedback_id: int | None


class FeedbackIdentityResolver:
    _MAP_KEY_PREFIX = "feedback:admin_message"
    _MAP_TTL_SECONDS = 60 * 60 * 24 * 30

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def resolve(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> FeedbackIdentity:
        cleaned_username = self._clean(username)
        if cleaned_username and cleaned_username.startswith("@"):
            cleaned_username = cleaned_username[1:]

        return FeedbackIdentity(
            telegram_id=telegram_id,
            username=cleaned_username,
            first_name=self._clean(first_name),
            last_name=self._clean(last_name),
        )

    def remember_admin_message(
        self,
        admin_chat_id: int,
        admin_message_id: int,
        identity: FeedbackIdentity,
        feedback_id: int | None = None,
    ) -> None:
        key = self._mapping_key(admin_chat_id, admin_message_id)
        payload = {
            "user_telegram_id": identity.telegram_id,
            "feedback_id": feedback_id,
        }
        try:
            redis_client = get_redis()
            redis_client.set(
                key,
                json.dumps(payload, ensure_ascii=True),
                ex=self._MAP_TTL_SECONDS,
            )
            logger.info(
                "Stored feedback mapping: admin_chat=%d admin_message=%d user=%d feedback_id=%s",
                admin_chat_id,
                admin_message_id,
                identity.telegram_id,
                feedback_id,
            )
        except Exception as e:
            logger.error(
                "Failed to store feedback mapping for admin message %d in chat %d: %s",
                admin_message_id,
                admin_chat_id,
                e,
            )

    def resolve_by_admin_message(self, admin_chat_id: int, admin_message_id: int) -> FeedbackRoute | None:
        key = self._mapping_key(admin_chat_id, admin_message_id)
        try:
            redis_client = get_redis()
            raw_payload = redis_client.get(key)
        except Exception as e:
            logger.error(
                "Failed to read feedback mapping for admin message %d in chat %d: %s",
                admin_message_id,
                admin_chat_id,
                e,
            )
            return None

        if not raw_payload:
            return None

        try:
            payload = json.loads(raw_payload)
            user_telegram_id = int(payload["user_telegram_id"])
            raw_feedback_id = payload.get("feedback_id")
            feedback_id = int(raw_feedback_id) if raw_feedback_id is not None else None
            return FeedbackRoute(
                user_telegram_id=user_telegram_id,
                feedback_id=feedback_id,
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error(
                "Invalid feedback mapping payload for admin message %d in chat %d: %s",
                admin_message_id,
                admin_chat_id,
                e,
            )
            return None

    def _mapping_key(self, admin_chat_id: int, admin_message_id: int) -> str:
        return f"{self._MAP_KEY_PREFIX}:{admin_chat_id}:{admin_message_id}"


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


def format_message(identity: FeedbackIdentity, text: str) -> str:
    """Форматирует сообщение для пересылки."""
    user_info = FWD_USER_ID.format(user_id=identity.telegram_id)
    if identity.username:
        user_info += FWD_USERNAME.format(username=identity.username)
    if identity.first_name:
        user_info += FWD_FIRST_NAME.format(first_name=identity.first_name)

    return f"{FWD_HEADER}\n\n{user_info}\n\n{text}"


def _send_to_chat(
    bot: telebot.TeleBot,
    chat_id: int,
    formatted: str,
    label: str,
    user_id: int,
) -> tuple[bool, str, int | None]:
    """Отправить сообщение в конкретный чат. Возвращает (ok, error_text, message_id)."""
    try:
        sent = bot.send_message(chat_id, formatted)
        logger.info("Message delivered to %s (chat %d) from user %d", label, chat_id, user_id)
        return True, "", sent.message_id
    except Exception as e:
        logger.error("Failed to deliver message to %s (chat %d) from user %d: %s", label, chat_id, user_id, e)
        return False, str(e), None


def send_to_recipients(
    bot: telebot.TeleBot,
    identity: FeedbackIdentity,
    text: str,
    identity_resolver: FeedbackIdentityResolver | None = None,
    feedback_id: int | None = None,
) -> DeliveryResult:
    """
    Отправить сообщение адресатам согласно NOTIFY_MODE.

    Режимы:
      - admin: только в ЛС админу (ADMIN_ID)
      - group: только в группу (GROUP_CHAT_ID)
      - both:  и туда, и туда
    """
    formatted = format_message(identity, text)
    result = DeliveryResult()

    # Собираем список адресатов
    targets: list[tuple[int, str]] = []
    if settings.notify_mode in ("admin", "both"):
        targets.append((settings.admin_id, "admin"))
    if settings.notify_mode in ("group", "both") and settings.group_chat_id:
        targets.append((settings.group_chat_id, "group"))

    for chat_id, label in targets:
        ok, err, sent_message_id = _send_to_chat(
            bot,
            chat_id,
            formatted,
            label,
            identity.telegram_id,
        )
        result.details[chat_id] = (ok, err)
        if ok and sent_message_id is not None and identity_resolver is not None:
            identity_resolver.remember_admin_message(
                admin_chat_id=chat_id,
                admin_message_id=sent_message_id,
                identity=identity,
                feedback_id=feedback_id,
            )

    # Считаем успехом, если хотя бы один адресат получил
    result.success = any(ok for ok, _ in result.details.values())
    return result
