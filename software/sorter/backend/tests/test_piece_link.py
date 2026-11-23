import importlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from piece_link import live
from piece_link.journey import Journey, Kept
from piece_link.live import LiveLinker, chooseCrops, journeyCrops
from piece_link.model import FORMAT, formatMismatch
from piece_link.nodes import K_SAME, N_CAND
from piece_link.record import Stream

FPS = 16.0
CENTER = (640.0, 360.0)


class _Logger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def warning(self, msg: str) -> None:
        self.lines.append(msg)

    info = error = debug = warning


class _GC:
    def __init__(self) -> None:
        self.logger = _Logger()


class _FakeModel:
    """Names the first candidate on the channel above when there is one,
    else the first on the anchor's own channel, else none."""

    name = "fake"
    threshold = 0.9

    def run(self, tokens: np.ndarray, mask: np.ndarray, ctx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        probs = np.zeros((len(tokens), 1 + N_CAND), dtype=np.float32)
        for i in range(len(tokens)):
            if mask[i, 1 + K_SAME]:
                probs[i, 1 + K_SAME] = 0.95
            elif mask[i, 1]:
                probs[i, 1] = 0.95
            probs[i, 0] = 1.0 - probs[i].sum()
        return probs, np.zeros(len(tokens), dtype=np.float32)


def _meta() -> dict[str, Any]:
    zone = {"center": list(CENTER), "inner_radius": 100.0, "outer_radius": 300.0, "frame": [1280, 720]}
    return {"type": "meta", "t": 1000.0, "channel_output_gear_ratio": 1.0, "zones": {"2": zone, "3": zone, "4": zone}}


def _box(deg: float) -> list[float]:
    x = CENTER[0] + 200.0 * math.cos(math.radians(deg))
    y = CENTER[1] + 200.0 * math.sin(math.radians(deg))
    return [x - 20.0, y - 20.0, x + 20.0, y + 20.0]


def _state(ch: int, ts: float, pieces: list[tuple[float, int, int]]) -> dict[str, Any]:
    return {
        "type": "state",
        "t": ts + 0.03,
        "ch": ch,
        "ts": ts,
        "pieces": [[deg, 0, zone, *_box(deg), tid, [0.1, 0.2, 0.5]] for deg, tid, zone in pieces],
    }


def _ride() -> list[dict[str, Any]]:
    """One piece rides C3 from 120 degrees to its exit while the rotor turns
    under it, drops, and lands on the classification channel as track 7."""
    records: list[dict[str, Any]] = [_meta()]
    for ch in (3, 4):
        records.append({"type": "frame_info", "t": 1000.0, "ch": ch, "w": 1280, "h": 720})
    t = 1000.0
    deg = 120.0
    step = 1.8
    while deg > 4.0:
        if int(round((t - 1000.0) * FPS)) % 8 == 0:
            records.append(
                {"type": "cmd", "cmd": "move_steps", "stepper": "c_channel_3_rotor", "deg": 8 * step, "t": t - 0.01, "success": True}
            )
        records.append(_state(3, t, [(deg, 3, 0 if deg > 40 else 2)]))
        t += 1.0 / FPS
        deg -= step
    records.append(_state(3, t, []))
    t += 0.4
    records.append({"type": "event", "kind": "c4_piece", "track": 7, "piece": "piece-1", "t": t})
    for k in range(12):
        records.append(_state(4, t + k / FPS, [(170.0, 7, 1)]))
    return records


def _fed(records: list[dict[str, Any]]) -> Stream:
    stream = Stream()
    for r in records:
        stream.ingest(r)
    return stream


def test_a_ride_is_one_tracklet_a_channel() -> None:
    win = _fed(_ride()).window()
    assert win.tls[3].n == 1
    assert win.tls[4].n == 1
    assert win.tls[3].count[0] == len(win.ch[3])
    assert win.tracksOf("piece-1") == [7]
    assert 0.45 < float(np.median(win.ch[3].rho)) < 0.55
    assert float(win.odometer(3, win.now)) == pytest.approx(8 * 1.8 * len(win.moves[3]))


def test_two_pieces_apart_stay_apart() -> None:
    records = [_meta()]
    for k in range(40):
        records.append(_state(2, 1000.0 + k / FPS, [(150.0 - 0.5 * k, 1, 0), (60.0 - 0.5 * k, 2, 0)]))
    win = _fed(records).window()
    assert win.tls[2].n == 2
    assert sorted(win.tls[2].count.tolist()) == [40, 40]


def test_trimming_keeps_tracklet_ids() -> None:
    stream = Stream(window_s=5.0)
    stream.ingest(_meta())
    for k in range(int(20 * FPS)):
        # A new piece every two seconds, each seen for one.
        if k % 32 < 16:
            stream.ingest(_state(2, 1000.0 + k / FPS, [(100.0 - (k % 32), k // 32, 0)]))
        else:
            stream.ingest(_state(2, 1000.0 + k / FPS, []))
    stream.trim()
    win = stream.window()
    assert win.ch[2].t.min() >= stream.now - 5.0 - 1.0 / FPS
    assert win.tls[2].ids.max() == 9
    assert win.tls[2].n < 10


def test_walk_goes_from_c4_back_to_c3() -> None:
    win = _fed(_ride()).window()
    journey = Journey(win, _FakeModel(), Kept())
    walk = journey.pieceWalk(win.tracksOf("piece-1"))
    assert [int(journey.nd.ch[node]) for node, _ in walk] == [4, 3]
    assert walk[0][1] == 1.0
    assert walk[1][1] == pytest.approx(0.95)


def test_kept_answers_are_not_asked_again() -> None:
    stream = _fed(_ride())
    for k in range(int(15 * FPS)):
        stream.ingest(_state(4, stream.now + 1.0 / FPS, []))
    kept = Kept()
    first = Journey(stream.window(), _FakeModel(), kept)
    again = Journey(stream.window(), _FakeModel(), kept)
    assert first.asked_fresh == 2
    assert again.asked_fresh == 0
    assert again.pred.tolist() == first.pred.tolist()


def test_crops_of_the_walk_are_found_by_frame_and_box() -> None:
    win = _fed(_ride()).window()
    journey = Journey(win, _FakeModel())
    walk = journey.pieceWalk([7])
    c3 = win.ch[3]
    rows = [
        {"id": 1, "channel": 3, "ts": float(c3.t[5]), "track_id": 3, "bbox": [float(v) for v in c3.box[5]], "sharpness": 10.0},
        {"id": 2, "channel": 3, "ts": float(c3.t[40]), "track_id": None, "bbox": [float(v) for v in c3.box[40]], "sharpness": 30.0},
        # Another piece's crop from the same frame: a box somewhere else, another track.
        {"id": 3, "channel": 3, "ts": float(c3.t[40]), "track_id": 99, "bbox": [0.0, 0.0, 40.0, 40.0], "sharpness": 50.0},
    ]
    crops = journeyCrops(journey, walk, 0.9, lambda ch, t0, t1: [r for r in rows if r["channel"] == ch and t0 <= r["ts"] <= t1])
    assert [r["id"] for r in crops[3]] == [1, 2]
    assert crops[2] == []
    assert journeyCrops(journey, walk, 0.99, lambda ch, t0, t1: rows)[3] == []
    assert [r["id"] for r in chooseCrops(crops[3], crops[2])] == [2, 1]


def test_choose_crops_spreads_and_fills() -> None:
    c3 = [{"id": i, "ts": float(i), "sharpness": 1.0} for i in range(30)]
    c2 = [{"id": 100 + i, "ts": float(i), "sharpness": 1.0} for i in range(30)]
    picked = chooseCrops(c3, c2)
    assert len(picked) == 12
    assert sum(1 for r in picked if r["id"] < 100) == 8
    assert {0, 29} <= {r["id"] for r in picked}
    assert len(chooseCrops(c3, c2[:1])) == 12
    assert len(chooseCrops(c3[:2], c2)) == 12


def test_live_linker_answers_in_its_thread() -> None:
    linker = LiveLinker(_GC(), _FakeModel(), "fake")
    records = _ride()
    c3_states = [r for r in records if r["type"] == "state" and r["ch"] == 3 and r["pieces"]]
    last = c3_states[-1]
    box = last["pieces"][0][3:7]
    linker.rows_of = lambda ch, t0, t1: (
        [{"id": 11, "channel": 3, "ts": last["ts"], "track_id": 3, "bbox": box, "zone_code": 2,
          "com_forward_to_exit_deg": 5.0, "sharpness": 4.0}]
        if ch == 3 else []
    )
    linker.start()
    try:
        for r in records:
            linker.offer(r)
        picks = linker.link("piece-1", records[-1]["ts"], 0.9, timeout_s=10.0)
        assert picks is not None
        assert [p["id"] for p in picks] == [11]
        assert picks[0]["model_same"] is True
        assert picks[0]["model_score"] == pytest.approx(0.95)
        assert linker.link("unknown-piece", 0.0, 0.9, timeout_s=10.0) is None
        stats = linker.stats()
        assert stats["pieces"] == 2 and stats["linked"] == 1 and stats["errors"] == 0
    finally:
        linker.stop()


def test_format_mismatch_is_named() -> None:
    assert formatMismatch({"format": dict(FORMAT)}) is None
    assert "f_dim" in str(formatMismatch({"format": {**FORMAT, "f_dim": 80}}))
    assert formatMismatch({}) is not None


def test_tap_gets_an_open_segments_meta_and_frame_sizes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    import control_data_store
    import local_state

    importlib.reload(local_state)
    store = importlib.reload(control_data_store)
    try:
        assert store.beginSegment({"t": 1.0, "machine_setup": "x"})
        store.record({"type": "frame_info", "ch": 3, "w": 1280, "h": 720})
        store.record({"type": "state", "ch": 3, "ts": 1.5, "pieces": []})
        got: list[dict[str, Any]] = []
        store.setTap(got.append)
        store.record({"type": "state", "ch": 3, "ts": 2.0, "pieces": []})
        assert [r["type"] for r in got] == ["meta", "frame_info", "state"]
        assert got[0]["machine_setup"] == "x" and got[2]["ts"] == 2.0
        store.setTap(None)
        store.record({"type": "state", "ch": 3, "ts": 3.0, "pieces": []})
        assert len(got) == 3
    finally:
        store.setTap(None)
        store.endSegment()
        monkeypatch.delenv("LOCAL_STATE_DB_PATH")
        importlib.reload(local_state)
        importlib.reload(control_data_store)


def _linkModelDir(root: Path, name: str = "link-test") -> Path:
    model_dir = root / name
    (model_dir / "exports").mkdir(parents=True)
    (model_dir / "exports" / "linker.onnx").write_bytes(b"onnx")
    (model_dir / "run.json").write_text(
        json.dumps({"name": name, "purpose": "piece_link", "kind": "journey", "member": "linker.onnx", "format": FORMAT})
    )
    return model_dir


def test_a_link_model_put_there_by_hand_is_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server import hive_models

    monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
    _linkModelDir(tmp_path)
    entries = hive_models.list_installed_models()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["purpose"] == hive_models.PURPOSE_PIECE_LINK
    assert entry["source"] == "local" and entry["inert"] is True and entry["compatible"] is False


def test_the_matcher_hands_a_journey_model_to_the_live_linker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import link_matcher
    import toml_config
    from server import hive_models

    monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
    _linkModelDir(tmp_path)
    monkeypatch.setattr(
        toml_config,
        "getLinkMatchingConfig",
        lambda: {"enabled": True, "algorithm": "", "min_confidence": 0.9, "use_for_classification": False},
    )
    asked: list[tuple[str, float, float]] = []

    def linkPiece(piece_uuid: str, arrival_ts: float, min_p: float) -> list[dict[str, Any]]:
        asked.append((piece_uuid, arrival_ts, min_p))
        return []

    monkeypatch.setattr(live, "linkPiece", linkPiece)
    assert link_matcher.matchForPieceLive(_GC(), "piece-1", None, 12.5) == []
    assert asked == [("piece-1", 12.5, 0.9)]
    monkeypatch.setattr(
        toml_config,
        "getLinkMatchingConfig",
        lambda: {"enabled": False, "algorithm": "", "min_confidence": 0.9, "use_for_classification": False},
    )
    assert link_matcher.matchForPieceLive(_GC(), "piece-1", None, 12.5) is None
