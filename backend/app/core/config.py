from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "PaperMate"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/papermate"

    # Local File Storage
    upload_dir: str = "./uploads"

    # MinerU PDF Parser
    mineru_api_url: str = "https://mineru.net"  # Cloud: https://mineru.net, Local: http://localhost:8010
    mineru_api_key: Optional[str] = None  # Required for cloud API
    mineru_use_cloud: bool = True  # True for cloud API, False for local deployment
    mineru_model_version: str = "pipeline"  # Cloud model: pipeline | vlm

    # JWT
    jwt_secret_key: str = "your-super-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS & Security - supports comma-separated string from env
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def auth_cookie_path(self) -> str:
        """Path for refresh token cookie."""
        return f"{self.api_v1_prefix}/auth"

    # OpenAI (supports OpenAI-compatible providers)
    openai_api_key: str = ""
    openai_base_url: Optional[str] = None  # Custom API URL for third-party providers
    openai_model: str = "gpt-4o"

    # Optional search tools for Translation ReAct agent
    tavily_api_key: Optional[str] = None
    searxng_url: Optional[str] = None

    # Chat service settings
    chat_max_tool_rounds: int = 10
    chat_openai_timeout_seconds: float = 60.0
    chat_openai_max_retries: int = 5

    # Login rate limiting (in-memory)
    login_rate_limit_per_ip: int = 10
    login_rate_limit_per_user: int = 5
    login_rate_limit_window_seconds: int = 300

    def mineru_headers(self) -> dict[str, str]:
        """Build auth headers for MinerU API."""
        if self.mineru_api_key:
            return {"Authorization": f"Bearer {self.mineru_api_key}"}
        return {}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Validate JWT secret key is not using default value in production
    if not settings.debug and settings.jwt_secret_key == "your-super-secret-key-change-in-production":
        raise ValueError(
            "CRITICAL: JWT_SECRET_KEY is using the default value. "
            "Please set a secure JWT_SECRET_KEY environment variable for production."
        )
    return settings
