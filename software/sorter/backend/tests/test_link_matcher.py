import json
import math
from pathlib import Path

import numpy as np
import pytest

import link_matcher


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        pass

    def debug(self, *a, **kw) -> None:
        pass


class _GC:
    def __init__(self) -> None:
        self.logger = _Logger()


@pytest.fixture(autouse=True)
def _clear_cache():
    link_matcher.invalidateCache()
    yield
    link_matcher.invalidateCache()


class TestCandidateMeta:
    """The 11-d vector must match training exactly — a reorder scores garbage
    silently rather than raising, so pin every slot."""

    def test_feature_order_and_scaling(self) -> None:
        meta = link_matcher.candidateMeta(
            {"dt": 3.0, "channel": 3, "zone_code": 2, "com_forward_to_exit_deg": 90.0}
        )
        assert meta.shape == (link_matcher.META_DIM,)
        assert meta.dtype == np.float32
        expected = [
            3.0 / 30.0,                    # dt/30
            math.log1p(3.0) / 4.0,         # log1p(max(dt,0))/4
            0.0,                           # ch==2
            1.0,                           # ch==3
            0.0,                           # zone==0
            0.0,                           # zone==1
            1.0,                           # zone==2
            0.0,                           # zone==3
            90.0 / 180.0,                  # deg/180
            90.0 / 180.0,                  # abs(deg)/180
            1.0,                           # at_exit (zone 2)
        ]
        assert np.allclose(meta, np.asarray(expected, dtype=np.float32))

    def test_negative_dt_does_not_break_log(self) -> None:
        # A crop captured AFTER the piece reached C4 gives dt < 0; log1p of a
        # negative is a domain error, so training clamps at 0 and we must too.
        meta = link_matcher.candidateMeta({"dt": -2.0, "channel": 2, "zone_code": 0})
        assert meta[0] == pytest.approx(-2.0 / 30.0)
        assert meta[1] == 0.0

    def test_at_exit_from_small_angle_without_exit_zone(self) -> None:
        meta = link_matcher.candidateMeta(
            {"dt": 1.0, "channel": 2, "zone_code": 0, "com_forward_to_exit_deg": 5.0}
        )
        assert meta[10] == 1.0

    def test_missing_fields_default_without_raising(self) -> None:
        meta = link_matcher.candidateMeta({})
        assert meta.shape == (link_matcher.META_DIM,)
        # zone defaults to -1 → no zone one-hot set
        assert list(meta[4:8]) == [0.0, 0.0, 0.0, 0.0]
        # deg defaults 0 → abs(deg) < 20 → at_exit
        assert meta[10] == 1.0


def _write_model_dir(tmp_path: Path, meta: dict) -> Path:
    d = tmp_path / "hive-link-onnx"
    (d / "exports").mkdir(parents=True)
    (d / "exports" / "encoder.onnx").write_bytes(b"not a real onnx")
    (d / "exports" / "head.onnx").write_bytes(b"not a real onnx")
    (d / "run.json").write_text(json.dumps(meta))
    return d


class TestMetaContractGuard:
    """A model trained on different meta features must refuse to load rather
    than silently mispredict — that was the whole point of baking
    meta_features into training_metadata at publish time."""

    def test_mismatched_meta_features_refuses_to_load(self, tmp_path: Path) -> None:
        gc = _GC()
        d = _write_model_dir(
            tmp_path,
            {"meta_features": "dt/30, ch==2, something_else_entirely", "meta_dim": 11},
        )
        assert link_matcher.loadModel(gc, "hive-link-onnx", d) is None
        assert any("meta_features mismatch" in e for e in gc.logger.errors)

    def test_mismatched_meta_dim_refuses_to_load(self, tmp_path: Path) -> None:
        gc = _GC()
        d = _write_model_dir(
            tmp_path, {"meta_features": link_matcher.META_FEATURES, "meta_dim": 17}
        )
        assert link_matcher.loadModel(gc, "hive-link-onnx", d) is None
        assert any("meta_dim" in e for e in gc.logger.errors)

    def test_whitespace_differences_are_tolerated(self, tmp_path: Path) -> None:
        # Same contract, reflowed. Must NOT trip the guard.
        gc = _GC()
        reflowed = link_matcher.META_FEATURES.replace(", ", ",  ").replace("; ", ";\n")
        d = _write_model_dir(tmp_path, {"meta_features": reflowed, "meta_dim": 11})
        link_matcher.loadModel(gc, "hive-link-onnx", d)
        assert not any("meta_features mismatch" in e for e in gc.logger.errors)

    def test_missing_files_refuses_to_load(self, tmp_path: Path) -> None:
        gc = _GC()
        d = tmp_path / "hive-link-onnx"
        (d / "exports").mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({"meta_dim": 11}))
        assert link_matcher.loadModel(gc, "hive-link-onnx", d) is None

    def test_load_failure_is_sticky(self, tmp_path: Path) -> None:
        # Retrying a broken model on every classified piece would spam the
        # classify thread with the same error.
        gc = _GC()
        d = _write_model_dir(
            tmp_path, {"meta_features": "totally different", "meta_dim": 11}
        )
        assert link_matcher.loadModel(gc, "hive-link-onnx", d) is None
        first = len(gc.logger.errors)
        assert link_matcher.loadModel(gc, "hive-link-onnx", d) is None
        assert len(gc.logger.errors) == first


class TestScoreCandidates:
    def test_empty_candidates_is_empty_not_none(self) -> None:
        # [] means "heuristic found nothing"; None means "model could not run".
        # The endpoint distinguishes them, so keep them distinct.
        assert link_matcher.scoreCandidates(_GC(), object(), "uuid", []) == []
