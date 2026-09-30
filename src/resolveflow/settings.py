from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://resolveflow:resolveflow@localhost:55432/resolveflow"
    session_secret: SecretStr = SecretStr("")
    operator_password: SecretStr = SecretStr("")
    supervisor_password: SecretStr = SecretStr("")
    developer_password: SecretStr = SecretStr("")
    demo_mode: bool = False
    public_read_only: bool = False
    cookie_secure: bool = True
    remote_deployment: bool = False
    provider_enabled: bool = False
    provider_base_url: str = "http://localhost:11434/v1"
    provider_model: str = "qwen3:8b"
    provider_api_key: SecretStr = SecretStr("")
    provider_timeout_seconds: float = Field(45, ge=1, le=120)
    provider_max_retries: int = Field(2, ge=0, le=3)
    provider_temperature: float = Field(0, ge=0, le=1)
    max_model_calls: int = Field(12, ge=1, le=30)
    max_tool_calls: int = Field(24, ge=1, le=60)
    max_total_tokens: int = Field(30000, ge=1000, le=100000)
    max_active_seconds: float = Field(240, ge=5, le=600)
    job_lease_seconds: int = Field(90, ge=3, le=300)
    max_job_attempts: int = Field(3, ge=1, le=5)
    worker_idle_seconds: float = Field(0.5, ge=0.1, le=30)
    database_pool_size: int = Field(5, ge=1, le=10)
    database_max_overflow: int = Field(3, ge=0, le=10)
    retention_days: int = Field(30, ge=1, le=365)

    @field_validator("database_url", mode="before")
    @classmethod
    def postgres_driver(cls, value):
        # Hosts commonly supply postgres:// or postgresql:// URLs. Keep passwords
        # and encoded query parameters intact while selecting the installed driver.
        url = make_url(value)
        if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
            raise ValueError("A PostgreSQL database URL is required")
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)

    @model_validator(mode="after")
    def secure_config(self):
        if self.remote_deployment:
            if self.demo_mode or not self.cookie_secure:
                raise ValueError("Remote deployments require demo access off and secure cookies")
            secrets = [
                self.session_secret.get_secret_value(),
                self.operator_password.get_secret_value(),
                self.supervisor_password.get_secret_value(),
                self.developer_password.get_secret_value(),
            ]
            if any(len(value) < 32 or "CHANGE_ME" in value for value in secrets):
                raise ValueError("Remote deployments require four strong generated secrets")
            if len(set(secrets)) != len(secrets):
                raise ValueError("Remote role passwords and signing secret must be distinct")
            url = make_url(self.database_url)
            if url.query.get("sslmode") not in ("require", "verify-ca", "verify-full"):
                raise ValueError("Remote PostgreSQL connections require TLS")
            if self.provider_enabled and not self.provider_base_url.startswith("https://"):
                raise ValueError("Hosted providers must be reachable over HTTPS")
        if self.provider_enabled and not self.provider_base_url.startswith(
            ("http://localhost:", "http://127.0.0.1:", "http://host.docker.internal:", "https://")
        ):
            raise ValueError("Remote providers require HTTPS")
        return self

    @property
    def checkpoint_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
