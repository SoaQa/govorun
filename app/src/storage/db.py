from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.config import settings

engine = create_engine(settings.postgres_dsn, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session() -> Session:
    """Создать новую сессию БД."""
    return SessionLocal()
