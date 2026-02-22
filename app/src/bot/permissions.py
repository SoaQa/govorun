"""
Проверка прав пользователей.

Три уровня доступа:
  - public    — для всех (проверка не нужна)
  - admin     — только администратор
  - staff     — администратор + модераторы
"""
from src.config import settings


def is_admin(user_id: int) -> bool:
    """Только администратор."""
    return user_id == settings.admin_id


def is_staff(user_id: int) -> bool:
    """Администратор или модератор."""
    return user_id == settings.admin_id or user_id in settings.moderator_ids
