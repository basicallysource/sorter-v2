from __future__ import annotations

from cryptography.fernet import Fernet
import pytest

from app.config import Settings


def test_development_generates_persistent_dev_secrets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET", "change-me-in-production")
    monkeypatch.delenv("SECRET_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DEV_SECRET_DIR", str(tmp_path))

    settings_a = Settings(_env_file=None)
    settings_b = Settings(_env_file=None)

    assert settings_a.jwt_signing_key != "change-me-in-production"
    assert settings_a.jwt_signing_key == settings_b.jwt_signing_key
    assert settings_a.secret_encryption_key == settings_b.secret_encryption_key
    Fernet(settings_a.secret_encryption_key.encode())


def test_non_development_requires_explicit_security_secrets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "change-me-in-production")
    monkeypatch.delenv("SECRET_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DEV_SECRET_DIR", str(tmp_path))

    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _ = settings.jwt_signing_key
    with pytest.raises(RuntimeError, match="SECRET_ENCRYPTION_KEY"):
        _ = settings.secret_encryption_key


def test_non_development_accepts_explicit_secrets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fernet_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("DEV_SECRET_DIR", str(tmp_path))

    settings = Settings(_env_file=None)

    assert settings.jwt_signing_key == "x" * 32
    assert settings.secret_encryption_key == fernet_key
