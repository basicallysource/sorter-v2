from __future__ import annotations

from rt.shadow.config import SHADOW_ROLE_ALLOWLIST, parse_shadow_feeds_env


def test_empty_env_returns_empty_list() -> None:
    assert parse_shadow_feeds_env("") == []
    assert parse_shadow_feeds_env(None) == []  # real os.environ lookup
    assert parse_shadow_feeds_env("   ") == []


def test_single_role() -> None:
    assert parse_shadow_feeds_env("c2") == ["c2"]


def test_comma_separated_roles_preserve_order() -> None:
    assert parse_shadow_feeds_env("c3,c2") == ["c3", "c2"]


def test_whitespace_and_case_insensitive() -> None:
    assert parse_shadow_feeds_env(" C2 , c3 ") == ["c2", "c3"]


def test_duplicates_collapsed() -> None:
    assert parse_shadow_feeds_env("c2,c2,c3") == ["c2", "c3"]


def test_unknown_role_skipped() -> None:
    # "c9" is not allowed — silently dropped, valid neighbors survive.
    assert parse_shadow_feeds_env("c9,c2") == ["c2"]


def test_allowlist_stable() -> None:
    # Stability guard so a thoughtless extension doesn't drop existing roles.
    assert {"c1", "c2", "c3", "c4"}.issubset(SHADOW_ROLE_ALLOWLIST)


def test_reads_os_environ(monkeypatch) -> None:
    monkeypatch.setenv("RT_SHADOW_FEEDS", "c2,c4")
    assert parse_shadow_feeds_env() == ["c2", "c4"]


def test_os_environ_unset(monkeypatch) -> None:
    monkeypatch.delenv("RT_SHADOW_FEEDS", raising=False)
    assert parse_shadow_feeds_env() == []
