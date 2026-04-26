#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import platform
import re
import shutil
import subprocess
import threading
import time
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

try:
    import websockets
except Exception:  # pragma: no cover - optional runtime dependency guard
    websockets = None  # type: ignore[assignment]


BASE = "http://localhost:8000"
REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_ROOT = REPO_ROOT / "logs" / "runs"
DEFAULT_FEEDS = ("c2_feed", "c3_feed", "c4_feed")
DEFAULT_WS_TAGS = {
    "frame",
    "known_object",
    "runtime_stats",
    "system_status",
    "sorter_state",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Observe a sorter run by periodically recording runtime state, "
            "tracked pieces, full rt tracks, websocket events, and screenshots."
        )
    )
    parser.add_argument("--backend-base", default=BASE)
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    parser.add_argument("--duration-s", type=float, default=120.0)
    parser.add_argument("--sample-period-s", type=float, default=2.0)
    parser.add_argument("--label", default="observed sorter run")
    parser.add_argument("--note", default="")
    parser.add_argument("--resume", action="store_true", help="POST /resume before observing.")
    parser.add_argument(
        "--leave-running",
        action="store_true",
        help="Do not POST /pause after a --resume-controlled run.",
    )
    parser.add_argument(
        "--post-run-drain-s",
        type=float,
        default=8.0,
        help=(
            "Before pausing a --resume-controlled run, keep RT running up to "
            "this many seconds so an in-flight distributor send can complete."
        ),
    )
    parser.add_argument(
        "--screenshot-mode",
        choices=("auto", "none", "macos-screen"),
        default="auto",
        help="auto uses macOS screencapture when available.",
    )
    parser.add_argument("--no-ws", action="store_true", help="Disable websocket event capture.")
    parser.add_argument(
        "--no-frame-capture",
        action="store_true",
        help="Do not save throttled annotated camera frames from websocket frame events.",
    )
    parser.add_argument(
        "--frame-period-s",
        type=float,
        default=2.0,
        help="Minimum seconds between saved frame images per camera.",
    )
    parser.add_argument(
        "--feed",
        action="append",
        dest="feeds",
        help="Perception feed to snapshot via /api/rt/tracks/{feed_id}. Repeatable.",
    )
    return parser.parse_args()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower())
    return cleaned.strip("-") or "run"


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _jsonl_append(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        f.write("\n")


def _safe_get(session: requests.Session, base_url: str, path: str, *, timeout: float = 8.0) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return data
        return {"_error": "non_object_json", "_value": data}
    except Exception as exc:
        return {"_error": str(exc), "_url": url}


def _post(session: requests.Session, base_url: str, path: str, *, timeout: float = 15.0) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    response = session.post(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"value": data}


def _ws_url_for_backend(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/ws", "", "", ""))


def _screenshot_mode(mode: str) -> str:
    if mode == "auto":
        if platform.system() == "Darwin" and shutil.which("screencapture"):
            return "macos-screen"
        return "none"
    return mode


def _capture_screenshot(mode: str, dest: Path) -> str | None:
    if mode == "none":
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode == "macos-screen":
        subprocess.run(["screencapture", "-x", str(dest)], check=True, timeout=15)
        return str(dest)
    return None


class WsRecorder:
    def __init__(
        self,
        *,
        ws_url: str,
        out_file: Path,
        frames_dir: Path,
        tags: set[str],
        started_at: float,
        frame_period_s: float,
        capture_frames: bool,
    ) -> None:
        self.ws_url = ws_url
        self.out_file = out_file
        self.frames_dir = frames_dir
        self.tags = set(tags)
        self.started_at = float(started_at)
        self.frame_period_s = max(0.2, float(frame_period_s))
        self.capture_frames = bool(capture_frames)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._known: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._frame_counts: Counter[str] = Counter()
        self._last_frame_capture: dict[str, float] = {}
        self._saved_frame_count = 0
        self._connected = False

    def start(self) -> None:
        if websockets is None:
            self._record_internal("ws_unavailable", {"reason": "websockets package unavailable"})
            return
        self._thread = threading.Thread(target=self._thread_main, name="run-observer-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = list(self._known.values())[-10:]
            return {
                "connected": self._connected,
                "event_counts": dict(self._counts),
                "known_object_count": len(self._known),
                "recent_known_objects": recent,
                "saved_frame_count": self._saved_frame_count,
                "frame_counts": dict(self._frame_counts),
            }

    def _thread_main(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.ws_url, ping_interval=None) as ws:  # type: ignore[union-attr]
                    with self._lock:
                        self._connected = True
                    self._record_internal("ws_connected", {"url": self.ws_url})
                    while not self._stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        self._record_raw(raw)
            except Exception as exc:
                with self._lock:
                    self._connected = False
                self._record_internal("ws_error", {"error": str(exc)})
                await asyncio.sleep(1.0)

    def _record_internal(self, tag: str, payload: dict[str, Any]) -> None:
        record = {
            "captured_at": time.time(),
            "elapsed_s": time.time() - self.started_at,
            "tag": f"_{tag}",
            "data": payload,
        }
        _jsonl_append(self.out_file, record)

    def _record_raw(self, raw: str | bytes) -> None:
        try:
            event = json.loads(raw)
        except Exception:
            self._record_internal("ws_decode_error", {"raw": str(raw)[:500]})
            return
        if not isinstance(event, dict):
            return
        tag = event.get("tag")
        if isinstance(tag, str) and self.tags and tag not in self.tags:
            return
        if tag == "frame":
            self._record_frame_event(event)
            return
        record = {
            "captured_at": time.time(),
            "elapsed_s": time.time() - self.started_at,
            "tag": tag,
            "event": event,
        }
        with self._lock:
            if isinstance(tag, str):
                self._counts[tag] += 1
            if tag == "known_object":
                data = event.get("data")
                if isinstance(data, dict):
                    key = _piece_key(data)
                    if key is not None:
                        self._known.pop(key, None)
                        self._known[key] = _compact_piece(data)
                        while len(self._known) > 100:
                            self._known.popitem(last=False)
        _jsonl_append(self.out_file, record)

    def _record_frame_event(self, event: dict[str, Any]) -> None:
        data = event.get("data")
        if not isinstance(data, dict):
            return
        camera = data.get("camera")
        camera = camera if isinstance(camera, str) and camera.strip() else "unknown"
        with self._lock:
            self._counts["frame"] += 1
            self._frame_counts[camera] += 1
            last = self._last_frame_capture.get(camera, 0.0)
            now = time.time()
            if not self.capture_frames or now - last < self.frame_period_s:
                return
            self._last_frame_capture[camera] = now

        image_path: str | None = None
        image_kind: str | None = None
        for candidate in ("annotated", "raw"):
            encoded = data.get(candidate)
            if isinstance(encoded, str) and encoded.strip():
                try:
                    raw = base64.b64decode(encoded, validate=False)
                except Exception:
                    continue
                self.frames_dir.mkdir(parents=True, exist_ok=True)
                safe_camera = _slug(camera)
                index = self._frame_counts[camera]
                file_path = self.frames_dir / f"{safe_camera}_{index:05d}_{int(now * 1000)}.jpg"
                file_path.write_bytes(raw)
                image_path = str(file_path.relative_to(self.out_file.parent))
                image_kind = candidate
                with self._lock:
                    self._saved_frame_count += 1
                break

        compact_data = {
            key: value
            for key, value in data.items()
            if key not in {"raw", "annotated"}
        }
        compact_data["image_path"] = image_path
        compact_data["image_kind"] = image_kind
        record = {
            "captured_at": time.time(),
            "elapsed_s": time.time() - self.started_at,
            "tag": "frame",
            "event": {"tag": "frame", "data": compact_data},
        }
        _jsonl_append(self.out_file, record)


def _piece_payload(row_or_piece: dict[str, Any]) -> dict[str, Any]:
    piece = row_or_piece.get("piece")
    if not isinstance(piece, dict):
        return row_or_piece
    merged = dict(piece)
    for key in ("active", "live", "history_finished_at"):
        if key in row_or_piece and key not in merged:
            merged[key] = row_or_piece.get(key)
    return merged


def _piece_key(piece: dict[str, Any]) -> str | None:
    gid = piece.get("tracked_global_id")
    if isinstance(gid, int):
        return f"gid:{gid}"
    uuid = piece.get("uuid") or piece.get("piece_uuid")
    if isinstance(uuid, str) and uuid.strip():
        return f"uuid:{uuid}"
    return None


def _lifecycle_phase(piece: dict[str, Any]) -> str:
    if piece.get("stage") == "distributed" or isinstance(piece.get("distributed_at"), (int, float)):
        return "distributed"
    status = piece.get("classification_status")
    if status in {"classified", "unknown", "not_found", "multi_drop_fail"} or piece.get("classified_at"):
        return "classified"
    if (
        piece.get("carousel_snapping_started_at")
        or piece.get("carousel_snapping_completed_at")
        or piece.get("part_id")
        or piece.get("preview_jpeg_path")
        or piece.get("thumbnail")
    ):
        return "capturing"
    if piece.get("tracked_global_id") is not None or piece.get("first_carousel_seen_ts"):
        return "tracking"
    return "capturing"


def _has_c4_evidence(piece: dict[str, Any]) -> bool:
    return bool(
        piece.get("carousel_detected_confirmed_at")
        or piece.get("first_carousel_seen_ts")
        or piece.get("carousel_snapping_started_at")
        or piece.get("carousel_snapping_completed_at")
        or piece.get("classified_at")
        or isinstance(piece.get("classification_channel_zone_center_deg"), (int, float))
        or piece.get("classification_channel_zone_state")
    )


def _recent_visible_candidate(piece: dict[str, Any]) -> bool:
    if piece.get("classification_channel_zone_state") == "lost" and piece.get("stage") != "distributed":
        return False
    if (
        _lifecycle_phase(piece) == "classified"
        and not piece.get("distributed_at")
        and piece.get("classification_channel_zone_state") != "active"
    ):
        return False
    if not _has_c4_evidence(piece) and piece.get("stage") != "distributed" and not piece.get("distributed_at"):
        return False
    if piece.get("stage") != "created":
        return True
    return bool(piece.get("tracked_global_id") is not None or piece.get("part_id") or piece.get("preview_jpeg_path"))


def _wrap_distance_deg(angle: float, target: float) -> float:
    return abs(((angle - target + 540.0) % 360.0) - 180.0)


def _exit_distance(piece: dict[str, Any], drop_angle: float | None) -> float | None:
    angle = piece.get("classification_channel_zone_center_deg")
    if not isinstance(angle, (int, float)):
        return None
    target = piece.get("classification_channel_exit_deg")
    if not isinstance(target, (int, float)):
        target = drop_angle
    if not isinstance(target, (int, float)):
        return None
    return _wrap_distance_deg(float(angle), float(target))


def _compact_piece(piece: dict[str, Any], *, drop_angle: float | None = None) -> dict[str, Any]:
    return {
        "uuid": piece.get("uuid") or piece.get("piece_uuid"),
        "tracked_global_id": piece.get("tracked_global_id"),
        "stage": piece.get("stage"),
        "classification_status": piece.get("classification_status"),
        "zone_state": piece.get("classification_channel_zone_state"),
        "zone_center_deg": piece.get("classification_channel_zone_center_deg"),
        "exit_distance_deg": _exit_distance(piece, drop_angle),
        "part_id": piece.get("part_id"),
        "part_name": piece.get("part_name"),
        "color_id": piece.get("color_id"),
        "color_name": piece.get("color_name"),
        "confidence": piece.get("confidence"),
        "preview_jpeg_path": piece.get("preview_jpeg_path"),
        "updated_at": piece.get("updated_at"),
    }


def _runner_by_feed(rt_status: dict[str, Any], feed_id: str) -> dict[str, Any]:
    runners = rt_status.get("runners")
    if not isinstance(runners, list):
        return {}
    for runner in runners:
        if isinstance(runner, dict) and runner.get("feed_id") == feed_id:
            return runner
    return {}


def _counts_delta(start: dict[str, Any], end: dict[str, Any]) -> dict[str, int]:
    start_counts = (start.get("payload") if isinstance(start.get("payload"), dict) else start).get("counts", {})
    end_counts = (end.get("payload") if isinstance(end.get("payload"), dict) else end).get("counts", {})
    if not isinstance(start_counts, dict) or not isinstance(end_counts, dict):
        return {}
    keys = sorted(set(start_counts.keys()) | set(end_counts.keys()))
    out: dict[str, int] = {}
    for key in keys:
        a = start_counts.get(key)
        b = end_counts.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta = int(b - a)
            if delta:
                out[key] = delta
    return out


def _flow_gate_delta(start: dict[str, Any], end: dict[str, Any]) -> dict[str, float]:
    def _totals(payload: dict[str, Any]) -> dict[str, Any]:
        flow = payload.get("flow_gate_accounting")
        if not isinstance(flow, dict):
            return {}
        totals = flow.get("totals_s")
        return totals if isinstance(totals, dict) else {}

    start_totals = _totals(start)
    end_totals = _totals(end)
    keys = sorted(set(start_totals.keys()) | set(end_totals.keys()))
    out: dict[str, float] = {}
    for key in keys:
        a = start_totals.get(key, 0.0)
        b = end_totals.get(key, 0.0)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        delta = float(b) - float(a)
        if delta > 0.05:
            out[str(key)] = delta
    return dict(sorted(out.items(), key=lambda item: item[1], reverse=True))


def _distributor_idle(rt_status: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    runtime_debug = rt_status.get("runtime_debug")
    distributor = runtime_debug.get("distributor") if isinstance(runtime_debug, dict) else None
    distributor = distributor if isinstance(distributor, dict) else {}
    pending = distributor.get("pending")
    return distributor.get("fsm_state") == "idle" and pending is None, distributor


def _runtime_int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _runner_counts(rt_status: dict[str, Any], feed_id: str) -> dict[str, int]:
    runner = _runner_by_feed(rt_status, feed_id)
    return {
        "detection_count": _runtime_int(runner.get("detection_count")),
        "raw_track_count": _runtime_int(runner.get("raw_track_count")),
        "confirmed_track_count": _runtime_int(runner.get("confirmed_track_count")),
        "confirmed_real_track_count": _runtime_int(
            runner.get("confirmed_real_track_count")
        ),
    }


def _line_idle(rt_status: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    distributor_idle, distributor = _distributor_idle(rt_status)
    runtime_debug = rt_status.get("runtime_debug")
    runtime_debug = runtime_debug if isinstance(runtime_debug, dict) else {}

    c2 = runtime_debug.get("c2") if isinstance(runtime_debug.get("c2"), dict) else {}
    c3 = runtime_debug.get("c3") if isinstance(runtime_debug.get("c3"), dict) else {}
    c4 = runtime_debug.get("c4") if isinstance(runtime_debug.get("c4"), dict) else {}

    state = {
        "distributor_idle": distributor_idle,
        "distributor": {
            "fsm_state": distributor.get("fsm_state"),
            "pending": distributor.get("pending"),
            "chute": distributor.get("chute"),
        },
        "c2": {
            "piece_count": _runtime_int(c2.get("piece_count")),
            "visible_track_count": _runtime_int(c2.get("visible_track_count")),
            "pending_track_count": _runtime_int(c2.get("pending_track_count")),
            "runner": _runner_counts(rt_status, "c2_feed"),
        },
        "c3": {
            "piece_count": _runtime_int(c3.get("piece_count")),
            "visible_track_count": _runtime_int(c3.get("visible_track_count")),
            "active_visible_track_count": _runtime_int(
                c3.get("active_visible_track_count")
            ),
            "pending_track_count": _runtime_int(c3.get("pending_track_count")),
            "ignored_transport_bad_actor_count": _runtime_int(
                (
                    c3.get("transport_bad_actor_suppression")
                    if isinstance(c3.get("transport_bad_actor_suppression"), dict)
                    else {}
                ).get("ignored_count")
            ),
            "runner": _runner_counts(rt_status, "c3_feed"),
        },
        "c4": {
            "raw_detection_count": _runtime_int(c4.get("raw_detection_count")),
            "dossier_count": _runtime_int(c4.get("dossier_count")),
            "zone_count": _runtime_int(c4.get("zone_count")),
            "runner": _runner_counts(rt_status, "c4_feed"),
        },
    }
    busy_total = 0
    busy_total += state["c2"]["piece_count"] + state["c2"]["visible_track_count"]
    busy_total += state["c2"]["pending_track_count"]
    busy_total += state["c3"]["piece_count"] + state["c3"]["visible_track_count"]
    busy_total += state["c3"]["pending_track_count"]
    busy_total += state["c4"]["raw_detection_count"] + state["c4"]["dossier_count"]
    busy_total += state["c4"]["zone_count"]
    for feed in ("c2", "c3", "c4"):
        runner = state[feed]["runner"]
        busy_total += runner["detection_count"]
        busy_total += runner["raw_track_count"]
        busy_total += runner["confirmed_track_count"]
    state["busy_total"] = int(busy_total)
    return distributor_idle and busy_total == 0, state


def _derive_sample(
    *,
    rt_status: dict[str, Any],
    tracked_pieces: dict[str, Any],
    tracks_by_feed: dict[str, dict[str, Any]],
    runtime_stats: dict[str, Any],
    now_mono: float | None = None,
    runtime_anomaly_window_s: float = 3.0,
) -> dict[str, Any]:
    rows = tracked_pieces.get("items")
    rows = rows if isinstance(rows, list) else []
    drop_angle = tracked_pieces.get("drop_angle_deg")
    drop_angle = float(drop_angle) if isinstance(drop_angle, (int, float)) else None

    pieces = [_piece_payload(row) for row in rows if isinstance(row, dict)]
    active = [
        piece
        for piece in pieces
        if piece.get("active") is not False
        and piece.get("stage") != "distributed"
        and not isinstance(piece.get("distributed_at"), (int, float))
    ]
    recent_candidates = [
        piece
        for piece in active
        if _recent_visible_candidate(piece)
    ]
    active_zone = [
        piece for piece in active if piece.get("classification_channel_zone_state") == "active"
    ]
    active_zone_by_gid: dict[int, list[dict[str, Any]]] = {}
    for piece in active_zone:
        gid = piece.get("tracked_global_id")
        if isinstance(gid, int):
            active_zone_by_gid.setdefault(gid, []).append(piece)
    active_zone.sort(
        key=lambda piece: (
            _exit_distance(piece, drop_angle) is None,
            _exit_distance(piece, drop_angle) or 9999.0,
            -(float(piece.get("updated_at")) if isinstance(piece.get("updated_at"), (int, float)) else 0.0),
        )
    )
    recent_without_active_zone = [
        piece
        for piece in recent_candidates
        if piece.get("classification_channel_zone_state") != "active"
    ]
    stale_classified = [
        piece
        for piece in active
        if _lifecycle_phase(piece) == "classified"
        and piece.get("classification_channel_zone_state") != "active"
    ]

    c4_runner = _runner_by_feed(rt_status, "c4_feed")
    c4_tracks = tracks_by_feed.get("c4_feed", {})
    c4_track_items = c4_tracks.get("tracks") if isinstance(c4_tracks.get("tracks"), list) else []
    c4_confirmed_real_tracks = [
        track for track in c4_track_items
        if isinstance(track, dict) and track.get("confirmed_real") is True
    ]
    c4_confirmed_count = c4_runner.get("confirmed_real_track_count")
    if not isinstance(c4_confirmed_count, int):
        c4_confirmed_count = len(c4_confirmed_real_tracks)

    runtime_debug = rt_status.get("runtime_debug")
    c4_debug = runtime_debug.get("c4") if isinstance(runtime_debug, dict) else None
    c4_debug = c4_debug if isinstance(c4_debug, dict) else {}
    c3_debug = runtime_debug.get("c3") if isinstance(runtime_debug, dict) else None
    c3_debug = c3_debug if isinstance(c3_debug, dict) else {}
    c3_transport_bad_actors = _bad_actor_suppression_snapshot(
        c3_debug.get("transport_bad_actor_suppression")
    )
    c3_upstream_bad_actors = _bad_actor_suppression_snapshot(
        c3_debug.get("upstream_bad_actor_suppression")
    )

    anomalies: list[dict[str, Any]] = []
    if c3_transport_bad_actors.get("ignored_count", 0) > 0:
        anomalies.append({
            "kind": "c3_transport_bad_actor_visible",
            **c3_transport_bad_actors,
        })
    if c3_upstream_bad_actors.get("ignored_count", 0) > 0:
        anomalies.append({
            "kind": "c3_upstream_bad_actor_visible",
            **c3_upstream_bad_actors,
        })
    duplicate_active_gids = {
        str(gid): [_compact_piece(piece, drop_angle=drop_angle) for piece in group]
        for gid, group in active_zone_by_gid.items()
        if len(group) > 1
    }
    if duplicate_active_gids:
        anomalies.append({"kind": "duplicate_active_global_ids", "items": duplicate_active_gids})
    if stale_classified:
        anomalies.append({
            "kind": "stale_classified_active_pieces",
            "count": len(stale_classified),
            "items": [_compact_piece(piece, drop_angle=drop_angle) for piece in stale_classified[:10]],
        })
    if recent_without_active_zone:
        anomalies.append({
            "kind": "recent_candidates_without_active_zone",
            "count": len(recent_without_active_zone),
            "items": [_compact_piece(piece, drop_angle=drop_angle) for piece in recent_without_active_zone[:10]],
        })
    if c4_confirmed_count > len(active_zone):
        anomalies.append({
            "kind": "c4_confirmed_tracks_without_active_dossiers",
            "confirmed_real_track_count": c4_confirmed_count,
            "active_c4_dossier_count": len(active_zone),
        })
    c4_diag = c4_debug.get("handoff_burst_diagnostics")
    if isinstance(c4_diag, dict):
        recent_moves = c4_diag.get("recent_moves")
        angles = c4_debug.get("angles")
        angles = angles if isinstance(angles, dict) else {}
        hold_deg = angles.get("exit_approach_angle_deg")
        if not isinstance(hold_deg, (int, float)):
            hold_deg = angles.get("tolerance_deg")
        hold_deg = float(hold_deg) if isinstance(hold_deg, (int, float)) else 30.0
        unsafe_exit_moves = []
        if isinstance(recent_moves, list):
            for move in recent_moves:
                if not isinstance(move, dict):
                    continue
                if move.get("source") != "c4_transport":
                    continue
                if move.get("front_handoff_requested") is not True:
                    continue
                if move.get("front_distributor_ready") is not False:
                    continue
                distance = move.get("front_exit_distance_deg")
                if not isinstance(distance, (int, float)) or float(distance) > hold_deg:
                    continue
                if not _runtime_anomaly_is_fresh(
                    move,
                    now_mono=now_mono,
                    window_s=runtime_anomaly_window_s,
                ):
                    continue
                unsafe_exit_moves.append(move)
        if unsafe_exit_moves:
            anomalies.append({
                "kind": "c4_transport_near_exit_without_distributor_ready",
                "count": len(unsafe_exit_moves),
                "last": unsafe_exit_moves[-1],
            })
    if isinstance(runtime_debug, dict):
        for runtime_id in ("c2", "c3", "c4"):
            runtime_diag = runtime_debug.get(runtime_id)
            if not isinstance(runtime_diag, dict):
                continue
            handoff_diag = runtime_diag.get("handoff_burst_diagnostics")
            if not isinstance(handoff_diag, dict):
                continue
            runtime_anomalies = handoff_diag.get("anomalies")
            if not isinstance(runtime_anomalies, list) or not runtime_anomalies:
                continue
            fresh_anomalies = [
                anomaly
                for anomaly in runtime_anomalies
                if _runtime_anomaly_is_fresh(
                    anomaly,
                    now_mono=now_mono,
                    window_s=runtime_anomaly_window_s,
                )
            ]
            if not fresh_anomalies:
                continue
            last_anomaly = fresh_anomalies[-1]
            anomalies.append({
                "kind": f"{runtime_id}_dropzone_arrival_burst",
                "count": len(fresh_anomalies),
                "last": last_anomaly if isinstance(last_anomaly, dict) else {},
            })

    stats_payload = runtime_stats.get("payload") if isinstance(runtime_stats.get("payload"), dict) else runtime_stats
    counts = stats_payload.get("counts") if isinstance(stats_payload, dict) else None

    return {
        "c4": {
            "detector_slug": c4_runner.get("detector_slug"),
            "tracker_slug": c4_runner.get("tracker_slug"),
            "detection_count": c4_runner.get("detection_count"),
            "raw_track_count": c4_runner.get("raw_track_count"),
            "confirmed_real_track_count": c4_confirmed_count,
            "observed_rpm": c4_runner.get("observed_rpm"),
            "runtime_dossier_count": c4_debug.get("dossier_count"),
            "runtime_zone_count": c4_debug.get("zone_count"),
            "full_track_count": len(c4_track_items),
            "full_confirmed_real_track_count": len(c4_confirmed_real_tracks),
        },
        "c3": {
            "visible_track_count": c3_debug.get("visible_track_count"),
            "active_visible_track_count": c3_debug.get("active_visible_track_count"),
            "transport_bad_actor_suppression": c3_transport_bad_actors,
            "upstream_bad_actor_suppression": c3_upstream_bad_actors,
        },
        "tracked_pieces": {
            "total": len(pieces),
            "active": len(active),
            "active_c4_zone": len(active_zone),
            "recent_visible_candidates": len(recent_candidates),
            "recent_candidates_without_active_zone": len(recent_without_active_zone),
            "stale_classified": len(stale_classified),
            "top_queue_by_exit": [
                _compact_piece(piece, drop_angle=drop_angle) for piece in active_zone[:10]
            ],
        },
        "runtime_counts": counts if isinstance(counts, dict) else {},
        "anomalies": anomalies,
    }


def _runtime_anomaly_is_fresh(
    anomaly: Any,
    *,
    now_mono: float | None,
    window_s: float,
) -> bool:
    if now_mono is None or not isinstance(anomaly, dict):
        return True
    ts_mono = anomaly.get("ts_mono")
    if not isinstance(ts_mono, (int, float)):
        return True
    return (float(now_mono) - float(ts_mono)) <= max(0.5, float(window_s))


def _bad_actor_suppression_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"ignored_count": 0, "ignored": []}
    ignored = value.get("ignored")
    ignored_items = ignored if isinstance(ignored, list) else []
    ignored_count = value.get("ignored_count")
    if not isinstance(ignored_count, int):
        ignored_count = len(ignored_items)
    return {
        "name": value.get("name"),
        "ignored_count": max(0, int(ignored_count)),
        "ignored": [item for item in ignored_items[:10] if isinstance(item, dict)],
        "observing": bool(value.get("observing", False)),
        "observe_for_s": value.get("observe_for_s"),
    }


def _write_summary(
    *,
    run_dir: Path,
    run_meta: dict[str, Any],
    samples: list[dict[str, Any]],
    start_runtime_stats: dict[str, Any],
    end_runtime_stats: dict[str, Any],
    start_rt_status: dict[str, Any],
    end_rt_status: dict[str, Any],
    ws_snapshot: dict[str, Any],
) -> None:
    anomaly_counts: Counter[str] = Counter()
    for sample in samples:
        derived = sample.get("derived")
        if not isinstance(derived, dict):
            continue
        for anomaly in derived.get("anomalies", []) or []:
            if isinstance(anomaly, dict) and isinstance(anomaly.get("kind"), str):
                anomaly_counts[anomaly["kind"]] += 1

    summary = {
        **run_meta,
        "sample_count": len(samples),
        "counts_delta": _counts_delta(start_runtime_stats, end_runtime_stats),
        "flow_gate_delta_s": _flow_gate_delta(start_rt_status, end_rt_status),
        "ws": ws_snapshot,
        "anomaly_counts": dict(anomaly_counts),
        "last_sample_derived": samples[-1].get("derived") if samples else {},
    }
    _json_dump(run_dir / "summary.json", summary)

    lines = [
        f"# Sorter Run Observer - {run_meta['label']}",
        "",
        f"- Started: `{datetime.fromtimestamp(run_meta['started_at']).isoformat(timespec='seconds')}`",
        f"- Ended: `{datetime.fromtimestamp(run_meta['ended_at']).isoformat(timespec='seconds')}`",
        f"- Duration: `{run_meta['wall_duration_s']:.1f}s`",
        f"- Samples: `{len(samples)}` every `{run_meta['sample_period_s']:.1f}s`",
        f"- Screenshots: `{run_meta['screenshot_count']}`",
        f"- Saved camera frames: `{ws_snapshot.get('saved_frame_count', 0)}`",
        f"- Resume controlled: `{run_meta['resume_controlled']}`",
        f"- Post-run drain: `{run_meta.get('post_run_drain_s', 0.0):.1f}s`",
        "",
        "## Count Delta",
        "",
    ]
    drain_result = run_meta.get("post_run_drain_result")
    if isinstance(drain_result, dict):
        line_state = drain_result.get("line_state")
        busy_total = (
            line_state.get("busy_total")
            if isinstance(line_state, dict)
            else None
        )
        lines.append(
            "- Drain result: "
            f"`drained={bool(drain_result.get('drained'))}` "
            f"`line_busy={busy_total}` "
            f"`actual={float(drain_result.get('actual_s') or 0.0):.1f}s` "
            f"`last={drain_result.get('last_distributor_state', {}).get('fsm_state')}`"
        )
        lines.append("")
    counts_delta = summary["counts_delta"]
    if counts_delta:
        for key, value in counts_delta.items():
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- No numeric runtime count deltas recorded.")
    lines.extend(["", "## Flow Gate Pareto", ""])
    flow_gate_delta = summary.get("flow_gate_delta_s")
    if isinstance(flow_gate_delta, dict) and flow_gate_delta:
        total_gate_s = sum(
            float(v)
            for v in flow_gate_delta.values()
            if isinstance(v, (int, float))
        )
        for key, seconds in list(flow_gate_delta.items())[:15]:
            pct = (float(seconds) / total_gate_s * 100.0) if total_gate_s > 0 else 0.0
            lines.append(f"- `{key}`: `{float(seconds):.1f}s` ({pct:.1f}%)")
    else:
        lines.append("- No flow-gate accounting delta recorded.")
    lines.extend(["", "## Anomalies", ""])
    if anomaly_counts:
        for key, value in anomaly_counts.items():
            lines.append(f"- `{key}`: `{value}` samples")
    else:
        lines.append("- No observer anomalies detected.")
    lines.extend(["", "## Last C4 Queue", ""])
    last = summary.get("last_sample_derived")
    queue = []
    if isinstance(last, dict):
        tracked = last.get("tracked_pieces")
        if isinstance(tracked, dict):
            queue = tracked.get("top_queue_by_exit") or []
    if queue:
        for item in queue:
            if not isinstance(item, dict):
                continue
            label = item.get("part_name") or item.get("uuid") or item.get("tracked_global_id")
            lines.append(
                "- "
                f"`gid={item.get('tracked_global_id')}` "
                f"`zone={item.get('zone_state')}` "
                f"`exit_d={item.get('exit_distance_deg')}` "
                f"{label}"
            )
    else:
        lines.append("- No queue candidates in the last sample.")
    lines.append("")
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    backend_base = str(args.backend_base).rstrip("/")
    out_root = Path(args.out_root).expanduser().resolve()
    started_at = time.time()
    stamp = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = out_root / f"{stamp}_{_slug(args.label)}"
    screenshots_dir = run_dir / "screenshots"
    frames_dir = run_dir / "frames"
    samples_file = run_dir / "samples.jsonl"
    events_file = run_dir / "events.jsonl"
    run_dir.mkdir(parents=True, exist_ok=True)

    feeds = tuple(args.feeds or DEFAULT_FEEDS)
    screenshot_mode = _screenshot_mode(str(args.screenshot_mode))
    session = requests.Session()

    recorder = None
    if not args.no_ws:
        recorder = WsRecorder(
            ws_url=_ws_url_for_backend(backend_base),
            out_file=events_file,
            frames_dir=frames_dir,
            tags=set(DEFAULT_WS_TAGS),
            started_at=started_at,
            frame_period_s=float(args.frame_period_s),
            capture_frames=not bool(args.no_frame_capture),
        )
        recorder.start()

    start_runtime_stats = _safe_get(session, backend_base, "/runtime-stats")
    start_rt_status = _safe_get(session, backend_base, "/api/rt/status")
    _json_dump(
        run_dir / "start.json",
        {
            "captured_at": time.time(),
            "backend_base": backend_base,
            "rt_status": start_rt_status,
            "runtime_stats": start_runtime_stats,
            "system_status": _safe_get(session, backend_base, "/api/system/status"),
            "tracked_pieces": _safe_get(
                session,
                backend_base,
                "/api/tracked/pieces?limit=500&include_stubs=false",
            ),
        },
    )

    resume_controlled = bool(args.resume)
    if resume_controlled:
        _post(session, backend_base, "/resume")

    samples: list[dict[str, Any]] = []
    screenshot_count = 0
    post_run_drain_result: dict[str, Any] | None = None
    deadline = time.monotonic() + max(0.0, float(args.duration_s))
    sample_period_s = max(0.2, float(args.sample_period_s))

    try:
        while True:
            now = time.time()
            elapsed = now - started_at
            rt_status = _safe_get(session, backend_base, "/api/rt/status")
            runtime_stats = _safe_get(session, backend_base, "/runtime-stats")
            tracked_pieces = _safe_get(
                session,
                backend_base,
                "/api/tracked/pieces?limit=500&include_stubs=false",
            )
            tracks_by_feed = {
                feed_id: _safe_get(session, backend_base, f"/api/rt/tracks/{feed_id}")
                for feed_id in feeds
            }

            screenshot_path = None
            if screenshot_mode != "none":
                shot_name = f"{len(samples):04d}_{int(now * 1000)}.png"
                try:
                    captured = _capture_screenshot(screenshot_mode, screenshots_dir / shot_name)
                    if captured is not None:
                        screenshot_count += 1
                        screenshot_path = str(Path(captured).relative_to(run_dir))
                except Exception as exc:
                    screenshot_path = f"ERROR: {exc}"

            derived = _derive_sample(
                rt_status=rt_status,
                tracked_pieces=tracked_pieces,
                tracks_by_feed=tracks_by_feed,
                runtime_stats=runtime_stats,
                now_mono=time.monotonic(),
                runtime_anomaly_window_s=max(3.0, sample_period_s * 2.0 + 0.5),
            )
            sample = {
                "captured_at": now,
                "elapsed_s": elapsed,
                "screenshot": screenshot_path,
                "ws": recorder.snapshot() if recorder is not None else None,
                "rt_status": rt_status,
                "runtime_stats": runtime_stats,
                "tracked_pieces": tracked_pieces,
                "tracks_by_feed": tracks_by_feed,
                "derived": derived,
            }
            samples.append(sample)
            _jsonl_append(samples_file, sample)

            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                break
            time.sleep(min(sample_period_s, remaining))
    finally:
        if resume_controlled and not args.leave_running:
            drain_s = max(0.0, float(args.post_run_drain_s))
            drain_started = time.time()
            drain_last: dict[str, Any] = {}
            line_last: dict[str, Any] = {}
            drained = False
            if drain_s > 0.0:
                drain_deadline = time.monotonic() + drain_s
                while time.monotonic() < drain_deadline:
                    rt_status = _safe_get(session, backend_base, "/api/rt/status")
                    _dist_idle, drain_last = _distributor_idle(rt_status)
                    drained, line_last = _line_idle(rt_status)
                    if drained:
                        break
                    time.sleep(min(0.25, max(0.0, drain_deadline - time.monotonic())))
                if not drained and drain_last.get("pending") is not None:
                    grace_s = min(8.0, max(3.0, drain_s * 0.75))
                    grace_deadline = time.monotonic() + grace_s
                    while time.monotonic() < grace_deadline:
                        rt_status = _safe_get(session, backend_base, "/api/rt/status")
                        _dist_idle, drain_last = _distributor_idle(rt_status)
                        drained, line_last = _line_idle(rt_status)
                        if drained:
                            break
                        time.sleep(min(0.25, max(0.0, grace_deadline - time.monotonic())))
                post_run_drain_result = {
                    "requested_s": drain_s,
                    "actual_s": time.time() - drain_started,
                    "drained": drained,
                    "line_idle": drained,
                    "line_state": line_last,
                    "last_distributor_state": {
                        "fsm_state": drain_last.get("fsm_state"),
                        "pending": drain_last.get("pending"),
                        "chute": drain_last.get("chute"),
                    },
                }
                _jsonl_append(
                    events_file,
                    {
                        "captured_at": time.time(),
                        "elapsed_s": time.time() - started_at,
                        "tag": "_post_run_drain",
                        "data": post_run_drain_result,
                    },
                )
            try:
                _post(session, backend_base, "/pause")
            except Exception as exc:
                _jsonl_append(
                    events_file,
                    {
                        "captured_at": time.time(),
                        "elapsed_s": time.time() - started_at,
                        "tag": "_pause_error",
                        "data": {"error": str(exc)},
                    },
                )
        if recorder is not None:
            recorder.stop()

    ended_at = time.time()
    end_runtime_stats = _safe_get(session, backend_base, "/runtime-stats")
    end_rt_status = _safe_get(session, backend_base, "/api/rt/status")
    _json_dump(
        run_dir / "end.json",
        {
            "captured_at": ended_at,
            "rt_status": end_rt_status,
            "runtime_stats": end_runtime_stats,
            "system_status": _safe_get(session, backend_base, "/api/system/status"),
            "tracked_pieces": _safe_get(
                session,
                backend_base,
                "/api/tracked/pieces?limit=500&include_stubs=false",
            ),
        },
    )

    run_meta = {
        "label": str(args.label),
        "note": str(args.note),
        "backend_base": backend_base,
        "run_dir": str(run_dir),
        "started_at": started_at,
        "ended_at": ended_at,
        "wall_duration_s": ended_at - started_at,
        "duration_requested_s": float(args.duration_s),
        "sample_period_s": sample_period_s,
        "feeds": list(feeds),
        "screenshot_mode": screenshot_mode,
        "screenshot_count": screenshot_count,
        "frame_capture_enabled": not bool(args.no_frame_capture),
        "resume_controlled": resume_controlled,
        "post_run_drain_s": max(0.0, float(args.post_run_drain_s)),
        "post_run_drain_result": post_run_drain_result,
    }
    _json_dump(run_dir / "run.json", run_meta)
    _write_summary(
        run_dir=run_dir,
        run_meta=run_meta,
        samples=samples,
        start_runtime_stats=start_runtime_stats,
        end_runtime_stats=end_runtime_stats,
        start_rt_status=start_rt_status,
        end_rt_status=end_rt_status,
        ws_snapshot=recorder.snapshot() if recorder is not None else {},
    )

    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
