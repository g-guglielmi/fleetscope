from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sites: Mapped[list["Site"]] = relationship(back_populates="client", cascade="all, delete-orphan")


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("client_id", "slug", name="uq_site_client_slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    client: Mapped[Client] = relationship(back_populates="sites")


class Collector(Base):
    __tablename__ = "collectors"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_collector_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    collector_id: Mapped[int] = mapped_column(ForeignKey("collectors.id", ondelete="CASCADE"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw: Mapped[dict] = mapped_column(JSON)


class Component(Base):
    __tablename__ = "components"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    hostname: Mapped[str] = mapped_column(String(255))
    product: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    build: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Certificate(Base):
    __tablename__ = "certificates"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(512))
    issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    thumbprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class License(Base):
    __tablename__ = "licenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    product: Mapped[str] = mapped_column(String(128))
    edition: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_advantage_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Advisory(Base):
    __tablename__ = "advisories"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_type: Mapped[str] = mapped_column(String(64), index=True)  # matches component.type
    title: Mapped[str] = mapped_column(String(512))
    cve: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    cvss: Mapped[float | None] = mapped_column(nullable=True)
    # Simple version predicate for build-number matching (see enrichment.py).
    # NVD-sourced rows arrive with this empty and needs_review=True, so they do
    # NOT auto-match until a human adds the build predicate (no false positives).
    affected_below_build: Mapped[str | None] = mapped_column(String(64), nullable=True)
    affected_versions: Mapped[list | None] = mapped_column(JSON, nullable=True)  # optional exact-version list
    fixed_build: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | nvd
    needs_review: Mapped[bool] = mapped_column(default=False)
    published: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    advisory_id: Mapped[int] = mapped_column(ForeignKey("advisories.id", ondelete="CASCADE"))
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
