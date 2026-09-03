from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FS_", env_file=".env", extra="ignore")

    # SQLite lives on a bind mount in the container (sqlite:////data/fleetscope.db).
    database_url: str = "sqlite:///./fleetscope.db"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # Shared ingest key — every probe uses this to push; probes self-declare their
    # client/site, which are auto-provisioned. Empty = ingest disabled.
    ingest_key: str = ""

    # Bootstrap admin (created on first startup if no users exist)
    admin_email: str = "admin@local"
    admin_password: str = "changeme"

    # A collector is considered offline if no push within this many minutes
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
