from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    retention_days: int = Field(30, ge=1, le=365)

    @model_validator(mode="after")
    def secure_config(self):
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
