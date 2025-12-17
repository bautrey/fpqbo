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

    # QBO OAuth (Optional - for Phase 3+)
    qbo_client_id: str | None = None
    qbo_client_secret: SecretStr | None = None

    # Database
    database_url: str = "sqlite:///./data/fortium-qbo.db"

    # Deployment
    base_url: str = "http://localhost:8000"

    @property
    def session_max_age_seconds(self) -> int:
        """Session max age in seconds for cookie configuration."""
        return self.session_max_age_days * 24 * 60 * 60

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
