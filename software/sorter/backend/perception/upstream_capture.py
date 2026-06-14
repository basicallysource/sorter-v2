"""Rolling upstream-crop store + Gemini-embedding similarity search.

Goal: when a piece lands in the classification channel (C4) we want extra,
independent views of it from the channels it passed through (C2/C3) so a
recognizer can fuse them for higher confidence — instead of relying on a burst
of near-identical C4 frames.

Pipeline, all off the inference hot path:
  collector thread  → crops on-channel detections (rate-limited / deduped) → queue
  embed thread      → batches crops → OpenRouter Gemini multimodal embeddings
                      → stores vector + jpeg + metadata in a local sqlite-vec DB
  search (on demand)→ embeds the anchor piece's crop → cosine-KNN over the vec DB
                      within a time window → ranked candidates

Similarity is a single system: image embeddings (google/gemini-embedding-2,
3072-dim) compared by cosine distance in sqlite-vec. Precision-oriented: the
caller gates on ``min_similarity`` so a weak match returns nothing.

Embedding is a paid network call, so the collector dedups to roughly one crop
per piece-pass per channel (``min_enqueue_interval_s``) — never one per frame.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Optional

import cv2
import numpy as np


OPENROUTER_URL = "https://openrouter.ai/api/v1/embeddings"
EMBED_MODEL = "google/gemini-embedding-2"
EMBED_DIM = 3072
ANCHOR_MAX_CROPS = 3
_HTTP_TIMEOUT_S = 60.0


def _vecDbPath() -> str:
    override = os.getenv("UPSTREAM_VEC_DB")
    if override:
        return override
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, "upstream_vec.sqlite")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class UpstreamMatchConfig:
    # --- Collection -----------------------------------------------------
    # Off by default — this is a paid-API, experimental feature; enable it
    # explicitly from the tuning page when you want to collect.
    enabled: bool = False
    collect_ch2: bool = True
    collect_ch3: bool = True
    # Frame sample cadence: every this many seconds we grab ONE frame per enabled
    # channel and embed EVERY on-channel bbox in it. Lower = more coverage + more
    # cost (each crop is a paid embedding). This — not the camera frame rate —
    # sets the steady-state volume.
    sample_interval_s: float = 0.5
    crop_pad_px: int = 6
    jpeg_quality: int = 80
    # How long crops/vectors live in the local DB.
    window_seconds: int = 180
    # Crops embedded per OpenRouter request (a busy frame has many bboxes).
    embed_batch_size: int = 32
    # Pending-crop queue cap; excess crops are dropped (we'd rather skip than
    # back up unbounded).
    embed_max_queue: int = 1024

    # --- Search ---------------------------------------------------------
    # Window relative to the anchor's arrival: the piece was upstream BEFORE it
    # reached C4, so look back, plus a little forward for clock skew.
    lookback_seconds: float = 120.0
    forward_seconds: float = 2.0
    # Per-channel time windows. When False, every channel uses the single
    # lookback/forward window above. When True, each channel gets its own window
    # expressed as a span of "seconds before the piece arrived at C4": the piece
    # passes the further-upstream channel (C2) earlier than the nearer one (C3),
    # so their best matches sit at different ages. A window runs from
    # ``*_window_start_s`` (older edge) to ``*_window_end_s`` (newer edge) seconds
    # before arrival; set the end negative to extend past arrival for clock skew.
    per_channel_window: bool = False
    ch2_window_start_s: float = 60.0
    ch2_window_end_s: float = 30.0
    ch3_window_start_s: float = 30.0
    ch3_window_end_s: float = 0.0
    # Cosine-similarity floor (similarity = 1 - cosine_distance). The
    # precision-over-recall knob.
    min_similarity: float = 0.5
    max_results: int = 24
    search_ch2: bool = True
    search_ch3: bool = True
    # When both channels are searched, how the top results are drawn:
    #  - False (default): ONE similarity search over both channels' crops pooled
    #    together — the global top ``max_results``, so the channel with stronger
    #    matches can take every slot.
    #  - True: search each channel SEPARATELY, take the top ``max_results`` from
    #    C2 and the top ``max_results`` from C3, then merge — both channels are
    #    always represented. No effect when only one channel is enabled.
    search_per_channel_topn: bool = False

    # --- Classification injection --------------------------------------
    # When a piece lands on C4, embed its burst crops, find its best upstream
    # (C2/C3) matches, and hand those extra views to Brickognize alongside the
    # C4 burst. Off by default — same paid embedding call as search, run once
    # per classified piece.
    classify_inject_enabled: bool = False
    # How many upstream matches to GRAB (top-N by similarity) and attach to the
    # piece for review. All grabbed crops show on the detail card; only the most
    # similar ``classify_use_n`` of them are actually sent to Brickognize.
    classify_top_n: int = 3
    # Of the grabbed matches, how many of the most-similar to USE for
    # classification — sent to Brickognize and flagged used. The rest stay on the
    # piece for review but did not influence the result. Capped so the total
    # (burst + used upstream) never exceeds Brickognize's 8-image limit.
    classify_use_n: int = 1
    # Only inject a match this similar or better (cosine similarity 0-1).
    classify_min_similarity: float = 0.8


_DEFAULTS = UpstreamMatchConfig()

FIELD_META: list[dict] = [
    {"section": "Collection", "key": "enabled", "label": "Collection enabled", "type": "bool", "default": _DEFAULTS.enabled, "description": "Master switch for crop collection. When on (and the machine is sorting), frames from the enabled upstream channels are sampled, cropped, embedded, and stored. Uses a paid embedding API, so it's off by default."},
    {"section": "Collection", "key": "collect_ch2", "label": "Collect from C2", "type": "bool", "default": _DEFAULTS.collect_ch2, "description": "Collect crops from Channel 2, an upstream C-channel the piece passes through before reaching C4."},
    {"section": "Collection", "key": "collect_ch3", "label": "Collect from C3", "type": "bool", "default": _DEFAULTS.collect_ch3, "description": "Collect crops from Channel 3, an upstream C-channel the piece passes through before reaching C4."},
    {"section": "Collection", "key": "sample_interval_s", "label": "Frame sample interval (s) — embeds all bboxes per sample", "type": "float", "default": _DEFAULTS.sample_interval_s, "description": "How often a frame is sampled for embedding. Every this many seconds, one frame per enabled channel is grabbed and every piece bbox in it is embedded. This — not the camera frame rate — sets how many paid embeddings you generate. Lower = more coverage and more cost."},
    {"section": "Collection", "key": "crop_pad_px", "label": "Crop padding (px)", "type": "int", "default": _DEFAULTS.crop_pad_px, "description": "Extra pixels added around each detected bounding box when cutting out the crop, so the embedded image isn't trimmed tight to the piece."},
    {"section": "Collection", "key": "jpeg_quality", "label": "JPEG quality", "type": "int", "default": _DEFAULTS.jpeg_quality, "description": "JPEG compression quality (0–100) for stored crops. Higher = sharper images but larger storage."},
    {"section": "Collection", "key": "window_seconds", "label": "Rolling window (s)", "type": "int", "default": _DEFAULTS.window_seconds, "description": "How long each crop and its embedding vector stays in the local vector database before it's pruned. Anything older than this age is deleted. A piece reaches C4 within seconds of being on C2/C3, so it only needs to stay searchable for a couple of minutes."},
    {"section": "Collection", "key": "embed_batch_size", "label": "Embed batch size", "type": "int", "default": _DEFAULTS.embed_batch_size, "description": "Number of crops sent per embedding API request. A busy frame has many bboxes; batching them into one request cuts the number of API calls."},
    {"section": "Collection", "key": "embed_max_queue", "label": "Max pending crops", "type": "int", "default": _DEFAULTS.embed_max_queue, "description": "Capacity of the in-memory queue of crops waiting to be embedded. If embedding can't keep up and the queue fills, new crops are dropped rather than letting the backlog grow unbounded."},
    {"section": "Search", "key": "lookback_seconds", "label": "Look back from arrival (s)", "type": "float", "default": _DEFAULTS.lookback_seconds, "description": "When searching for a C4 piece's earlier views, how far BEFORE its C4 arrival time to look. The piece was upstream before it reached C4, so its matches are in the recent past."},
    {"section": "Search", "key": "forward_seconds", "label": "Look forward from arrival (s)", "type": "float", "default": _DEFAULTS.forward_seconds, "description": "How far AFTER the piece's C4 arrival time to also include in the search, to absorb small clock differences between the cameras."},
    {"section": "Search", "key": "per_channel_window", "label": "Per-channel time windows", "type": "bool", "default": _DEFAULTS.per_channel_window, "description": "When off, every channel is searched over the same 'Look back/forward from arrival' window above. When on, C2 and C3 each use their own window below, set as a span of seconds before the piece reached C4. The piece passes C2 (further upstream) earlier than C3, so their matches sit at different ages."},
    {"section": "Search", "key": "ch2_window_start_s", "label": "C2 window start (s before arrival)", "type": "float", "default": _DEFAULTS.ch2_window_start_s, "description": "Only used when 'Per-channel time windows' is on. Older edge of the C2 search window: how many seconds before the piece arrived at C4 the window begins. Default 60 = start looking 60s before arrival."},
    {"section": "Search", "key": "ch2_window_end_s", "label": "C2 window end (s before arrival)", "type": "float", "default": _DEFAULTS.ch2_window_end_s, "description": "Only used when 'Per-channel time windows' is on. Newer edge of the C2 search window: how many seconds before arrival the window ends. Default 30 = stop at 30s before arrival, so C2 covers 30–60s ago. Set negative to extend past arrival into the future (e.g. -2 = 2s after arrival) for clock skew."},
    {"section": "Search", "key": "ch3_window_start_s", "label": "C3 window start (s before arrival)", "type": "float", "default": _DEFAULTS.ch3_window_start_s, "description": "Only used when 'Per-channel time windows' is on. Older edge of the C3 search window: how many seconds before arrival the window begins. Default 30 = start looking 30s before arrival."},
    {"section": "Search", "key": "ch3_window_end_s", "label": "C3 window end (s before arrival)", "type": "float", "default": _DEFAULTS.ch3_window_end_s, "description": "Only used when 'Per-channel time windows' is on. Newer edge of the C3 search window: how many seconds before arrival the window ends. Default 0 = up to the arrival moment, so C3 covers 0–30s ago. Set negative to extend past arrival into the future (e.g. -2 = 2s after arrival) for clock skew."},
    {"section": "Search", "key": "min_similarity", "label": "Min similarity (0-1)", "type": "float", "default": _DEFAULTS.min_similarity, "description": "Minimum cosine similarity (0–1, where 1 is identical) a stored crop must have to the query to count as a match. Higher = fewer but more confident matches."},
    {"section": "Search", "key": "max_results", "label": "Max results", "type": "int", "default": _DEFAULTS.max_results, "description": "Maximum number of candidate matches a search returns."},
    {"section": "Search", "key": "search_ch2", "label": "Search C2", "type": "bool", "default": _DEFAULTS.search_ch2, "description": "Include Channel 2 crops when searching for matches."},
    {"section": "Search", "key": "search_ch3", "label": "Search C3", "type": "bool", "default": _DEFAULTS.search_ch3, "description": "Include Channel 3 crops when searching for matches."},
    {"section": "Search", "key": "search_per_channel_topn", "label": "Top-N per channel (don't pool C2 + C3)", "type": "bool", "default": _DEFAULTS.search_per_channel_topn, "description": "How results are drawn when both C2 and C3 are searched. Off: one search over both channels' crops pooled together, returning the global top 'Max results' — a channel with stronger matches can take every slot. On: search each channel on its own and take the top 'Max results' from C2 and the top 'Max results' from C3, then merge, so both channels are always represented. No effect when only one channel is enabled."},
    {"section": "Classification", "key": "classify_inject_enabled", "label": "Inject matches into Brickognize", "type": "bool", "default": _DEFAULTS.classify_inject_enabled, "description": "When a piece lands on C4, automatically find its best upstream (C2/C3) views and send them to Brickognize alongside the C4 photos, giving the classifier extra angles. Runs one paid embedding per classified piece, so it's off by default."},
    {"section": "Classification", "key": "classify_top_n", "label": "Matches to grab (top N)", "type": "int", "default": _DEFAULTS.classify_top_n, "description": "How many upstream matches to GRAB (top-N by similarity) and attach to the piece for review. All of these show on the piece's detail card."},
    {"section": "Classification", "key": "classify_use_n", "label": "Matches to use for classification (top N)", "type": "int", "default": _DEFAULTS.classify_use_n, "description": "Of the grabbed matches, how many of the most-similar to actually SEND to Brickognize for classification. The rest are kept for review only. Total images (C4 burst + these) is capped at Brickognize's 8-image limit."},
    {"section": "Classification", "key": "classify_min_similarity", "label": "Min similarity to inject (0-1)", "type": "float", "default": _DEFAULTS.classify_min_similarity, "description": "Minimum cosine similarity (0–1) required before an upstream match is injected into classification. Stricter than the search floor so only strong matches influence the result."},
]


def configFromDict(d: dict) -> UpstreamMatchConfig:
    cfg = UpstreamMatchConfig()
    for meta in FIELD_META:
        k = meta["key"]
        if k not in d:
            continue
        raw = d[k]
        try:
            if meta["type"] == "int":
                setattr(cfg, k, int(raw))
            elif meta["type"] == "bool":
                setattr(cfg, k, bool(raw))
            else:
                setattr(cfg, k, float(raw))
        except (TypeError, ValueError):
            pass
    return cfg


def configToDict(cfg: UpstreamMatchConfig) -> dict[str, object]:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}


# ---------------------------------------------------------------------------
# Embeddings (OpenRouter / Gemini)
# ---------------------------------------------------------------------------


def _serializeF32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _jpegBytesToDataUri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def _b64ToDataUri(b64: str) -> str:
    return "data:image/jpeg;base64," + b64


def embedDataUris(data_uris: list[str], logger: Any = None) -> list[Optional[list[float]]]:
    """Embed each image data-URI via OpenRouter, index-aligned. Failures (and a
    missing key) yield ``None`` rows so the caller can drop them."""
    n = len(data_uris)
    if n == 0:
        return []
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        _log(logger, "warning", "[upstream] OPENROUTER_API_KEY not set; cannot embed")
        return [None] * n
    body = {
        "model": EMBED_MODEL,
        "input": [
            {"content": [{"type": "image_url", "image_url": {"url": uri}}]}
            for uri in data_uris
        ],
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://sorter.local",
            "X-Title": "sorter-upstream-match",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        _log(logger, "warning", f"[upstream] embed HTTP {exc.code}: {detail}")
        return [None] * n
    except Exception as exc:
        _log(logger, "warning", f"[upstream] embed failed: {exc}")
        return [None] * n
    out: list[Optional[list[float]]] = [None] * n
    for item in payload.get("data") or []:
        idx = item.get("index")
        emb = item.get("embedding")
        if isinstance(idx, int) and 0 <= idx < n and isinstance(emb, list):
            out[idx] = emb
    return out


def anchorImageB64s(payload: dict) -> list[str]:
    b64s: list[str] = []
    for entry in (payload.get("recognition_image_set") or []):
        if not isinstance(entry, dict) or entry.get("source") != "c4_burst":
            continue
        img = entry.get("image")
        if isinstance(img, str) and img:
            b64s.append(img)
    if not b64s:
        latest = payload.get("latest_captured_crop")
        if isinstance(latest, str) and latest:
            b64s.append(latest)
    return b64s


# ---------------------------------------------------------------------------
# Cropping
# ---------------------------------------------------------------------------


def _cropBbox(bgr: np.ndarray, bbox: Any, pad: int, w: int, h: int) -> Optional[np.ndarray]:
    try:
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError, IndexError):
        return None
    xa = max(0, int(round(min(x1, x2))) - pad)
    ya = max(0, int(round(min(y1, y2))) - pad)
    xb = min(w, int(round(max(x1, x2))) + pad)
    yb = min(h, int(round(max(y1, y2))) + pad)
    if xb <= xa or yb <= ya:
        return None
    return bgr[ya:yb, xa:xb]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass
class _PendingCrop:
    ts: float
    channel: int
    bbox: tuple[float, float, float, float]
    jpeg: bytes
    jpeg_b64: str


class UpstreamCropStore:
    def __init__(self, *, perception_service: Any, logger: Any = None) -> None:
        self._service = perception_service
        self._logger = logger
        self._cfg_lock = threading.Lock()
        self._cfg = UpstreamMatchConfig()
        self._queue: "queue.Queue[_PendingCrop]" = queue.Queue(maxsize=_DEFAULTS.embed_max_queue)
        self._last_enqueue_ts: dict[int, float] = {}
        self._last_frame_ts: dict[int, float] = {}
        self._stop = threading.Event()
        self._collector: Optional[threading.Thread] = None
        self._embedder: Optional[threading.Thread] = None
        self._db_lock = threading.Lock()
        self._counter = 0
        self._embedded_total = 0
        self._dropped_total = 0
        self._last_embed_error: Optional[str] = None

    def configure(self, cfg: UpstreamMatchConfig) -> None:
        with self._cfg_lock:
            self._cfg = cfg

    def config(self) -> UpstreamMatchConfig:
        with self._cfg_lock:
            return self._cfg

    def start(self) -> None:
        if self._collector is not None:
            return
        self._stop.clear()
        self._collector = threading.Thread(target=self._collectLoop, daemon=True, name="upstream-collector")
        self._embedder = threading.Thread(target=self._embedLoop, daemon=True, name="upstream-embedder")
        self._collector.start()
        self._embedder.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        for t in (self._collector, self._embedder):
            if t is not None:
                t.join(timeout=timeout)
        self._collector = None
        self._embedder = None

    # --- db -------------------------------------------------------------

    def _openDb(self):
        import sqlite3
        import sqlite_vec

        con = sqlite3.connect(_vecDbPath(), check_same_thread=False)
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute("pragma journal_mode=WAL")
        con.execute(
            f"create virtual table if not exists upstream_crops using vec0("
            f"crop_id integer primary key, ts float, channel integer, "
            f"+bbox text, +jpeg text, embedding float[{EMBED_DIM}] distance_metric=cosine)"
        )
        return con

    # --- collection -----------------------------------------------------

    def _isSorting(self) -> bool:
        # Only collect while the machine is actively sorting (RUNNING). Paused,
        # ready, or standby means pieces aren't flowing — embedding then just
        # burns paid API calls on whatever is parked in view. Mirrors
        # SampleCollector._isSorting.
        try:
            from server import shared_state
            from defs.sorter_controller import SorterLifecycle

            controller = shared_state.controller_ref
            if controller is None:
                return False
            return controller.state == SorterLifecycle.RUNNING
        except Exception:
            return False

    def _collectLoop(self) -> None:
        while not self._stop.is_set():
            cfg = self.config()
            if not cfg.enabled or not self._isSorting():
                self._stop.wait(0.5)
                continue
            for ch in self._collectChannels(cfg):
                try:
                    self._collectChannel(ch, cfg)
                except Exception as exc:
                    _log(self._logger, "warning", f"[upstream] collect ch{ch} failed: {exc}")
            # Poll a touch faster than the sample interval; the interval gate in
            # _collectChannel does the real cadence.
            self._stop.wait(max(0.05, min(cfg.sample_interval_s, 0.25)))

    @staticmethod
    def _collectChannels(cfg: UpstreamMatchConfig) -> list[int]:
        chans: list[int] = []
        if cfg.collect_ch2:
            chans.append(2)
        if cfg.collect_ch3:
            chans.append(3)
        return chans

    def _collectChannel(self, channel_id: int, cfg: UpstreamMatchConfig) -> None:
        now = time.time()
        last = self._last_enqueue_ts.get(channel_id, 0.0)
        if now - last < cfg.sample_interval_s:
            return
        res = self._service.read_bboxes_and_frame(channel_id)
        if res is None:
            return
        bboxes, frame = res
        # Mark the sample tick even on an empty frame so the cadence stays steady.
        self._last_enqueue_ts[channel_id] = now
        if not bboxes:
            return
        ts = float(frame.timestamp)
        if self._last_frame_ts.get(channel_id) == ts:
            return
        bgr = frame.bgr
        if bgr is None or bgr.size == 0:
            return
        h, w = bgr.shape[:2]
        self._last_frame_ts[channel_id] = ts
        # Embed EVERY on-channel bbox in this sampled frame. C2/C3 hold many
        # pieces at once (they're being separated) and any of them may be the one
        # that reaches C4, so we must never drop one — no largest-only, no dedup.
        for b in bboxes:
            crop = _cropBbox(bgr, b, cfg.crop_pad_px, w, h)
            if crop is None or crop.size == 0:
                continue
            ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), int(cfg.jpeg_quality)])
            if not ok:
                continue
            jpeg = buf.tobytes()
            item = _PendingCrop(
                ts=ts,
                channel=channel_id,
                bbox=(float(b[0]), float(b[1]), float(b[2]), float(b[3])),
                jpeg=jpeg,
                jpeg_b64=base64.b64encode(jpeg).decode("ascii"),
            )
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self._dropped_total += 1

    # --- embedding ------------------------------------------------------

    def _embedLoop(self) -> None:
        try:
            con = self._openDb()
        except Exception as exc:
            _log(self._logger, "error", f"[upstream] vec DB open failed: {exc}")
            return
        row = con.execute("select max(crop_id) from upstream_crops").fetchone()
        self._counter = int(row[0]) + 1 if row and row[0] is not None else 1
        last_prune = 0.0
        while not self._stop.is_set():
            cfg = self.config()
            batch = self._drainBatch(cfg.embed_batch_size, timeout=0.5)
            if batch:
                uris = [_jpegBytesToDataUri(it.jpeg) for it in batch]
                vecs = embedDataUris(uris, self._logger)
                rows = []
                any_fail = False
                for it, vec in zip(batch, vecs):
                    if vec is None or len(vec) != EMBED_DIM:
                        any_fail = True
                        continue
                    rows.append((self._counter, it.ts, it.channel, json.dumps([round(v, 1) for v in it.bbox]), it.jpeg_b64, _serializeF32(vec)))
                    self._counter += 1
                if rows:
                    try:
                        with self._db_lock:
                            con.executemany(
                                "insert into upstream_crops(crop_id, ts, channel, bbox, jpeg, embedding) values (?,?,?,?,?,?)",
                                rows,
                            )
                            con.commit()
                        self._embedded_total += len(rows)
                        self._last_embed_error = None
                    except Exception as exc:
                        self._last_embed_error = str(exc)
                        _log(self._logger, "warning", f"[upstream] vec insert failed: {exc}")
                elif any_fail:
                    self._last_embed_error = "embedding request returned no usable vectors"
            now = time.time()
            if now - last_prune > 5.0:
                try:
                    with self._db_lock:
                        con.execute("delete from upstream_crops where ts < ?", (now - cfg.window_seconds,))
                        con.commit()
                except Exception:
                    pass
                last_prune = now

    def _drainBatch(self, max_n: int, timeout: float) -> list[_PendingCrop]:
        batch: list[_PendingCrop] = []
        try:
            batch.append(self._queue.get(timeout=timeout))
        except queue.Empty:
            return batch
        while len(batch) < max_n:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    # --- search ---------------------------------------------------------

    def search(self, anchor_b64s: list[str], ref_ts: float, cfg: UpstreamMatchConfig) -> dict:
        uris = [_b64ToDataUri(b) for b in anchor_b64s[:ANCHOR_MAX_CROPS]]
        vecs = [v for v in embedDataUris(uris, self._logger) if v and len(v) == EMBED_DIM]
        if not vecs:
            return {"candidates": [], "error": "anchor embedding failed (no usable vectors)", "n_anchor_embedded": 0}
        query = np.mean(np.asarray(vecs, dtype=np.float32), axis=0).tolist()

        channels: list[int] = []
        if cfg.search_ch2:
            channels.append(2)
        if cfg.search_ch3:
            channels.append(3)
        if not channels:
            return {"candidates": [], "n_anchor_embedded": len(vecs)}

        k = int(max(1, cfg.max_results))

        def _windowFor(group: list[int]) -> tuple[float, float]:
            # Per-channel windows are spans of "seconds before arrival": the window
            # runs from start_s (older edge) to end_s (newer edge) before ref_ts. A
            # negative end reaches past arrival into the future (clock-skew slack).
            if cfg.per_channel_window and len(group) == 1:
                if group[0] == 2:
                    return ref_ts - cfg.ch2_window_start_s, ref_ts - cfg.ch2_window_end_s
                return ref_ts - cfg.ch3_window_start_s, ref_ts - cfg.ch3_window_end_s
            return ref_ts - cfg.lookback_seconds, ref_ts + cfg.forward_seconds

        # Split into per-channel queries when either per-channel windows or
        # per-channel top-N is on (both need each channel queried on its own).
        # Otherwise a single pooled KNN over both channels returns the global top-k.
        if (cfg.per_channel_window or cfg.search_per_channel_topn) and len(channels) > 1:
            query_groups = [[c] for c in channels]
        else:
            query_groups = [channels]

        rows: list[Any] = []
        try:
            con = self._openDb()
            try:
                for group in query_groups:
                    t0, t1 = _windowFor(group)
                    sql = (
                        "select channel, ts, bbox, jpeg, distance from upstream_crops "
                        "where embedding match ? and k = ? and ts >= ? and ts <= ?"
                    )
                    params: list[Any] = [_serializeF32(query), k, t0, t1]
                    if len(group) == 1:
                        sql += " and channel = ?"
                        params.append(group[0])
                    sql += " order by distance"
                    rows.extend(con.execute(sql, params).fetchall())
            finally:
                con.close()
        except Exception as exc:
            _log(self._logger, "warning", f"[upstream] search query failed: {exc}")
            return {"candidates": [], "error": f"query failed: {exc}", "n_anchor_embedded": len(vecs)}

        candidates = []
        for channel, ts, bbox_json, jpeg_b64, distance in rows:
            score = 1.0 - float(distance)
            if score < cfg.min_similarity:
                continue
            try:
                bbox = json.loads(bbox_json) if bbox_json else []
            except Exception:
                bbox = []
            candidates.append({
                "channel_id": int(channel),
                "ts": float(ts),
                "dt_s": round(float(ts) - ref_ts, 3),
                "score": round(score, 4),
                "method": "gemini-embedding-2",
                "bbox": bbox,
                "jpeg_b64": jpeg_b64,
            })
        candidates.sort(key=lambda c: c["score"], reverse=True)
        # Per-channel top-N keeps each channel's top-k (up to 2k total); pooled
        # mode (even when split for per-channel windows) returns the global top-k.
        if not cfg.search_per_channel_topn:
            candidates = candidates[:k]
        return {"candidates": candidates, "n_anchor_embedded": len(vecs)}

    def matchForClassification(self, anchor_b64s: list[str], ref_ts: float) -> list[dict]:
        """Top-N upstream matches to fuse into a C4 piece's Brickognize call.

        Reuses ``search`` but gates on the classification-specific knobs
        (``classify_min_similarity`` / ``classify_top_n``) instead of the
        search-page ones. Grabs ``classify_top_n`` candidates (sorted most-
        similar first) and tags each with ``used``: True for the most-similar
        ``classify_use_n``, which are the ones actually sent to Brickognize.
        Returns ``[]`` when injection is disabled, there is no anchor, or nothing
        clears the bar."""
        cfg = self.config()
        if not cfg.classify_inject_enabled or cfg.classify_top_n < 1 or not anchor_b64s:
            return []
        search_cfg = replace(
            cfg,
            min_similarity=cfg.classify_min_similarity,
            max_results=cfg.classify_top_n,
        )
        result = self.search(anchor_b64s, ref_ts, search_cfg)
        candidates = list(result.get("candidates", []))[: cfg.classify_top_n]
        use_n = max(0, int(cfg.classify_use_n))
        for i, cand in enumerate(candidates):
            if isinstance(cand, dict):
                cand["used"] = i < use_n
        return candidates

    def listCrops(self, offset: int = 0, limit: int = 60, channel: Optional[int] = None) -> dict:
        """Paginated view of what's actually embedded + stored, newest first."""
        where = ""
        params: list[Any] = []
        if channel in (2, 3):
            where = "where channel = ?"
            params.append(channel)
        try:
            con = self._openDb()
            try:
                total = con.execute(f"select count(*) from upstream_crops {where}", params).fetchone()[0]
                rows = con.execute(
                    f"select channel, ts, bbox, jpeg from upstream_crops {where} order by ts desc limit ? offset ?",
                    params + [int(limit), int(offset)],
                ).fetchall()
            finally:
                con.close()
        except Exception as exc:
            return {"total": 0, "offset": offset, "limit": limit, "items": [], "error": str(exc)}
        items = []
        for ch, ts, bbox_json, jpeg_b64 in rows:
            try:
                bbox = json.loads(bbox_json) if bbox_json else []
            except Exception:
                bbox = []
            items.append({"channel_id": int(ch), "ts": float(ts), "bbox": bbox, "jpeg_b64": jpeg_b64})
        return {"total": int(total), "offset": int(offset), "limit": int(limit), "items": items}

    # --- introspection --------------------------------------------------

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "enabled": self.config().enabled,
            "sorting": self._isSorting(),
            "queued": self._queue.qsize(),
            "embedded_total": self._embedded_total,
            "dropped_total": self._dropped_total,
            "last_embed_error": self._last_embed_error,
        }
        try:
            con = self._openDb()
            try:
                per = {}
                for ch, cnt, oldest, newest in con.execute(
                    "select channel, count(*), min(ts), max(ts) from upstream_crops group by channel"
                ).fetchall():
                    per[str(ch)] = {"count": cnt, "oldest_ts": oldest, "newest_ts": newest}
                out["channels"] = per
            finally:
                con.close()
        except Exception as exc:
            out["db_error"] = str(exc)
        return out


def _log(logger: Any, level: str, msg: str) -> None:
    if logger is None:
        return
    fn = getattr(logger, level, None) or getattr(logger, "info", None)
    if fn is None:
        return
    try:
        fn(msg)
    except Exception:
        pass
