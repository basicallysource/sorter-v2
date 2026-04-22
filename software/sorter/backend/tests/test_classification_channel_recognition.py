from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from defs.known_object import ClassificationStatus
from subsystems.classification_channel.recognition import (
    CROP_REFLECTION_PAD_RATIO,
    MIN_SHARPNESS_LAPLACIAN_VAR,
    ClassificationChannelRecognizer,
)


def _sharp_crop(seed: int = 7) -> np.ndarray:
    """Produce a crop with Laplacian variance comfortably above the sharpness
    floor so existing tests that only care about the fire/not-fire branch
    aren't tripped by the blur gate added to ``fire()``.
    """
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(32, 32, 3), dtype=np.uint8)


class _Logger:
    def debug(self, *args, **kwargs) -> None:
        pass

    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


class _Transport:
    def __init__(self) -> None:
        self.pending_marked: list[str] = []
        self.fallback_calls: list[tuple[str, ClassificationStatus]] = []

    def markPendingClassification(self, piece) -> None:
        self.pending_marked.append(piece.uuid)

    def resolveFallbackClassification(self, uuid: str, *, status: ClassificationStatus) -> bool:
        self.fallback_calls.append((uuid, status))
        return True

    def resolveClassification(self, *args, **kwargs) -> bool:
        return True


class _RuntimeStats:
    def __init__(self) -> None:
        self.recognizer_counts: dict[str, int] = {}
        self.blocked_reasons: list[tuple[str, str]] = []

    def observeRecognizerCounter(self, name: str) -> None:
        self.recognizer_counts[name] = self.recognizer_counts.get(name, 0) + 1

    def observeBlockedReason(self, machine: str, reason: str) -> None:
        self.blocked_reasons.append((machine, reason))


class _Recognizer(ClassificationChannelRecognizer):
    def __init__(
        self,
        crops: list[np.ndarray] | list[tuple[np.ndarray, str]],
        transport: _Transport,
        runtime_stats: _RuntimeStats | None = None,
    ) -> None:
        super().__init__(
            gc=SimpleNamespace(runtime_stats=runtime_stats or _RuntimeStats()),
            logger=_Logger(),
            vision=None,
            transport=transport,
            event_queue=None,
        )
        normalized: list[tuple[np.ndarray, str, float]] = []
        for idx, entry in enumerate(crops):
            ts = 1000.0 + idx
            if isinstance(entry, tuple):
                if len(entry) == 3:
                    normalized.append(entry)
                else:
                    img, role = entry
                    normalized.append((img, role, ts))
            else:
                # Default bare np.ndarray crops to the carousel source so
                # pre-existing tests continue to represent the common "piece
                # has already landed on C4" case rather than "still upstream".
                normalized.append((entry, "carousel", ts))
        self._crops = normalized
        self.async_calls: list[tuple[str, int]] = []

    def _collectTrackedImages(self, piece) -> list[tuple[np.ndarray, str, float]]:
        return list(self._crops)

    def _classifyImagesAsync(self, piece, images) -> None:
        self.async_calls.append((piece.uuid, len(images)))


class _Vision:
    def __init__(
        self,
        details_by_id: dict[int, dict],
        fallback_by_role: dict[str, dict | None],
    ) -> None:
        self._details_by_id = details_by_id
        self._fallback_by_role = fallback_by_role

    def getFeederTrackHistoryDetail(self, global_id: int):
        return self._details_by_id.get(int(global_id))

    def findRecentFeederTrackHistoryDetailByRole(
        self,
        *,
        source_role: str,
        before_ts: float,
        max_age_s: float = 6.0,
        limit: int = 40,
    ):
        return self._fallback_by_role.get(source_role)


def _piece() -> SimpleNamespace:
    return SimpleNamespace(
        uuid="piece-1",
        tracked_global_id=17,
        classification_status=ClassificationStatus.pending,
        color_id="any_color",
        color_name="Any Color",
        thumbnail=None,
        updated_at=0.0,
    )


def test_recognizer_waits_when_no_crops_available() -> None:
    transport = _Transport()
    runtime_stats = _RuntimeStats()
    recognizer = _Recognizer(crops=[], transport=transport, runtime_stats=runtime_stats)
    piece = _piece()

    fired = recognizer.fire(piece)

    assert fired is False
    assert piece.classification_status == ClassificationStatus.pending
    assert transport.pending_marked == []
    assert transport.fallback_calls == []
    assert runtime_stats.recognizer_counts.get("recognize_skipped_no_crops") == 1
    assert runtime_stats.recognizer_counts.get("recognize_fired_total", 0) == 0


def test_recognizer_starts_async_classification_once_enough_crops_exist() -> None:
    transport = _Transport()
    runtime_stats = _RuntimeStats()
    recognizer = _Recognizer(
        crops=[_sharp_crop(seed=idx) for idx in range(2)],
        transport=transport,
        runtime_stats=runtime_stats,
    )
    piece = _piece()

    fired = recognizer.fire(piece)

    assert fired is True
    assert piece.classification_status == ClassificationStatus.classifying
    assert transport.pending_marked == ["piece-1"]
    assert transport.fallback_calls == []
    assert recognizer.async_calls == [("piece-1", 2)]
    assert runtime_stats.recognizer_counts.get("recognize_fired_total") == 1
    assert runtime_stats.recognizer_counts.get("recognize_skipped_no_crops", 0) == 0


def test_recognizer_skips_when_only_upstream_crops_available() -> None:
    # 3 c3 crops, 0 carousel -> must skip and bump the dedicated counter.
    transport = _Transport()
    runtime_stats = _RuntimeStats()
    recognizer = _Recognizer(
        crops=[(_sharp_crop(seed=idx), "c_channel_3") for idx in range(3)],
        transport=transport,
        runtime_stats=runtime_stats,
    )
    piece = _piece()

    fired = recognizer.fire(piece)

    assert fired is False
    assert transport.pending_marked == []
    assert (
        runtime_stats.recognizer_counts.get("recognize_skipped_no_carousel_crops")
        == 1
    )
    # Must NOT bump the "no crops at all" counter since we DID have c3 crops.
    assert runtime_stats.recognizer_counts.get("recognize_skipped_no_crops", 0) == 0


def test_recognizer_fires_once_carousel_crop_is_present() -> None:
    transport = _Transport()
    runtime_stats = _RuntimeStats()
    recognizer = _Recognizer(
        crops=[
            (_sharp_crop(seed=1), "c_channel_3"),
            (_sharp_crop(seed=2), "carousel"),
        ],
        transport=transport,
        runtime_stats=runtime_stats,
    )
    piece = _piece()

    fired = recognizer.fire(piece)

    assert fired is True
    assert (
        runtime_stats.recognizer_counts.get("recognize_skipped_no_carousel_crops", 0)
        == 0
    )
    assert runtime_stats.recognizer_counts.get("recognize_fired_total") == 1


def test_recognizer_bumps_empty_and_timeout_counters() -> None:
    transport = _Transport()
    runtime_stats = _RuntimeStats()
    recognizer = _Recognizer(crops=[], transport=transport, runtime_stats=runtime_stats)

    # Simulate the two branches that live inside _classifyImagesAsync's nested
    # closures. We invoke the helper directly because those closures run on
    # background threads and the branch logic is a single increment either way.
    recognizer._bumpRecognizerCounter("brickognize_empty_result")
    recognizer._bumpRecognizerCounter("brickognize_timeout_total")

    assert runtime_stats.recognizer_counts.get("brickognize_empty_result") == 1
    assert runtime_stats.recognizer_counts.get("brickognize_timeout_total") == 1


def test_collect_tracked_images_adds_c2_fallback_when_direct_detail_lacks_it() -> None:
    crop = np.zeros((10, 10, 3), dtype=np.uint8)
    payload = ClassificationChannelRecognizer._encodeImageBase64(crop)
    assert payload is not None

    direct_detail = {
        "global_id": 17,
        "segments": [
            {
                "source_role": "c_channel_3",
                "first_seen_ts": 100.0,
                "sector_snapshots": [
                    {"captured_ts": 100.0, "piece_jpeg_b64": payload},
                ],
            },
            {
                "source_role": "carousel",
                "first_seen_ts": 112.0,
                "sector_snapshots": [
                    {"captured_ts": 112.0, "piece_jpeg_b64": payload},
                ],
            },
        ],
    }
    c2_detail = {
        "global_id": 7,
        "segments": [
            {
                "source_role": "c_channel_2",
                "first_seen_ts": 94.0,
                "sector_snapshots": [
                    {"captured_ts": 94.0, "piece_jpeg_b64": payload},
                ],
            }
        ],
    }
    recognizer = ClassificationChannelRecognizer(
        gc=SimpleNamespace(runtime_stats=SimpleNamespace(observeBlockedReason=lambda *a, **k: None)),
        logger=_Logger(),
        vision=_Vision({17: direct_detail}, {"c_channel_2": c2_detail, "c_channel_3": None}),
        transport=_Transport(),
        event_queue=None,
    )
    piece = _piece()

    images = recognizer._collectTrackedImages(piece)

    assert len(images) == 3
    for entry in images:
        assert isinstance(entry, tuple)
        assert len(entry) == 3
        assert entry[1] in {"c_channel_2", "c_channel_3", "carousel"}
        # captured_ts is carried through verbatim.
        assert isinstance(entry[2], float)


def _make_crop(sharpness_seed: int) -> np.ndarray:
    # Generate a patterned crop whose Laplacian variance is roughly proportional
    # to the seed so tests can reason about which crop is the sharpest.
    rng = np.random.default_rng(sharpness_seed)
    high = max(2, min(256, sharpness_seed * 4 + 1))
    base = rng.integers(0, high, size=(32, 32, 3), dtype=np.uint8)
    return base.astype(np.uint8)


def test_select_crops_quota_reserves_c3_slots() -> None:
    # 10 crops: 6 c2, 2 c3, 2 carousel. Sharpness is ordered so c3 crops are
    # NOT among the top 8 by Laplacian alone — yet both should still land in
    # the final selection thanks to the quota.
    crops: list[tuple[np.ndarray, str, float]] = []
    for idx in range(6):
        # c2 crops get the highest sharpness seeds (100-105)
        crops.append((_make_crop(100 + idx), "c_channel_2", float(idx)))
    # c3 crops with modest sharpness (50-51)
    crops.append((_make_crop(50), "c_channel_3", 6.0))
    crops.append((_make_crop(51), "c_channel_3", 7.0))
    # carousel crops with low sharpness (10-11)
    crops.append((_make_crop(10), "carousel", 8.0))
    crops.append((_make_crop(11), "carousel", 9.0))

    selected = ClassificationChannelRecognizer._selectCropsWithSourceQuota(
        crops, max_count=8, c3_quota_ratio=0.25
    )

    assert len(selected) == 8
    roles = [role for _image, role, _ts in selected]
    assert roles.count("c_channel_3") == 2, f"expected 2 c3 crops, got roles={roles}"
    # Sharpest c3 should be placed at position 0 per the opinionated ordering.
    assert selected[0][1] == "c_channel_3"


def test_select_crops_quota_falls_back_when_no_c3() -> None:
    # 10 c2 crops, 0 c3 — quota slots must be filled from the general pool so
    # no slot is wasted.
    crops: list[tuple[np.ndarray, str, float]] = [
        (_make_crop(10 + idx), "c_channel_2", float(idx)) for idx in range(10)
    ]

    selected = ClassificationChannelRecognizer._selectCropsWithSourceQuota(
        crops, max_count=8, c3_quota_ratio=0.25
    )

    assert len(selected) == 8
    assert all(role == "c_channel_2" for _image, role, _ts in selected)


def test_select_crops_quota_small_pool_returns_all() -> None:
    # 3 crops total: 1 c3, 2 c2 — all must be returned and c3 must be present.
    crops: list[tuple[np.ndarray, str, float]] = [
        (_make_crop(50), "c_channel_3", 1.0),
        (_make_crop(20), "c_channel_2", 2.0),
        (_make_crop(80), "c_channel_2", 3.0),
    ]

    selected = ClassificationChannelRecognizer._selectCropsWithSourceQuota(
        crops, max_count=8, c3_quota_ratio=0.25
    )

    assert len(selected) == 3
    roles = [role for _image, role, _ts in selected]
    assert "c_channel_3" in roles


def test_recognizer_skips_when_all_crops_below_sharpness_floor() -> None:
    # Flat grey crops have Laplacian variance ~0 — well below the floor.
    # fire() must return False, no classification should be queued, and the
    # dedicated counter should increment so operators can see the defer rate.
    transport = _Transport()
    runtime_stats = _RuntimeStats()
    blurry = [np.full((32, 32, 3), 128, dtype=np.uint8) for _ in range(3)]
    recognizer = _Recognizer(
        crops=[(img, "carousel") for img in blurry],
        transport=transport,
        runtime_stats=runtime_stats,
    )
    piece = _piece()

    fired = recognizer.fire(piece)

    assert fired is False
    assert piece.classification_status == ClassificationStatus.pending
    assert transport.pending_marked == []
    assert recognizer.async_calls == []
    assert (
        runtime_stats.recognizer_counts.get("recognize_skipped_low_sharpness")
        == 1
    )
    assert runtime_stats.recognizer_counts.get("recognize_fired_total", 0) == 0
    # Sanity: no false-positive on the unrelated skip counters.
    assert runtime_stats.recognizer_counts.get("recognize_skipped_no_crops", 0) == 0


def test_pad_crop_for_brickognize_adds_reflective_border() -> None:
    # Padding should add a border proportional to the smaller edge. With a
    # 32x32 crop and 0.15 ratio we expect pad=5 on each side -> 42x42 output.
    crop = np.random.default_rng(42).integers(
        0, 256, size=(32, 32, 3), dtype=np.uint8
    )
    padded = ClassificationChannelRecognizer._padCropForBrickognize(crop)

    expected_pad = int(round(32 * CROP_REFLECTION_PAD_RATIO))
    assert padded.shape == (32 + 2 * expected_pad, 32 + 2 * expected_pad, 3)
    # The interior (non-border) region must match the original crop verbatim so
    # we know we padded rather than scaled.
    inner = padded[expected_pad:-expected_pad, expected_pad:-expected_pad]
    assert np.array_equal(inner, crop)
    # Sharpness floor constant is non-zero — guard against accidental bypass.
    assert MIN_SHARPNESS_LAPLACIAN_VAR > 0.0


def test_pad_crop_for_brickognize_is_noop_on_zero_ratio() -> None:
    crop = np.zeros((20, 20, 3), dtype=np.uint8)
    padded = ClassificationChannelRecognizer._padCropForBrickognize(
        crop, pad_ratio=0.0
    )
    assert padded.shape == crop.shape


def test_select_crops_quota_top_slot_is_sharpest_c3_when_present() -> None:
    # Pool with 9 crops; confirm index 0 is a c3 crop and that it is the
    # sharpest c3 in the pool.
    c3_low = (_make_crop(30), "c_channel_3", 1.0)
    c3_high = (_make_crop(60), "c_channel_3", 2.0)
    c2_crops = [(_make_crop(100 + idx), "c_channel_2", float(10 + idx)) for idx in range(7)]

    crops: list[tuple[np.ndarray, str, float]] = [c3_low] + c2_crops + [c3_high]

    selected = ClassificationChannelRecognizer._selectCropsWithSourceQuota(
        crops, max_count=8, c3_quota_ratio=0.25
    )

    assert len(selected) == 8
    assert selected[0][1] == "c_channel_3"
    # Sharpest c3 (higher seed) should beat the lower-sharpness c3 for slot 0.
    # Use the actual Laplacian var to confirm rather than identity.
    top_gray = (
        selected[0][0]
        if selected[0][0].ndim == 2
        else __import__("cv2").cvtColor(selected[0][0], __import__("cv2").COLOR_BGR2GRAY)
    )
    import cv2 as _cv2  # local import for clarity
    top_var = float(_cv2.Laplacian(top_gray, _cv2.CV_64F).var())
    low_gray = _cv2.cvtColor(c3_low[0], _cv2.COLOR_BGR2GRAY)
    low_var = float(_cv2.Laplacian(low_gray, _cv2.CV_64F).var())
    assert top_var >= low_var
