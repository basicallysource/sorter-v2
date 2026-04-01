"""Shared test fixtures for SortHive backend tests."""

from __future__ import annotations

import hashlib
import io
import os
import secrets
import shutil
import tempfile
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["JWT_SECRET"] = "test-secret-key-not-for-production"

from app.deps import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.machine import Machine  # noqa: E402
from app.routers.auth import limiter as auth_limiter  # noqa: E402
from app.routers.machines import limiter as machine_limiter  # noqa: E402
from app.routers.upload import limiter as upload_limiter  # noqa: E402


TEST_DB_URL = "sqlite:///test.db"

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def _setup_db() -> Generator[None, None, None]:
    """Create all tables before each test and drop them after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    """Provide a database session for direct DB manipulation in tests."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db: Session) -> TestClient:
    """FastAPI TestClient with overridden DB dependency."""

    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    app.state.limiter.enabled = False
    auth_limiter.enabled = False
    machine_limiter.enabled = False
    upload_limiter.enabled = False
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
    app.state.limiter.enabled = True
    auth_limiter.enabled = True
    machine_limiter.enabled = True
    upload_limiter.enabled = True


@pytest.fixture()
def upload_dir(tmp_path: object) -> Generator[str, None, None]:
    """Provide a temporary upload directory."""
    d = tempfile.mkdtemp()
    os.environ["UPLOAD_DIR"] = d
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _register_user(
    client: TestClient, email: str, password: str, display_name: str = "Test"
) -> dict:
    """Register a user and return the response JSON."""
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert resp.status_code == 200 or resp.status_code == 201, resp.text
    return resp.json()


def _login_user(client: TestClient, email: str, password: str) -> dict:
    """Log in and return response JSON. Cookies are set on the client."""
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth_headers(client: TestClient) -> dict[str, str]:
    """Extract CSRF token from cookies and return headers for unsafe requests."""
    csrf = client.cookies.get("csrf_token", "")
    return {"X-CSRF-Token": csrf}


@pytest.fixture()
def test_user(client: TestClient) -> dict:
    """Register and log in a standard member user."""
    _register_user(client, "member@test.com", "Password123!", "Member User")
    data = _login_user(client, "member@test.com", "Password123!")
    return {"email": "member@test.com", "password": "Password123!", **data}


@pytest.fixture()
def test_reviewer(client: TestClient, db: Session) -> dict:
    """Register, log in, and promote a user to reviewer role."""
    _register_user(client, "reviewer@test.com", "Password123!", "Reviewer User")
    _login_user(client, "reviewer@test.com", "Password123!")
    # Promote to reviewer directly in DB
    user = db.query(User).filter(User.email == "reviewer@test.com").first()
    user.role = "reviewer"
    db.commit()
    return {"email": "reviewer@test.com", "password": "Password123!"}


@pytest.fixture()
def auth_headers(client: TestClient, test_user: dict) -> dict[str, str]:
    """Return headers with CSRF token for the logged-in test_user."""
    return _auth_headers(client)


@pytest.fixture()
def test_machine(client: TestClient, test_user: dict, auth_headers: dict) -> dict:
    """Create a machine and return its info including the raw token."""
    resp = client.post(
        "/api/machines",
        json={"name": "Test Sorter", "description": "A test machine"},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.fixture()
def machine_token(test_machine: dict) -> str:
    """Return the raw API token for the test machine (shown only at creation)."""
    return test_machine["raw_token"]


def make_test_image(width: int = 100, height: int = 100, fmt: str = "png") -> io.BytesIO:
    """Create a minimal valid PNG or JPEG image for upload tests."""
    if fmt == "png":
        # Minimal 1x1 red PNG
        import struct
        import zlib

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            c = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + c + crc

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        # Raw image data: filter byte 0 + RGB per pixel per row
        raw = b""
        for _ in range(height):
            raw += b"\x00" + b"\xff\x00\x00" * width
        idat = zlib.compress(raw)
        png = sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
        buf = io.BytesIO(png)
    else:
        # Minimal JPEG: use a simple JFIF stub
        buf = io.BytesIO(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        )
    buf.seek(0)
    return buf
