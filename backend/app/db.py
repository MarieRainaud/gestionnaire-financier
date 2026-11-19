import os
from datetime import date, datetime, timezone
from datetime import date as CalendarDate
from decimal import Decimal
from sqlalchemy import (
    create_engine,
    ForeignKey,
    String,
    Numeric,
    Date,
    DateTime,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://finance:finance@127.0.0.1:5443/finance"
)
engine = create_engine(URL, pool_pre_ping=True, pool_size=5, max_overflow=2)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password: Mapped[str] = mapped_column(String(512))
    demo: Mapped[bool] = mapped_column(default=False)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Owned:
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


class Account(Owned, Base):
    __tablename__ = "accounts"
    name: Mapped[str] = mapped_column(String(100))
    bank: Mapped[str] = mapped_column(String(100))
    opening: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    opening_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20), default="courant")


class Category(Owned, Base):
    __tablename__ = "categories"
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    __table_args__ = (UniqueConstraint("owner_id", "name"),)


class Transaction(Owned, Base):
    __tablename__ = "transactions"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(250))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    # Les deux écritures d'un virement partagent le même identifiant.
    transfer: Mapped[str | None] = mapped_column(String(36), index=True)
    recurring_id: Mapped[int | None] = mapped_column(ForeignKey("recurring.id"))
    recurring_due: Mapped[CalendarDate | None] = mapped_column(Date, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("owner_id", "account_id", "fingerprint"),
        Index("ix_tx_owner_date", "owner_id", "date"),
    )


class Budget(Owned, Base):
    __tablename__ = "budgets"
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    month: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    __table_args__ = (UniqueConstraint("owner_id", "category_id", "month"),)


class Recurring(Owned, Base):
    __tablename__ = "recurring"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    months: Mapped[int] = mapped_column(default=1)
    next_due: Mapped[date] = mapped_column(Date)
    anchor_day: Mapped[int] = mapped_column(default=1)
    active: Mapped[bool] = mapped_column(default=True)


class Loan(Owned, Base):
    __tablename__ = "loans"
    name: Mapped[str] = mapped_column(String(100))
    lender: Mapped[str] = mapped_column(String(100))
    principal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_due: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    installment: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    next_due: Mapped[date] = mapped_column(Date)
    anchor_day: Mapped[int] = mapped_column(default=1)


class Repayment(Owned, Base):
    __tablename__ = "repayments"
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), unique=True
    )


class Rule(Owned, Base):
    __tablename__ = "rules"
    contains: Mapped[str] = mapped_column(String(100))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(254), default="")
    display_name: Mapped[str] = mapped_column(String(150), default="")
    __table_args__ = (UniqueConstraint("issuer", "subject"),)


class OIDCFlow(Base):
    __tablename__ = "oidc_flows"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(150))
    nonce: Mapped[str] = mapped_column(String(150))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OIDCSession(Base):
    __tablename__ = "oidc_sessions"
    token: Mapped[str] = mapped_column(
        ForeignKey("sessions.token", ondelete="CASCADE"), primary_key=True
    )
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("external_identities.id", ondelete="CASCADE"), index=True
    )
    sid: Mapped[str] = mapped_column(String(255))


class OIDCLogoutHint(Base):
    __tablename__ = "oidc_logout_hints"
    token: Mapped[str] = mapped_column(
        ForeignKey("sessions.token", ondelete="CASCADE"), primary_key=True
    )
    id_token: Mapped[str] = mapped_column(String(16384))


class OIDCLogout(Base):
    __tablename__ = "oidc_logouts"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))
