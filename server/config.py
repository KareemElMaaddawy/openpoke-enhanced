"""Simplified configuration management."""

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def _load_env_file() -> None:
    """Load .env from root directory if present."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, value = stripped.split("=", 1)
                key, value = key.strip(), value.strip().strip("'\"")
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


_load_env_file()


DEFAULT_APP_NAME = "OpenPoke Server"
DEFAULT_APP_VERSION = "0.3.0"


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(os.getenv(name, str(fallback)))
    except (TypeError, ValueError):
        return fallback


ROUTING_MODES = ("legacy", "records")


# These read the environment when Settings() is built, not when the class is defined,
# so `server.server --routing` can set OPENPOKE_ROUTING after this module is imported.
def _routing_mode_from_env() -> str:
    return os.getenv("OPENPOKE_ROUTING", "legacy").strip().lower()


def _full_roster_max_from_env() -> object:
    raw = os.getenv("OPENPOKE_FULL_ROSTER_MAX", "").strip()
    if raw:
        return raw
    # Imported here: services import this module, so a top-level import would be circular.
    from .services.routing.params import RetrievalParams

    return RetrievalParams().full_roster_max


class Settings(BaseModel):
    """Application settings with lightweight env fallbacks."""

    # App metadata
    app_name: str = Field(default=DEFAULT_APP_NAME)
    app_version: str = Field(default=DEFAULT_APP_VERSION)

    # Server runtime
    server_host: str = Field(default=os.getenv("OPENPOKE_HOST", "0.0.0.0"))
    server_port: int = Field(default=_env_int("OPENPOKE_PORT", 8001))

    # LLM model selection
    interaction_agent_model: str = Field(default="openai/gpt-6-luna")
    execution_agent_model: str = Field(default="openai/gpt-6-luna")
    execution_agent_search_model: str = Field(default="openai/gpt-6-luna")
    summarizer_model: str = Field(default="openai/gpt-6-luna")
    email_classifier_model: str = Field(default="openai/gpt-6-luna")

    # Credentials / integrations
    openrouter_api_key: Optional[str] = Field(default=os.getenv("OPENROUTER_API_KEY"))
    composio_gmail_auth_config_id: Optional[str] = Field(default=os.getenv("COMPOSIO_GMAIL_AUTH_CONFIG_ID"))
    composio_api_key: Optional[str] = Field(default=os.getenv("COMPOSIO_API_KEY"))

    # HTTP behaviour
    cors_allow_origins_raw: str = Field(default=os.getenv("OPENPOKE_CORS_ALLOW_ORIGINS", "*"))
    enable_docs: bool = Field(default=os.getenv("OPENPOKE_ENABLE_DOCS", "1") != "0")
    docs_url: Optional[str] = Field(default=os.getenv("OPENPOKE_DOCS_URL", "/docs"))

    # Summarisation controls
    conversation_summary_threshold: int = Field(default=100)
    conversation_summary_tail_size: int = Field(default=10)

    # Interaction-agent routing: "legacy" (names only) or "records" (records and retrieval)
    routing_mode: str = Field(default_factory=_routing_mode_from_env, validate_default=True)
    # Records mode shows every agent up to this many active ones, and retrieves above it
    full_roster_max: int = Field(default_factory=_full_roster_max_from_env, validate_default=True)
    embedding_model: str = Field(default="openai/text-embedding-3-small")
    embedding_dimensions: int = Field(default=512)

    @field_validator("routing_mode", mode="before")
    @classmethod
    def _validate_routing_mode(cls, value: object) -> str:
        mode = str(value).strip().lower()
        if mode not in ROUTING_MODES:
            raise ValueError(
                f"OPENPOKE_ROUTING must be one of: {', '.join(ROUTING_MODES)} (got {value!r})"
            )
        return mode

    @field_validator("full_roster_max", mode="before")
    @classmethod
    def _validate_full_roster_max(cls, value: object) -> int:
        message = f"OPENPOKE_FULL_ROSTER_MAX must be an integer >= 0, where 0 means always retrieve (got {value!r})"
        if isinstance(value, bool):
            raise ValueError(message)
        try:
            parsed = value if isinstance(value, int) else int(str(value).strip())
        except ValueError:
            raise ValueError(message) from None
        if parsed < 0:
            raise ValueError(message)
        return parsed

    @property
    def cors_allow_origins(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        if self.cors_allow_origins_raw.strip() in {"", "*"}:
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins_raw.split(",") if origin.strip()]

    @property
    def resolved_docs_url(self) -> Optional[str]:
        """Return documentation URL when docs are enabled."""
        return (self.docs_url or "/docs") if self.enable_docs else None

    @property
    def summarization_enabled(self) -> bool:
        """Flag indicating conversation summarisation is active."""
        return self.conversation_summary_threshold > 0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
