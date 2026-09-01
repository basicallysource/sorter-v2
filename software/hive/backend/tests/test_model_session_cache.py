"""Both predictors keep exactly one loaded model, not every one they have seen.

Regression cover for the leak found on 2026-08-20: `_load` cached into a dict
keyed by (name/filename, sha256) with no eviction, so every model version ever
activated kept its ONNX session — two, for link models — resident for the life
of the process. Only one model is ever active, so one slot is all there is.

Sessions are stubbed. A real graph would need the `onnx` package to build (see
test_color_predict.py), and none of this is about inference anyway.
"""

from __future__ import annotations

import gc
import types
import weakref


class _FakeSession:
    """Stands in for ort.InferenceSession, and counts how many were built."""

    def __init__(self, *args, **kwargs):
        pass

    def get_inputs(self):
        return [types.SimpleNamespace(name="input")]

    def get_outputs(self):
        return [types.SimpleNamespace(name="output")]


def _counting_session(made: list):
    class Counting(_FakeSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(1)  # a count, not the object — a strong ref here would
            # defeat the weakref check below

    return Counting


def test_color_predictor_keeps_only_the_active_model(tmp_path, monkeypatch):
    from app.services import color_predictor as cp

    (tmp_path / "colorpred.onnx").write_bytes(b"stub")
    made: list = []
    monkeypatch.setattr(cp, "model_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "_read_metadata", lambda path: {"hive.classes": "[1, 2]", "hive.input_size": "64"})
    monkeypatch.setattr(cp.ort, "InferenceSession", _counting_session(made))
    monkeypatch.setattr(cp, "_loaded_key", None)
    monkeypatch.setattr(cp, "_loaded_model", None)

    v1 = types.SimpleNamespace(filename="colorpred.onnx", sha256="aaa")
    v2 = types.SimpleNamespace(filename="colorpred.onnx", sha256="bbb")

    first = cp._load(v1)
    assert first is not None
    assert cp._load(v1) is first, "same sha should hit the slot, not rebuild"
    assert len(made) == 1

    # The point of the fix: activating a new version must release the old
    # session, not park it in a dict forever.
    released = weakref.ref(first.session)
    del first
    second = cp._load(v2)
    assert len(made) == 2
    assert cp._loaded_key == ("colorpred.onnx", "bbb")
    assert cp._loaded_model is second
    gc.collect()
    assert released() is None, "the superseded model's ONNX session is still resident"


def test_link_predictor_keeps_only_the_active_model(tmp_path, monkeypatch):
    from app.services import link_predictor as lp

    (tmp_path / "enc.onnx").write_bytes(b"stub")
    (tmp_path / "head.onnx").write_bytes(b"stub")
    made: list = []
    monkeypatch.setattr(lp, "model_dir", lambda: tmp_path)
    monkeypatch.setattr(lp.ort, "InferenceSession", _counting_session(made))
    monkeypatch.setattr(lp, "_loaded_key", None)
    monkeypatch.setattr(lp, "_loaded_model", None)

    def row(sha: str):
        return types.SimpleNamespace(
            name="link", sha256=sha, encoder_filename="enc.onnx", head_filename="head.onnx", input_size=64
        )

    v1, v2 = row("aaa"), row("bbb")

    first = lp._load(v1)
    assert first is not None
    assert lp._load(v1) is first, "same sha should hit the slot, not rebuild"
    assert len(made) == 2, "one encoder + one head"

    # A link model is two sessions, so a leak here cost double.
    released = [weakref.ref(first.encoder), weakref.ref(first.head)]
    del first
    second = lp._load(v2)
    assert len(made) == 4
    assert lp._loaded_key == ("link", "bbb")
    assert lp._loaded_model is second
    gc.collect()
    assert [r() for r in released] == [None, None], "superseded encoder/head still resident"
