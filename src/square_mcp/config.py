from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PRODUCTION_BASE_URL = "https://connect.squareup.com/v2"
DEFAULT_SANDBOX_BASE_URL = "https://connect.squareupsandbox.com/v2"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"

    # Auth mode:
    # "gateway" — production/SOP-compliant: token from HTTP header per request (no global state)
    # "env"     — local dev only: shared token from SQUARE_ACCESS_TOKEN env var (not SOP-compliant)
    auth_mode: Literal["env", "gateway"] = "gateway"

    # Square credentials (only required in env mode)
    square_access_token: str | None = None
    # Square environment used in env mode ("production" or "sandbox").
    square_environment: Literal["production", "sandbox"] = "production"

    # Header names used to pass the token and environment in gateway mode.
    # The client must include these headers on every /mcp request.
    square_auth_header: str = "X-Square-Access-Token"
    square_env_header: str = "X-Square-Environment"

    # Square-Version header pinned server-side. Letting a caller choose it
    # would let a caller silently break the response parsing in this service.
    square_api_version: str = "2024-07-17"

    @property
    def has_credentials(self) -> bool:
        """Returns True if the server can serve API calls.

        Gateway mode always returns True — each request carries its own token.
        Env mode requires SQUARE_ACCESS_TOKEN to be set.
        """
        if self.auth_mode == "gateway":
            return True
        return self.square_access_token is not None


def get_settings() -> Settings:
    return Settings()


def base_url_for(environment: str) -> str:
    """Resolve the Square API base URL for the given environment name.

    Callers must validate `environment` is "production" or "sandbox" before
    calling this (see server.resolve_environment) — an invalid value is a
    tool-level invalid_argument error, not something this helper guesses at.
    """
    if environment == "sandbox":
        return DEFAULT_SANDBOX_BASE_URL
    return DEFAULT_PRODUCTION_BASE_URL
