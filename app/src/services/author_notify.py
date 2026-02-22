from dataclasses import dataclass, field
from typing import Callable

import telebot
from sqlalchemy.orm import Session

from src.bot.messages import FWD_HEADER, FWD_USER_ID, FWD_USERNAME, FWD_FIRST_NAME
from src.config import settings
from src.logging import logger
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
    author_message_id: int | None


class FeedbackIdentityResolver:
    """Маппинг пересланных сообщений ↔ пользователей (хранение в Postgres)."""

    def __init__(self, session_factory: Callable[[], Session] = get_session):
        self._session_factory = session_factory

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
        author_message_id: int | None = None,
    ) -> None:
        """Сохранить связку пересланного сообщения с пользователем в БД."""
        session = None
        try:
            session = self._session_factory()
            repo = Repository(session)
            repo.create_mapping(
                chat_id=admin_chat_id,
                message_id=admin_message_id,
                user_telegram_id=identity.telegram_id,
                author_message_id=author_message_id,
            )
            logger.info(
                "Stored feedback mapping: chat=%d message=%d user=%d author_message=%s",
                admin_chat_id,
                admin_message_id,
                identity.telegram_id,
                author_message_id,
            )
        except Exception as e:
            logger.error(
                "Failed to store feedback mapping for message %d in chat %d: %s",
                admin_message_id,
                admin_chat_id,
                e,
            )
        finally:
            if session is not None:
                session.close()

    def resolve_by_admin_message(self, admin_chat_id: int, admin_message_id: int) -> FeedbackRoute | None:
        """Найти пользователя по пересланному сообщению."""
        session = None
        try:
            session = self._session_factory()
            repo = Repository(session)
            mapping = repo.resolve_mapping(chat_id=admin_chat_id, message_id=admin_message_id)
            if mapping is None:
                return None
            return FeedbackRoute(
                user_telegram_id=mapping.user_telegram_id,
                author_message_id=mapping.author_message_id,
            )
        except Exception as e:
            logger.error(
                "Failed to resolve feedback mapping for message %d in chat %d: %s",
                admin_message_id,
                admin_chat_id,
                e,
            )
            return None
        finally:
            if session is not None:
                session.close()


@dataclass
class DeliveryResult:
    """Результат доставки сообщения по всем адресатам."""
    success: bool = False
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
    author_message_id: int | None = None,
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
                author_message_id=author_message_id,
            )

    result.success = any(ok for ok, _ in result.details.values())
    return result
