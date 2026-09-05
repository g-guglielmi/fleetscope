from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FS_", env_file=".env", extra="ignore")

    # SQLite lives on a bind mount in the container (sqlite:////data/fleetscope.db).
    database_url: str = "sqlite:///./fleetscope.db"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # Default lifetime for dashboard-generated enrollment tokens.
    enrollment_ttl_hours: int = 24

    # Bootstrap admin (created on first startup if no users exist)
    admin_email: str = "admin@local"
    admin_password: str = "changeme"

    # Relaxes the production safety checks (default secrets, unsigned manifest,
    # forced password change). Never set in a real deployment.
    dev_mode: bool = False

    # Public URL of this dashboard (https://fleetscope.example.com). Embedded in
    # generated agent install commands.
    public_url: str = ""

    # Base64 32-byte key for AES-256-GCM encryption of stored credentials.
    # Unset = credential features disabled. Generate: tools/sign/sign.py keygen
    secrets_key: str = ""

    # Base64 Ed25519 public key that signs check manifests / agent releases.
    # Embedded in install commands so agents pin it. Generate: sign.py keygen
    signing_pubkey: str = ""

    # Agent check-in cadence handed to agents (seconds).
    agent_checkin_seconds: int = 120

    # Where check modules and the agent release live. Defaults: <repo>/checks and
    # <repo>/agent-release in dev, /app/checks and /app/agent in the image.
    checks_dir: str = ""
    agent_release_dir: str = ""

    # A collector is considered offline if no push within this many minutes
    # (legacy PowerShell collector; agents are judged on their check-in cadence).
    collector_stale_minutes: int = 60
    collector_offline_minutes: int = 360

    # Expiry warning thresholds (days)
    cert_warn_days: int = 30
    license_warn_days: int = 45

    # NVD auto-sync (curated table is primary; NVD adds review candidates)
    nvd_sync_enabled: bool = True
    nvd_api_key: str = ""  # optional; raises the NVD rate limit
    nvd_sync_hour: int = 3  # local hour for the daily sync

    # Email / SMTP alerts (leave smtp_host empty to disable)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    alert_from: str = "fleetscope@localhost"
    alert_to: str = ""  # comma-separated recipients
    alert_hour: int = 7  # local hour for the daily digest

    cors_origins: str = "*"


settings = Settings()
