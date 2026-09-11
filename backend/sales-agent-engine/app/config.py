"""Service configuration: env, tenant budgets, model routing rules.

Engine-specific variables use the ``SALES_AGENT_`` prefix. Variables that already
exist on the platform (``backend/.env``) keep their established names so a single
env file serves every service.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent

API_PREFIX = "/api/v1/sales-agent"
AGENT_SCHEMA = "agent"
CHECKPOINT_SCHEMA = "agent_checkpoint"

_DEFAULT_PUBLIC_KEY = BACKEND_ROOT / "auth-service" / "src" / "main" / "resources" / "keys" / "public_key.pem"


def _env(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env", SERVICE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- service ---------------------------------------------------------
    service_name: str = Field("sales-agent-engine", validation_alias=_env("SALES_AGENT_SERVICE_NAME"))
    hostname: str = Field("sales-agent-engine", validation_alias=_env("SALES_AGENT_HOSTNAME"))
    port: int = Field(8084, validation_alias=_env("SALES_AGENT_PORT"))
    log_level: str = Field("INFO", validation_alias=_env("SALES_AGENT_LOG_LEVEL"))

    # --- database --------------------------------------------------------
    database_url: str | None = Field(None, validation_alias=_env("SALES_AGENT_DATABASE_URL"))
    db_user: str = Field("postgres", validation_alias=_env("SALES_AGENT_DB_USER", "DATABASE_PROVIDER_USERNAME"))
    db_password: SecretStr = Field(SecretStr(""), validation_alias=_env("SALES_AGENT_DB_PASSWORD", "DATABASE_PASSWORD"))
    db_host: str = Field("localhost", validation_alias=_env("SALES_AGENT_DB_HOST"))
    db_port: int = Field(5432, validation_alias=_env("SALES_AGENT_DB_PORT"))
    db_name: str = Field("rolesync-micro-sales-agent", validation_alias=_env("SALES_AGENT_DB_NAME"))
    db_pool_size: int = Field(10, validation_alias=_env("SALES_AGENT_DB_POOL_SIZE"))

    # --- redis -----------------------------------------------------------
    redis_host: str = Field("localhost", validation_alias=_env("SALES_AGENT_REDIS_HOST", "REDIS_HOST"))
    redis_port: int = Field(6379, validation_alias=_env("SALES_AGENT_REDIS_PORT", "REDIS_PORT"))
    redis_db: int = Field(0, validation_alias=_env("SALES_AGENT_REDIS_DB"))
    redis_key_prefix: str = Field("sae", validation_alias=_env("SALES_AGENT_REDIS_KEY_PREFIX"))

    # --- identity (auth-service tokens + workspace membership) -----------
    jwt_public_key_path: Path | None = Field(
        _DEFAULT_PUBLIC_KEY, validation_alias=_env("SALES_AGENT_JWT_PUBLIC_KEY_PATH")
    )
    jwt_public_key_pem: SecretStr | None = Field(None, validation_alias=_env("SALES_AGENT_JWT_PUBLIC_KEY_PEM"))
    jwt_issuer: str = Field("rolesync-micro-authservice", validation_alias=_env("JWT_ISSUER"))
    jwt_leeway_seconds: int = Field(30, validation_alias=_env("SALES_AGENT_JWT_LEEWAY_SECONDS"))
    auth_cookie_name: str = Field("access_token", validation_alias=_env("SALES_AGENT_AUTH_COOKIE_NAME"))
    workspace_service_url: str = Field(
        "http://localhost:8083", validation_alias=_env("SALES_AGENT_WORKSPACE_SERVICE_URL")
    )
    membership_cache_seconds: int = Field(60, validation_alias=_env("SALES_AGENT_MEMBERSHIP_CACHE_SECONDS"))

    # --- discovery -------------------------------------------------------
    eureka_enabled: bool = Field(False, validation_alias=_env("SALES_AGENT_EUREKA_ENABLED"))
    eureka_server: str = Field("http://eureka-service:8761/eureka/", validation_alias=_env("EUREKA_SERVER"))

    # --- approvals + tools -----------------------------------------------
    approval_ttl_seconds: int = Field(86_400, validation_alias=_env("SALES_AGENT_APPROVAL_TTL_SECONDS"))
    tool_timeout_seconds: float = Field(30.0, validation_alias=_env("SALES_AGENT_TOOL_TIMEOUT_SECONDS"))

    # --- event stream (SSE) ----------------------------------------------
    event_stream_maxlen: int = Field(5_000, validation_alias=_env("SALES_AGENT_EVENT_STREAM_MAXLEN"))
    event_stream_ttl_seconds: int = Field(7 * 86_400, validation_alias=_env("SALES_AGENT_EVENT_STREAM_TTL_SECONDS"))
    sse_ping_seconds: int = Field(15, validation_alias=_env("SALES_AGENT_SSE_PING_SECONDS"))
    sse_max_connection_seconds: int = Field(1_800, validation_alias=_env("SALES_AGENT_SSE_MAX_CONNECTION_SECONDS"))

    def _base_url(self) -> URL:
        if self.database_url:
            return make_url(self.database_url)
        return URL.create(
            "postgresql",
            username=self.db_user,
            password=self.db_password.get_secret_value() or None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def sqlalchemy_url(self) -> URL:
        return self._base_url().set(drivername="postgresql+asyncpg")

    @property
    def psycopg_conninfo(self) -> str:
        """libpq conninfo for the LangGraph checkpointer (psycopg 3)."""
        from psycopg.conninfo import make_conninfo

        url = self._base_url()
        return make_conninfo(
            host=url.host or "localhost",
            port=url.port or 5432,
            dbname=url.database,
            user=url.username,
            password=url.password or None,
        )

    def jwt_public_key(self) -> str:
        if self.jwt_public_key_pem and self.jwt_public_key_pem.get_secret_value().strip():
            return self.jwt_public_key_pem.get_secret_value()
        if self.jwt_public_key_path and self.jwt_public_key_path.is_file():
            return self.jwt_public_key_path.read_text(encoding="utf-8")
        raise RuntimeError(
            "No JWT public key configured: set SALES_AGENT_JWT_PUBLIC_KEY_PATH (auth-service public_key.pem) "
            "or SALES_AGENT_JWT_PUBLIC_KEY_PEM"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
