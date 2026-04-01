from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://sorthive:sorthive_dev@localhost:5432/sorthive"
    JWT_SECRET: str = "change-me-in-production"
    UPLOAD_DIR: str = "data/uploads"
    CORS_ORIGIN: str = "http://localhost:5174"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    MIN_REVIEWS_FOR_CONSENSUS: int = 2
    COOKIE_SECURE: bool = False
    APP_BASE_URL: str | None = None
    GITHUB_CLIENT_ID: str | None = None
    GITHUB_CLIENT_SECRET: str | None = None
    GITHUB_REDIRECT_URI: str | None = None
    GITHUB_OAUTH_STATE_EXPIRE_MINUTES: int = 10

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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
