from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---- Collector ingest payload (see docs/COLLECTOR_CONTRACT.md) ----
class ComponentIn(BaseModel):
    type: str
    hostname: str
    product: str | None = None
    version: str | None = None
    build: str | None = None
    osVersion: str | None = None
    extra: dict = Field(default_factory=dict)


class CertificateIn(BaseModel):
    source: str
    hostname: str | None = None
    subject: str
    issuer: str | None = None
    notAfter: datetime
    thumbprint: str | None = None


class LicenseIn(BaseModel):
    product: str
    edition: str | None = None
    model: str | None = None
    count: int | None = None
    subscriptionAdvantageDate: datetime | None = None
    expires: datetime | None = None


class IngestPayload(BaseModel):
    collectorVersion: str | None = None
    client: str | None = None          # informational; the token binds the client
    site: str = Field(min_length=1)    # site display name; slug auto-derived
    probe: str | None = None           # probe identity (e.g. hostname)
    collectedAt: datetime
    components: list[ComponentIn] = Field(default_factory=list)
    certificates: list[CertificateIn] = Field(default_factory=list)
    licenses: list[LicenseIn] = Field(default_factory=list)


class IngestResult(BaseModel):
    ok: bool = True
    snapshotId: int
    components: int
    certificates: int
    licenses: int
    findings: int
    # Present only on the enrollment push: the probe's permanent token to save
    # and use for all subsequent pushes. The enrollment token can then expire.
    collectorToken: str | None = None
    enrolled: bool = False


# ---- Auth ----
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Read models ----
class ClientOverview(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    slug: str
    name: str


class OverviewClient(BaseModel):
    slug: str
    name: str
    sites: int
    collectors: int
    status: str  # ok | stale | offline | unknown
    lastSeen: datetime | None
    openFindings: int
    criticalFindings: int
    nearestCertExpiry: datetime | None
    nearestLicenseExpiry: datetime | None
