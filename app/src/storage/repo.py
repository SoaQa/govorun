from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.logging import logger
from src.storage.models import User, AuthorMessage


class Repository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_user(self, telegram_id: int, username: str | None, first_name: str | None, last_name: str | None) -> User:
        """Создать или обновить пользователя."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        user = self.session.execute(stmt).scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            self.session.add(user)
            logger.info("New user created: telegram_id=%d, username=%s", telegram_id, username)
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.last_seen_at = datetime.now(timezone.utc)

        self.session.commit()
        return user

    def create_author_message(self, user_telegram_id: int, text: str) -> AuthorMessage:
        """Создать запись о сообщении автору."""
        msg = AuthorMessage(
            user_telegram_id=user_telegram_id,
            text=text,
        )
        self.session.add(msg)
        self.session.commit()
        logger.info("Author message created: id=%d, user=%d", msg.id, user_telegram_id)
        return msg

    def mark_delivered(self, message_id: int) -> None:
        """Пометить сообщение как доставленное."""
        msg = self.session.get(AuthorMessage, message_id)
        if msg:
            msg.delivery_status = "delivered"
            msg.delivered_at = datetime.now(timezone.utc)
            self.session.commit()

    def mark_failed(self, message_id: int, error: str) -> None:
        """Пометить сообщение как недоставленное."""
        msg = self.session.get(AuthorMessage, message_id)
        if msg:
            msg.delivery_status = "failed"
            msg.error = error
            self.session.commit()
