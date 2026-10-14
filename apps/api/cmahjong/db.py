"""用户、会话、对局。SQLite 用来本机直接玩，腾讯云 Compose 用 PostgreSQL。"""

from __future__ import annotations

import os
import time
from datetime import datetime
from urllib.parse import quote_plus

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def resolve_database_url() -> str:
    """密码单独传入再编码，避免 @、#、% 把连接串拆坏。"""
    host = os.environ.get("POSTGRES_HOST")
    password = os.environ.get("POSTGRES_PASSWORD")
    if host and password is not None:
        user = quote_plus(os.environ.get("POSTGRES_USER", "cmahjong"))
        name = quote_plus(os.environ.get("POSTGRES_DB", "cmahjong"))
        port = os.environ.get("POSTGRES_PORT", "5432")
        return f"postgresql+psycopg://{user}:{quote_plus(password)}@{host}:{port}/{name}"
    return os.environ.get("DATABASE_URL", "sqlite:///./cmahjong.db")


DATABASE_URL = resolve_database_url()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Game(Base):
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ruleset_version: Mapped[str] = mapped_column(String(40))
    rules_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    phase: Mapped[str] = mapped_column(String(32))
    hand_index: Mapped[int] = mapped_column(Integer)
    seed: Mapped[bytes] = mapped_column(LargeBinary)
    state_json: Mapped[str] = mapped_column(Text)
    scores_json: Mapped[str] = mapped_column(Text)
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GameEvent(Base):
    __tablename__ = "game_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    hand_index: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[str] = mapped_column(Text)
    public_json: Mapped[str] = mapped_column(Text)


class Save(Base):
    __tablename__ = "saves"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_game_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(40))
    phase: Mapped[str] = mapped_column(String(32))
    hand_index: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    seed: Mapped[bytes] = mapped_column(LargeBinary)
    state_json: Mapped[str] = mapped_column(Text)
    events_json: Mapped[str] = mapped_column(Text)
    scores_json: Mapped[str] = mapped_column(Text)
    rules_json: Mapped[str] = mapped_column(Text)
    ruleset_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def make_engine():
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    last_error: Exception | None = None
    for attempt in range(30):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            Base.metadata.create_all(engine)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    assert last_error is not None
    raise last_error


def health_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
