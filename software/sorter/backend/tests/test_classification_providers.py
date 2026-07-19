import threading
import time
from types import SimpleNamespace

from classification.providers import (
    COLOR_PROVIDER_BRICKOGNIZE,
    COLOR_PROVIDER_HIVE_BASICALLY,
    MOLD_PROVIDER_BRICKOGNIZE,
)
from subsystems.classification_channel.simple_state_machine_rev01.base import (
    Rev01BaseState,
)
from subsystems.classification_channel.simple_state_machine_rev01.context import (
    SimpleStateMachineRev01Context,
)


class _Logger:
    def info(self, *_a, **_k) -> None: ...
    def warning(self, *_a, **_k) -> None: ...
    def warn(self, *_a, **_k) -> None: ...
    def error(self, *_a, **_k) -> None: ...


def _base() -> Rev01BaseState:
    # Only _resolveHostedColor / updateKnownObjectWithResult are exercised, so
    # the state machine's hardware deps are never constructed.
    obj = Rev01BaseState.__new__(Rev01BaseState)
    obj.logger = _Logger()
    # The metadata lookups off the classified path are best-effort and log
    # through gc; they must not be what decides provider provenance.
    obj.gc = SimpleNamespace(logger=_Logger())
    obj.event_queue = SimpleNamespace(put=lambda _e: None)
    # The real context, so this test tracks the fields the state machine
    # actually carries rather than a hand-rolled stand-in that drifts.
    obj.ctx = SimpleStateMachineRev01Context()
    return obj


def _settledHolder(result: object) -> dict:
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    holder: dict = {"started_at": time.monotonic(), "thread": thread}
    if result is not None:
        holder["result"] = result
    return holder


def test_no_hosted_provider_records_brickognize() -> None:
    base = _base()

    base._resolveHostedColor(None)

    assert base.ctx.color_provider == COLOR_PROVIDER_BRICKOGNIZE
    assert base.ctx.hosted_color is None


def test_hosted_color_answer_is_recorded_and_overrides() -> None:
    base = _base()

    base._resolveHostedColor(
        _settledHolder({"color_id": 11, "color_name": "Black"})
    )

    assert base.ctx.color_provider == COLOR_PROVIDER_HIVE_BASICALLY
    # Hive returns ints; the sorting profile keys on string ids.
    assert base.ctx.hosted_color == ("11", "Black")


def test_hosted_color_timeout_falls_back_and_records_brickognize() -> None:
    # The provider was configured but produced nothing — the piece is sorted on
    # Brickognize's color, so that is what must be recorded.
    base = _base()

    base._resolveHostedColor(_settledHolder(None))

    assert base.ctx.color_provider == COLOR_PROVIDER_BRICKOGNIZE
    assert base.ctx.hosted_color is None


def test_hosted_color_partial_payload_falls_back() -> None:
    base = _base()

    base._resolveHostedColor(_settledHolder({"color_id": 11}))

    assert base.ctx.color_provider == COLOR_PROVIDER_BRICKOGNIZE
    assert base.ctx.hosted_color is None


def test_known_object_records_provider_and_hosted_color_wins() -> None:
    from defs.known_object import ClassificationStatus, KnownObject

    base = _base()
    base.ctx.color_provider = COLOR_PROVIDER_HIVE_BASICALLY
    base.ctx.hosted_color = ("11", "Black")
    piece = KnownObject(uuid="u1")
    base.ctx.known_object = piece
    base.ctx.captured_crops = []
    base.sharpness = lambda _f: 0.0

    base.updateKnownObjectWithResult(
        {
            "items": [{"id": "3001", "name": "Brick 2x4", "score": 0.9}],
            "colors": [{"id": "5", "name": "Red", "score": 0.8}],
        },
        None,
    )

    assert piece.classification_status == ClassificationStatus.classified
    assert piece.color_id == "11"
    assert piece.color_name == "Black"
    assert piece.color_provider == COLOR_PROVIDER_HIVE_BASICALLY
    assert piece.mold_provider == MOLD_PROVIDER_BRICKOGNIZE


def test_known_object_keeps_brickognize_color_without_hosted_answer() -> None:
    from defs.known_object import KnownObject

    base = _base()
    piece = KnownObject(uuid="u2")
    base.ctx.known_object = piece
    base.ctx.captured_crops = []
    base.sharpness = lambda _f: 0.0

    base.updateKnownObjectWithResult(
        {
            "items": [{"id": "3001", "name": "Brick 2x4", "score": 0.9}],
            "colors": [{"id": "5", "name": "Red", "score": 0.8}],
        },
        None,
    )

    assert piece.color_id == "5"
    assert piece.color_name == "Red"
    assert piece.color_provider == COLOR_PROVIDER_BRICKOGNIZE
