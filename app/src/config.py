from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    bot_token: str
    webhook_domain: str
    webhook_port: int = 8443
    webhook_path: str = "webhook/secret-path"
    webhook_secret_token: str = ""

    # Telegram ID администратора (используется для пересылки ЛС и проверки прав)
    admin_id: int

    # Куда пересылать сообщения: admin / group / both
    notify_mode: Literal["admin", "group", "both"] = "admin"

    # Группа/чат (обязательно если notify_mode = group или both)
    group_chat_id: int | None = None

    @field_validator("group_chat_id", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        """Пустая строка из ENV -> None."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @model_validator(mode="after")
    def _check_chat_ids(self) -> "Settings":
        """Проверяем что нужные chat_id заданы для выбранного режима."""
        if self.notify_mode in ("group", "both") and not self.group_chat_id:
            raise ValueError("GROUP_CHAT_ID is required when NOTIFY_MODE is 'group' or 'both'")
        return self

    # Postgres
    postgres_dsn: str = "postgresql+psycopg://govorun:changeme@postgres:5432/govorun"

    # Redis
    redis_dsn: str = "redis://redis:6379/0"

    # Rate limit
    rate_limit_seconds: int = 3600

    # Максимальная длина сообщения пользователя
    max_message_length: int = 2000

    # Logging
    log_level: str = "INFO"

    # Внутренний HTTP сервер
    app_host: str = "0.0.0.0"
    app_port: int = 8080

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @property
    def webhook_url(self) -> str:
        return f"https://{self.webhook_domain}:{self.webhook_port}/{self.webhook_path}"


settings = Settings()
