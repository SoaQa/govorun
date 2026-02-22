import telebot

from src.config import settings
from src.logging import logger
from src.bot.keyboards import main_keyboard
from src.bot.permissions import is_admin, is_staff
from src.bot.messages import (
    START,
    BTN_WRITE,
    ASK_MESSAGE,
    RATE_LIMIT,
    EMPTY_MESSAGE,
    TOO_LONG,
    SENT_OK,
    SENT_FAIL,
    BLOCKED,
    UNKNOWN,
    CHAT_INFO,
    REPLY_PREFIX,
    ADMIN_REPLY_OK,
    ADMIN_REPLY_FAIL,
    ADMIN_REPLY_TARGET_NOT_FOUND,
    ADMIN_BAN_OK,
    ADMIN_UNBAN_OK,
    ADMIN_USER_NOT_FOUND,
    ADMIN_BAN_FAIL,
    ADMIN_UNBAN_FAIL,
)
from src.bot.states import (
    get_state,
    set_state,
    reset_state,
    STATE_WAITING_MESSAGE,
)
from src.services.rate_limit import can_send, get_ttl
from src.services.author_notify import send_to_recipients, BanService, FeedbackIdentityResolver
from src.storage.db import get_session
from src.storage.repo import Repository


def register_handlers(bot: telebot.TeleBot) -> None:
    """Регистрирует все хендлеры бота."""
    identity_resolver = FeedbackIdentityResolver()
    ban_service = BanService()
    group_chat_id = settings.group_chat_id

    def _extract_command(text: str) -> str:
        tokens = text.strip().split(maxsplit=1)
        if not tokens:
            return ""
        command_token = tokens[0].lower()
        if not command_token.startswith("/"):
            return ""
        if "@" in command_token:
            command_token = command_token.split("@", 1)[0]
        return command_token

    def _user_keyboard(message: telebot.types.Message) -> telebot.types.ReplyKeyboardMarkup | telebot.types.ReplyKeyboardRemove:
        """Клавиатура с кнопкой — только для обычных пользователей в ЛС."""
        if message.chat.type == "private" and not is_staff(message.from_user.id):
            return main_keyboard()
        return telebot.types.ReplyKeyboardRemove()

    def _is_feedback_blocked(user_id: int) -> bool:
        return not is_staff(user_id) and ban_service.is_banned(user_id)

    def _reject_banned_feedback(
        message: telebot.types.Message,
        *,
        reset_waiting_state: bool = False,
    ) -> bool:
        user = message.from_user
        if user is None or not _is_feedback_blocked(user.id):
            return False

        if reset_waiting_state:
            reset_state(user.id)

        bot.send_message(
            message.chat.id,
            BLOCKED,
            reply_markup=_user_keyboard(message),
        )
        return True

    @bot.message_handler(commands=["start"])
    def handle_start(message: telebot.types.Message) -> None:
        """Приветствие + сохранение пользователя."""
        user = message.from_user
        logger.info("/start from user %d (%s)", user.id, user.username)

        # Сохраняем/обновляем пользователя в БД
        session = None
        try:
            session = get_session()
            repo = Repository(session)
            repo.upsert_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
        except Exception as e:
            logger.error("DB error on /start: %s", e)
        finally:
            if session is not None:
                session.close()

        reset_state(user.id)

        bot.send_message(
            message.chat.id,
            START,
            reply_markup=_user_keyboard(message),
        )

    @bot.message_handler(commands=["getid"])
    def handle_getid(message: telebot.types.Message) -> None:
        """Показать chat_id текущего чата. Доступно staff (админ + модераторы)."""
        user = message.from_user
        if not is_staff(user.id):
            return

        chat = message.chat
        chat_type = chat.type
        title = chat.title or chat.username or chat.first_name or "—"

        bot.send_message(
            chat.id,
            CHAT_INFO.format(chat_id=chat.id, chat_type=chat_type, title=title),
            parse_mode="HTML",
        )
        logger.info("/getid by admin in chat %d (%s)", chat.id, chat_type)

    _STAFF_COMMANDS = ("/ban", "/unban", "/reply")

    @bot.message_handler(
        func=lambda m: (
            bool(m.from_user)
            and is_staff(m.from_user.id)
            and m.reply_to_message is not None
            and (
                # В ЛС админа — любой reply или команда
                m.chat.id == settings.admin_id
                # В группе — только staff-команды
                or (
                    group_chat_id is not None
                    and m.chat.id == group_chat_id
                    and _extract_command(m.text or "") in _STAFF_COMMANDS
                )
            )
        )
    )
    def handle_staff_reply(message: telebot.types.Message) -> None:
        """Обработка reply на пересланное сообщение: /reply, /ban, /unban, plain text."""
        text = (message.text or "").strip()
        if not text:
            return
        command = _extract_command(text)

        route = identity_resolver.resolve_by_admin_message(
            admin_chat_id=message.chat.id,
            admin_message_id=message.reply_to_message.message_id,
        )
        if route is None:
            bot.send_message(message.chat.id, ADMIN_REPLY_TARGET_NOT_FOUND)
            return

        if command == "/ban":
            ban_result = ban_service.ban_user(route.user_telegram_id)
            if not ban_result.success:
                bot.send_message(message.chat.id, ADMIN_BAN_FAIL)
            elif not ban_result.found:
                bot.send_message(message.chat.id, ADMIN_USER_NOT_FOUND)
            else:
                bot.send_message(message.chat.id, ADMIN_BAN_OK)
            return

        if command == "/unban":
            unban_result = ban_service.unban_user(route.user_telegram_id)
            if not unban_result.success:
                bot.send_message(message.chat.id, ADMIN_UNBAN_FAIL)
            elif not unban_result.found:
                bot.send_message(message.chat.id, ADMIN_USER_NOT_FOUND)
            else:
                bot.send_message(message.chat.id, ADMIN_UNBAN_OK)
            return

        # /reply <текст> — извлекаем текст после команды
        if command == "/reply":
            reply_text = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
            reply_text = reply_text.strip()
            if not reply_text:
                return
            text = reply_text
        else:
            # Простой reply без команды — только админ в ЛС с ботом
            if not is_admin(message.from_user.id) or message.chat.id != settings.admin_id:
                return

        try:
            bot.send_message(route.user_telegram_id, REPLY_PREFIX.format(text=text))
            bot.send_message(message.chat.id, ADMIN_REPLY_OK)
            logger.info(
                "Staff reply delivered: staff=%d user=%d author_message=%s",
                message.from_user.id,
                route.user_telegram_id,
                route.author_message_id,
            )
        except Exception as e:
            logger.error(
                "Failed to deliver staff reply: staff=%d user=%d author_message=%s err=%s",
                message.from_user.id,
                route.user_telegram_id,
                route.author_message_id,
                e,
            )
            bot.send_message(message.chat.id, ADMIN_REPLY_FAIL)

    @bot.message_handler(func=lambda m: m.text == BTN_WRITE)
    def handle_write_button(message: telebot.types.Message) -> None:
        """Пользователь нажал кнопку 'Написать автору'."""
        user = message.from_user
        logger.info("Write button pressed by user %d", user.id)

        if _reject_banned_feedback(message):
            return

        # Проверяем лимит до перехода в состояние ожидания (staff не ограничен)
        if not is_staff(user.id) and not can_send(user.id):
            ttl = get_ttl(user.id)
            minutes = ttl // 60
            bot.send_message(
                message.chat.id,
                RATE_LIMIT.format(minutes=minutes),
                reply_markup=_user_keyboard(message),
            )
            return

        set_state(user.id, STATE_WAITING_MESSAGE)
        bot.send_message(
            message.chat.id,
            ASK_MESSAGE.format(max_len=settings.max_message_length),
        )

    @bot.message_handler(func=lambda m: get_state(m.from_user.id) == STATE_WAITING_MESSAGE)
    def handle_user_message(message: telebot.types.Message) -> None:
        """Пользователь прислал текст сообщения для автора."""
        user = message.from_user
        text = (message.text or "").strip()

        if _reject_banned_feedback(message, reset_waiting_state=True):
            return

        # Сброс состояния в любом случае
        reset_state(user.id)

        if not is_staff(user.id) and _extract_command(text):
            bot.send_message(
                message.chat.id,
                UNKNOWN,
                reply_markup=_user_keyboard(message),
            )
            return

        # Валидация
        if not text:
            bot.send_message(
                message.chat.id,
                EMPTY_MESSAGE,
                reply_markup=_user_keyboard(message),
            )
            return

        if len(text) > settings.max_message_length:
            bot.send_message(
                message.chat.id,
                TOO_LONG.format(length=len(text), max_len=settings.max_message_length),
                reply_markup=_user_keyboard(message),
            )
            return

        # Сохраняем в БД
        msg_record = None
        session = None
        try:
            session = get_session()
            repo = Repository(session)
            repo.upsert_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
            msg_record = repo.create_author_message(user_telegram_id=user.id, text=text)
        except Exception as e:
            logger.error("DB error saving message: %s", e)
        finally:
            if session is not None:
                session.close()

        # Отправляем адресатам (админ / группа / оба)
        identity = identity_resolver.resolve(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        result = send_to_recipients(
            bot=bot,
            identity=identity,
            text=text,
            identity_resolver=identity_resolver,
            author_message_id=msg_record.id if msg_record else None,
        )

        # Обновляем статус доставки
        if msg_record:
            session = None
            try:
                session = get_session()
                repo = Repository(session)
                if result.success:
                    repo.mark_delivered(msg_record.id)
                else:
                    repo.mark_failed(msg_record.id, result.error_summary or "Telegram API error")
            except Exception as e:
                logger.error("DB error updating delivery status: %s", e)
            finally:
                if session is not None:
                    session.close()

        if result.success:
            bot.send_message(
                message.chat.id,
                SENT_OK,
                reply_markup=_user_keyboard(message),
            )
        else:
            bot.send_message(
                message.chat.id,
                SENT_FAIL,
                reply_markup=_user_keyboard(message),
            )

    @bot.message_handler(func=lambda m: m.chat.type == "private")
    def handle_unknown(message: telebot.types.Message) -> None:
        """Обработка прочих сообщений в ЛС."""
        bot.send_message(
            message.chat.id,
            UNKNOWN,
            reply_markup=_user_keyboard(message),
        )
