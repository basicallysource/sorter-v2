import base64
import secrets
from pathlib import Path
from typing import Callable

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings

_INSECURE_SECRET_VALUES = frozenset({"", "change-me-in-production"})


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql://hive:hive_dev@localhost:5432/hive"
    JWT_SECRET: str | None = None
    UPLOAD_DIR: str = "data/uploads"
    # Local dir scanned for color-classifier models (`.onnx`). One row per file is
    # reconciled into the color_models table; the active one serves piece-color
    # predictions. Model bytes are uploaded here out of band (not through the API).
    COLOR_MODEL_DIR: str = "data/color_models"
    # Local dir scanned for piece_link matcher models. Each model is a pair of
    # ONNX graphs (`*.encoder.onnx` + `*.head.onnx`, grouped by their baked
    # `hive.name`); one row per pair is reconciled into the link_models table.
    # The active one scores "same physical piece" upstream crops in the labeling
    # view in place of the time/angle heuristic. Uploaded here out of band.
    LINK_MODEL_DIR: str = "data/link_models"
    STORAGE_BACKEND: str = "local"
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""
    S3_REGION: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_SERVE_MODE: str = "redirect"
    S3_PRESIGNED_EXPIRY_SECONDS: int = 3600
    CORS_ORIGIN: str = "http://localhost:5174"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Reviews required before a sample can flip out of 'in_review' into a
    # final status. Aligned with REVIEW_CONSENSUS_TARGET so the global status
    # only resolves once the queue stops serving the sample — no "tentative
    # accepted after the first vote" race. Unanimity is enforced by
    # recompute_sample_status: 3✓ → accepted, 3✗ → rejected, any mix → conflict.
    MIN_REVIEWS_FOR_CONSENSUS: int = 3
    # Once a sample has REVIEW_CONSENSUS_TARGET independent reviews, it drops
    # out of every reviewer's queue regardless of whether they personally
    # reviewed it. Edge cases (ties / conflicts) can be revisited via the
    # samples list; the queue is for fresh work.
    REVIEW_CONSENSUS_TARGET: int = 3
    COOKIE_SECURE: bool = False
    APP_BASE_URL: str | None = None
    GITHUB_CLIENT_ID: str | None = None
    GITHUB_CLIENT_SECRET: str | None = None
    GITHUB_REDIRECT_URI: str | None = None
    GITHUB_OAUTH_STATE_EXPIRE_MINUTES: int = 10
    REBRICKABLE_API_KEY: str = ""
    BLA_API_KEY: str = ""
    SORTING_PROFILE_PARTS_DB_PATH: str = "data/profile_builder/parts.db"
    SORTING_PROFILE_BRICKSTORE_DB_PATH: str = "~/Library/Caches/BrickStore/database-v12"
    SORTING_PROFILE_LDRAW_LIBRARY_DIR: str = "ldraw_lib"
    PROFILE_CATALOG_AUTO_SYNC_ENABLED: bool = True
    PROFILE_CATALOG_AUTO_SYNC_CHECK_INTERVAL_MINUTES: int = 60
    PROFILE_CATALOG_AUTO_SYNC_PARTS_MAX_AGE_HOURS: int = 24
    PROFILE_CATALOG_AUTO_SYNC_COLORS_MAX_AGE_HOURS: int = 24
    PROFILE_CATALOG_AUTO_SYNC_CATEGORIES_MAX_AGE_HOURS: int = 168
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Perceptron exposes an OpenAI-compatible /v1/chat/completions endpoint.
    PERCEPTRON_BASE_URL: str = "https://api.perceptron.inc/v1"
    # Hard cap on in-flight teacher items across all providers combined. Per-provider
    # concurrency is also capped (see adapter.max_concurrent) so a single noisy provider
    # can't starve the pool — this is just the upper bound on overall thread count.
    TEACHER_WORKER_PARALLELISM: int = 8
    # Background condition-sample auto-labeler. Off by default — operators
    # opt in by setting a Perceptron key + flipping the flag.
    CONDITION_WORKER_ENABLED: bool = False
    CONDITION_WORKER_PERCEPTRON_API_KEY: str | None = None
    CONDITION_WORKER_POLL_INTERVAL_S: float = 5.0
    CONDITION_WORKER_BATCH_SIZE: int = 5
    CONDITION_WORKER_MIN_INTERVAL_S: float = 0.20
    # How often the background worker recomputes per-machine dashboard stats
    # (machine_stats_cache). Clamped to a 60s floor in the worker.
    MACHINE_STATS_REFRESH_INTERVAL_MINUTES: int = 60
    # How often the background worker walks the object store for the admin
    # server-health page (server_storage_cache). The walk lists every S3 key so
    # it's slow; a few hours is plenty. Clamped to a 5min floor in the worker.
    SERVER_STORAGE_REFRESH_INTERVAL_MINUTES: int = 180
    DEFAULT_AI_MODEL: str = "anthropic/claude-sonnet-4.6"
    PROFILE_AI_PROMPT_CACHE_ENABLED: bool = True
    PROFILE_AI_PROMPT_CACHE_TTL: str | None = None
    SECRET_ENCRYPTION_KEY: str | None = None
    DEV_SECRET_DIR: str = "data/dev-secrets"
    # Shared secret for the service-to-service aggregate-stats API
    # (app.routers.public_stats). A caller presenting this key gets the same
    # aggregate analytics an admin sees on the all-machines page. Empty disables
    # the endpoint (503).
    PUBLIC_STATS_API_KEY: str = ""
    MAX_MODEL_FILE_SIZE: int = 2 * 1024 * 1024 * 1024
    ALLOWED_MODEL_RUNTIMES: tuple[str, ...] = ("onnx", "ncnn", "hailo", "pytorch", "rknn")

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
    def environment(self) -> str:
        normalized = (self.ENVIRONMENT or "").strip().lower()
        return normalized or "development"

    @property
    def is_development(self) -> bool:
        return self.environment in {"development", "dev", "local", "test"}

    @property
    def jwt_signing_key(self) -> str:
        candidate = (self.JWT_SECRET or "").strip()
        if self._is_secure_secret(candidate):
            if not self.is_development and len(candidate) < 32:
                raise RuntimeError("JWT_SECRET must be at least 32 characters outside development.")
            return candidate
        if not self.is_development:
            raise RuntimeError("JWT_SECRET must be set to a strong random value outside development.")
        return self._get_or_create_dev_secret("jwt_secret.txt", lambda: secrets.token_urlsafe(64))

    @property
    def secret_encryption_key(self) -> str:
        candidate = (self.SECRET_ENCRYPTION_KEY or "").strip()
        if self._is_secure_secret(candidate):
            self._validate_fernet_key(candidate)
            return candidate
        if not self.is_development:
            raise RuntimeError("SECRET_ENCRYPTION_KEY must be set to a valid Fernet key outside development.")
        return self._get_or_create_dev_secret(
            "secret_encryption.key",
            lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        )

    def validate_security_configuration(self) -> None:
        _ = self.jwt_signing_key
        _ = self.secret_encryption_key

    @staticmethod
    def _is_secure_secret(value: str) -> bool:
        return value not in _INSECURE_SECRET_VALUES

    @staticmethod
    def _validate_fernet_key(value: str) -> None:
        try:
            Fernet(value.encode())
        except Exception as exc:  # pragma: no cover - cryptography owns validation details
            raise RuntimeError("SECRET_ENCRYPTION_KEY must be a valid Fernet key.") from exc

    def _get_or_create_dev_secret(self, file_name: str, generate: Callable[[], str]) -> str:
        secret_dir = self._resolve_dev_secret_dir()
        secret_dir.mkdir(parents=True, exist_ok=True)
        secret_path = secret_dir / file_name
        if secret_path.exists():
            existing = secret_path.read_text().strip()
            if existing:
                return existing

        value = generate()
        secret_path.write_text(value)
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
        return value

    def _resolve_dev_secret_dir(self) -> Path:
        candidate = Path(self.DEV_SECRET_DIR).expanduser()
        if candidate.is_absolute():
            return candidate
        return Path(__file__).resolve().parents[1] / candidate

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
settings.validate_security_configuration()
