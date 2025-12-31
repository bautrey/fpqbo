"""Application configuration using Pydantic settings."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_secret_key: SecretStr = Field(min_length=32)
    session_max_age_days: int = 30
    debug: bool = False

    # Google OAuth (Admin UI) - Required
    google_client_id: str = Field(min_length=1)
    google_client_secret: SecretStr = Field(min_length=1)
    google_allowed_domain: str = "fortiumpartners.com"
    initial_admin_email: str | None = None

    # QBO OAuth - US (Production)
    qbo_client_id: str | None = None
    qbo_client_secret: SecretStr | None = None
    qbo_redirect_uri: str | None = None  # Defaults to {base_url}/callback

    # QBO OAuth - Canada (separate Intuit app required)
    qbo_ca_client_id: str | None = None
    qbo_ca_client_secret: SecretStr | None = None

    # DEPRECATED - tokens now stored in database (kept for migration)
    qbo_access_token: SecretStr | None = None
    qbo_refresh_token: str | None = None
    qbo_company_id: str | None = None

    # Database
    database_url: str = "sqlite:///./data/fortium-qbo.db"

    # Deployment
    base_url: str = "http://localhost:8000"

    @property
    def session_max_age_seconds(self) -> int:
        """Session max age in seconds for cookie configuration."""
        return self.session_max_age_days * 24 * 60 * 60

    @property
    def qbo_callback_url(self) -> str:
        """Get QBO OAuth callback URL."""
        return self.qbo_redirect_uri or f"{self.base_url}/callback"

    @property
    def qbo_configured(self) -> bool:
        """Check if any QBO OAuth is configured (US or CA)."""
        return self.qbo_us_configured or self.qbo_ca_configured

    @property
    def qbo_us_configured(self) -> bool:
        """Check if US QBO OAuth is configured."""
        return bool(self.qbo_client_id and self.qbo_client_secret)

    @property
    def qbo_ca_configured(self) -> bool:
        """Check if Canada QBO OAuth is configured."""
        return bool(self.qbo_ca_client_id and self.qbo_ca_client_secret)

    def get_qbo_credentials(self, region: str) -> tuple[str, str] | None:
        """
        Get QBO OAuth credentials for a specific region.

        Args:
            region: "US" or "CA"

        Returns:
            Tuple of (client_id, client_secret) or None if not configured
        """
        if region == "US" and self.qbo_us_configured:
            return (self.qbo_client_id, self.qbo_client_secret.get_secret_value())
        elif region == "CA" and self.qbo_ca_configured:
            return (self.qbo_ca_client_id, self.qbo_ca_client_secret.get_secret_value())
        return None

    @field_validator("app_secret_key")
    @classmethod
    def validate_secret_key_length(cls, v: SecretStr) -> SecretStr:
        """Ensure app_secret_key is at least 32 characters."""
        if len(v.get_secret_value()) < 32:
            raise ValueError("app_secret_key must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
