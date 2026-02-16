import telebot

from src.config import settings
from src.logging import logger
from src.bot.keyboards import main_keyboard
from src.bot.messages import (
    START,
    BTN_WRITE,
    ASK_MESSAGE,
    RATE_LIMIT,
    EMPTY_MESSAGE,
    TOO_LONG,
    SENT_OK,
    SENT_FAIL,
    UNKNOWN,
    CHAT_INFO,
)
from src.bot.states import (
    get_state,
    set_state,
    reset_state,
    STATE_WAITING_MESSAGE,
)
from src.services.rate_limit import can_send, get_ttl
from src.services.author_notify import send_to_recipients
from src.storage.db import get_session
from src.storage.repo import Repository


def register_handlers(bot: telebot.TeleBot) -> None:
    """Регистрирует все хендлеры бота."""

    @bot.message_handler(commands=["start"])
    def handle_start(message: telebot.types.Message) -> None:
        """Приветствие + сохранение пользователя."""
        user = message.from_user
        logger.info("/start from user %d (%s)", user.id, user.username)

        # Сохраняем/обновляем пользователя в БД
        try:
            session = get_session()
            repo = Repository(session)
            repo.upsert_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
            session.close()
        except Exception as e:
            logger.error("DB error on /start: %s", e)

        reset_state(user.id)

        bot.send_message(
            message.chat.id,
            START,
            reply_markup=main_keyboard(),
        )

    @bot.message_handler(commands=["getid"])
    def handle_getid(message: telebot.types.Message) -> None:
        """Показать chat_id текущего чата. Доступно только админу."""
        user = message.from_user
        if user.id != settings.admin_id:
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

    @bot.message_handler(func=lambda m: m.text == BTN_WRITE)
    def handle_write_button(message: telebot.types.Message) -> None:
        """Пользователь нажал кнопку 'Написать автору'."""
        user = message.from_user
        logger.info("Write button pressed by user %d", user.id)

        # Проверяем лимит до перехода в состояние ожидания
        if user.id != settings.admin_id and not can_send(user.id):
            ttl = get_ttl(user.id)
            minutes = ttl // 60
            bot.send_message(
                message.chat.id,
                RATE_LIMIT.format(minutes=minutes),
                reply_markup=main_keyboard(),
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

        # Сброс состояния в любом случае
        reset_state(user.id)

        # Валидация
        if not text:
            bot.send_message(
                message.chat.id,
                EMPTY_MESSAGE,
                reply_markup=main_keyboard(),
            )
            return

        if len(text) > settings.max_message_length:
            bot.send_message(
                message.chat.id,
                TOO_LONG.format(length=len(text), max_len=settings.max_message_length),
                reply_markup=main_keyboard(),
            )
            return

        # Сохраняем в БД
        msg_record = None
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

        # Отправляем адресатам (админ / группа / оба)
        result = send_to_recipients(bot, user.id, user.username, user.first_name, text)

        # Обновляем статус доставки
        if msg_record:
            try:
                session = get_session()
                repo = Repository(session)
                if result.success:
                    repo.mark_delivered(msg_record.id)
                else:
                    repo.mark_failed(msg_record.id, result.error_summary or "Telegram API error")
                session.close()
            except Exception as e:
                logger.error("DB error updating delivery status: %s", e)

        if result.success:
            bot.send_message(
                message.chat.id,
                SENT_OK,
                reply_markup=main_keyboard(),
            )
        else:
            bot.send_message(
                message.chat.id,
                SENT_FAIL,
                reply_markup=main_keyboard(),
            )

    @bot.message_handler(func=lambda m: True)
    def handle_unknown(message: telebot.types.Message) -> None:
        """Обработка всех прочих сообщений."""
        bot.send_message(
            message.chat.id,
            UNKNOWN,
            reply_markup=main_keyboard(),
        )
