import uuid

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    String,
    text as sql_text,
)

from ._base import Base, DictLikeMixin


class Identity(DictLikeMixin, Base):
    """Слой идентификации: к одному identity можно привязать email и/или Telegram (tg_id)."""

    __tablename__ = "identities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=True, index=True)
    tg_id = Column(BigInteger, unique=True, nullable=True, index=True)
    api_token_hash = Column(String(64), nullable=True, index=True)
    token_issued_at = Column(DateTime, nullable=True)
    password_hash = Column(String(64), nullable=True)
    email_verified = Column(Boolean, nullable=False, server_default=sql_text("false"))
    is_admin = Column(Boolean, nullable=False, server_default=sql_text("false"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
