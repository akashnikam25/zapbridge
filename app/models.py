from datetime import datetime
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(unique=True)
    github_login: Mapped[str] = mapped_column(String(255))
    access_token_enc: Mapped[str] = mapped_column(Text)           # Fernet-encrypted
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
