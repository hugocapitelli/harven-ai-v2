import logging
from functools import lru_cache
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("harven")

# Known-weak / placeholder JWT secrets that must never sign production tokens.
WEAK_JWT_SECRETS = {"", "change-me-in-production", "your-secret-key-here"}
# Minimum acceptable length for a strong JWT secret (e.g. `openssl rand -hex 32`).
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # Auth
    # Bootstrap signing secret. As of SEC-ROT-2 this is no longer the direct
    # source of truth for sign/verify — it only seeds / falls back the DB-backed
    # active secret (see backend/jwt_secret_provider.py). Kept fail-closed by the
    # validator below so a public default never reaches production.
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 8
    # TTL (seconds) of the in-process cache for the DB-backed active JWT secret.
    # Bounds how long a rotation (admin force-logout) can take to propagate when
    # the cache is not explicitly invalidated; force-logout invalidates eagerly.
    JWT_SECRET_CACHE_TTL: int = 30

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # App
    FRONTEND_URL: str = "http://localhost:3000"
    ENVIRONMENT: str = "development"
    # Dev-only escape hatch: expose the password-reset token in the response
    # body/log. Never honored in production (see request_password_reset).
    RESET_TOKEN_DEBUG: bool = False
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024
    PORT: int = 8000

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        """Fail-closed guard for the JWT signing secret.

        In production a weak/default/empty/too-short secret aborts the boot
        (RuntimeError) so tokens are never signed with a publicly known key.
        Outside production we only log a WARNING to preserve local DX.
        Any sufficiently strong secret is accepted — no format restriction
        beyond blacklist + minimum length — so runtime rotation
        (admin force-logout) keeps passing the guard.
        """
        secret = self.JWT_SECRET_KEY or ""
        is_weak = secret in WEAK_JWT_SECRETS or len(secret) < MIN_JWT_SECRET_LENGTH

        if not is_weak:
            return self

        if self.ENVIRONMENT.lower() == "production":
            raise RuntimeError(
                "Insecure JWT_SECRET_KEY in production: it is empty, a known "
                "default, or shorter than 32 characters. Set a strong secret, "
                "e.g. `JWT_SECRET_KEY=$(openssl rand -hex 32)`. Boot aborted "
                "(fail-closed) to prevent tokens being signed with a known key."
            )

        logger.warning(
            "JWT_SECRET_KEY is weak/default/short (%d chars). Acceptable for "
            "non-production (ENVIRONMENT=%s), but production boot would fail. "
            "Set a strong secret, e.g. `openssl rand -hex 32`.",
            len(secret),
            self.ENVIRONMENT,
        )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
