from __future__ import annotations

import pytest

from rt.contracts.registry import StrategyRegistry


class _Thing:
    def __init__(self, value: int = 0) -> None:
        self.value = value


def test_register_and_create_round_trip() -> None:
    registry: StrategyRegistry[_Thing] = StrategyRegistry("thing")
    registry.register("foo", _Thing)

    created = registry.create("foo", value=42)

    assert isinstance(created, _Thing)
    assert created.value == 42
    assert "foo" in registry.keys()


def test_register_duplicate_key_raises() -> None:
    registry: StrategyRegistry[_Thing] = StrategyRegistry("thing")
    registry.register("foo", _Thing)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("foo", _Thing)


def test_create_unknown_key_raises_lookup_error() -> None:
    registry: StrategyRegistry[_Thing] = StrategyRegistry("thing")

    with pytest.raises(LookupError, match="Unknown thing strategy"):
        registry.create("missing")
