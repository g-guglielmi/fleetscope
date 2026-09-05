from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---- Collector/agent ingest payload (see docs/COLLECTOR_CONTRACT.md) ----
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


class CheckDiagnostic(BaseModel):
    name: str
    version: str | None = None
    status: str  # ok | warn | error | skipped
    durationMs: int | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class IngestPayload(BaseModel):
    collectorVersion: str | None = None
    client: str | None = None          # informational; the token binds the client
    site: str = Field(min_length=1)    # site display name; slug auto-derived
    probe: str | None = None           # probe identity (e.g. hostname)
    collectedAt: datetime
    components: list[ComponentIn] = Field(default_factory=list)
    certificates: list[CertificateIn] = Field(default_factory=list)
    licenses: list[LicenseIn] = Field(default_factory=list)
    # Agent: per-check outcome of this collection (docs/AGENT.md §6.2)
    diagnostics: list[CheckDiagnostic] | None = None


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


# ---- Agent API (docs/AGENT.md §6.2) ----
class EnrollRequest(BaseModel):
    site: str = Field(min_length=1)
    hostname: str = Field(min_length=1)
    agentVersion: str | None = None
    osVersion: str | None = None


class CheckinRequest(BaseModel):
    agentVersion: str | None = None
    hostname: str | None = None
    osVersion: str | None = None
    prerequisites: dict = Field(default_factory=dict)        # {"cvad-sdk": "2402", "winrm-client": true}
    credentialVersions: dict[str, int] = Field(default_factory=dict)
    lastRun: dict | None = None


# ---- Auth ----
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "admin"
    mustChangePassword: bool = False


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=12, max_length=256)


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
