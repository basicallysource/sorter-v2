"""Persistent Hive API-key store for the training CLI.

Stored at ``$XDG_CONFIG_HOME/training/auth.json`` (or ``~/.config/training/auth.json``
if ``XDG_CONFIG_HOME`` is unset). File permissions are 0o600.

Schema:
    {
      "targets": {
        "<normalized hive url>": {
          "api_key": "hv_...",
          "added_at": "2026-04-17T…"
        }
      }
    }
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "training"


def _config_path() -> Path:
    return _config_dir() / "auth.json"


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _load() -> dict:
    path = _config_path()
    if not path.exists():
        return {"targets": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"targets": {}}
    if not isinstance(data, dict):
        return {"targets": {}}
    data.setdefault("targets", {})
    return data


def _save(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def set_token(hive_url: str, api_key: str) -> None:
    data = _load()
    data["targets"][_normalize_url(hive_url)] = {
        "api_key": api_key,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(data)


def get_token(hive_url: str) -> str | None:
    data = _load()
    entry = data["targets"].get(_normalize_url(hive_url))
    if not entry:
        return None
    token = entry.get("api_key")
    return token if isinstance(token, str) and token else None


def delete_token(hive_url: str) -> bool:
    data = _load()
    key = _normalize_url(hive_url)
    if key not in data["targets"]:
        return False
    data["targets"].pop(key)
    _save(data)
    return True


def list_targets() -> list[dict]:
    data = _load()
    return [
        {
            "url": url,
            "token_prefix": (entry.get("api_key", "")[:9] or "")
            + ("…" if entry.get("api_key") else ""),
            "added_at": entry.get("added_at"),
        }
        for url, entry in sorted(data["targets"].items())
    ]
