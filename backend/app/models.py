from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC. SQLite does not store timezones, so we keep everything naive
    UTC end to end to avoid aware/naive comparison errors."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize an incoming (possibly tz-aware) datetime to naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")  # admin | viewer
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    sites: Mapped[list["Site"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    credentials: Mapped[list["Credential"]] = relationship(back_populates="client", cascade="all, delete-orphan")


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("client_id", "slug", name="uq_site_client_slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    client: Mapped[Client] = relationship(back_populates="sites")
    config: Mapped["SiteConfig | None"] = relationship(
        back_populates="site", uselist=False, cascade="all, delete-orphan"
    )


class SiteConfig(Base):
    """What an agent should collect at a site, and how. Edited in the UI, pulled
    by the agent at every check-in. See docs/AGENT.md §6.3."""
    __tablename__ = "site_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), unique=True, index=True)
    # {check_name: {"enabled": bool, "settings": {...}}}
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    auto_update: Mapped[bool] = mapped_column(Boolean, default=True)
    # {"serviceAccount": "<credential name>"}
    agent: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"unattended": bool, "citrixSdkSource": str|None}
    prerequisites: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    site: Mapped[Site] = relationship(back_populates="config")


class Collector(Base):
    """An agent (or legacy probe). Enrolls with a temporary token, then gets its
    own permanent one."""
    __tablename__ = "collectors"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_collector_site_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # last ingest
    last_collector_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Agent-reported state (docs/AGENT.md §4.6)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prerequisites: Mapped[dict] = mapped_column(JSON, default=dict)          # {"cvad-sdk": "2402", "winrm-client": true, ...}
    credential_versions: Mapped[dict] = mapped_column(JSON, default=dict)    # {name: version} held by the agent
    last_checkin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # per-check diagnostics of the last collection
    pending_actions: Mapped[list] = mapped_column(JSON, default=list)        # ["run-now", "restart", ...]


class EnrollmentToken(Base):
    """A temporary, time-boxed token bound to one client. Agents present it on
    enrollment; the server then issues each agent its own permanent token.
    Reusable within its window (to enroll several of a client's agents)."""
    __tablename__ = "enrollment_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def is_valid(self, now: datetime) -> bool:
        return not self.revoked and self.expires_at > now


class Credential(Base):
    """A client-scoped secret managed in the dashboard and delivered to the
    client's agents that reference it by name. Encrypted with FS_SECRETS_KEY
    (AES-256-GCM); the plaintext is never returned to UI users."""
    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("client_id", "name", name="uq_credential_client_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # device | windows
    username: Mapped[str] = mapped_column(String(255))
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    client: Mapped[Client] = relationship(back_populates="credentials")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255))          # user email or "agent:<name>"
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    collector_id: Mapped[int] = mapped_column(ForeignKey("collectors.id", ondelete="CASCADE"))
    collected_at: Mapped[datetime] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
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
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Certificate(Base):
    __tablename__ = "certificates"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(512))
    issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    not_after: Mapped[datetime] = mapped_column(DateTime)
    thumbprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class License(Base):
    __tablename__ = "licenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    product: Mapped[str] = mapped_column(String(128))
    edition: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_advantage_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Advisory(Base):
    __tablename__ = "advisories"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_type: Mapped[str] = mapped_column(String(64), index=True)  # matches component.type
    title: Mapped[str] = mapped_column(String(512))
    cve: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    cvss: Mapped[float | None] = mapped_column(Float, nullable=True)
    # NVD-sourced rows arrive with this empty and needs_review=True, so they do
    # NOT auto-match until a human adds the build predicate (no false positives).
    affected_below_build: Mapped[str | None] = mapped_column(String(64), nullable=True)
    affected_versions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fixed_build: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | nvd
    needs_review: Mapped[bool] = mapped_column(default=False)
    published: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    advisory_id: Mapped[int] = mapped_column(ForeignKey("advisories.id", ondelete="CASCADE"))
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
