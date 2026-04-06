import base64
import hashlib

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://sorthive:sorthive_dev@localhost:5432/sorthive"
    JWT_SECRET: str = "change-me-in-production"
    UPLOAD_DIR: str = "data/uploads"
    CORS_ORIGIN: str = "http://localhost:5174"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    MIN_REVIEWS_FOR_CONSENSUS: int = 1
    COOKIE_SECURE: bool = False
    APP_BASE_URL: str | None = None
    GITHUB_CLIENT_ID: str | None = None
    GITHUB_CLIENT_SECRET: str | None = None
    GITHUB_REDIRECT_URI: str | None = None
    GITHUB_OAUTH_STATE_EXPIRE_MINUTES: int = 10
    REBRICKABLE_API_KEY: str = ""
    BL_AFFILIATE_API_KEY: str = ""
    SORTING_PROFILE_PARTS_DB_PATH: str = "data/profile_builder/parts.db"
    SORTING_PROFILE_BRICKSTORE_DB_PATH: str = "~/Library/Caches/BrickStore/database-v12"
    PROFILE_CATALOG_AUTO_SYNC_ENABLED: bool = True
    PROFILE_CATALOG_AUTO_SYNC_CHECK_INTERVAL_MINUTES: int = 60
    PROFILE_CATALOG_AUTO_SYNC_PARTS_MAX_AGE_HOURS: int = 24
    PROFILE_CATALOG_AUTO_SYNC_COLORS_MAX_AGE_HOURS: int = 24
    PROFILE_CATALOG_AUTO_SYNC_CATEGORIES_MAX_AGE_HOURS: int = 168
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    DEFAULT_AI_MODEL: str = "anthropic/claude-sonnet-4.6"
    PROFILE_AI_PROMPT_CACHE_ENABLED: bool = True
    PROFILE_AI_PROMPT_CACHE_TTL: str | None = None
    SECRET_ENCRYPTION_KEY: str | None = None

    @property
    def public_app_url(self) -> str:
        return (self.APP_BASE_URL or self.CORS_ORIGIN).rstrip("/")

    @property
    def github_redirect_uri(self) -> str:
        if self.GITHUB_REDIRECT_URI:
            return self.GITHUB_REDIRECT_URI
        return f"{self.public_app_url}/api/auth/github/callback"

    @property
    def github_oauth_enabled(self) -> bool:
        return bool(self.GITHUB_CLIENT_ID and self.GITHUB_CLIENT_SECRET)

    @property
    def secret_encryption_key(self) -> str:
        if self.SECRET_ENCRYPTION_KEY:
            return self.SECRET_ENCRYPTION_KEY
        derived = base64.urlsafe_b64encode(hashlib.sha256(self.JWT_SECRET.encode()).digest())
        return derived.decode()

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
