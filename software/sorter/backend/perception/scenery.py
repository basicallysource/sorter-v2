"""Scenery: what a detector boxes on a channel that is not a piece.

Any detection model now and then boxes something that is always in view: a
wall, a bracket, a thread stuck to the bowl, and on the classification channel
the rotor's own fins. This keeps a small memory of those boxes per channel and
drops a detection that matches one closely, the same place and shape
(IoU >= MATCH_IOU), before boxes are merged or tracked. Nothing is dropped only
for where it is: a piece beside scenery, or partly over it, keeps its box.

Two kinds of scenery:

- ``fixed``: still in the image whatever the rotor does (walls, brackets,
  threads). Dropped always.
- ``rest``: on the classification channel's rotor (its fins, marks on its
  hub), learned while the rotor rests with a fin over the exit
  (``fin_at_exit``), where every rest looks the same. Dropped only while the
  rotor rests there; while it turns, the rotor's scenery is not filtered.

It learns only from moments the channel holds no pieces:

- after homing the classification channel, once the pre-home sweep has cleared
  it and the rotor stands still;
- when someone asks for it (``requestLearn``, the "Learn the empty scene"
  button) with the channel empty.

What is boxed in at least LEARN_MIN_SHARE of the frames of such a moment is
learned; whatever was learned before and is not seen in any of them is
forgotten. While the classification channel's rotor turns, a learned box that
stays put in the image is fixed, and one that leaves is on the rotor: it is
kept as ``rest`` on a rotor that rests with a fin over the exit, and forgotten
on one that does not, since that rotor never comes back to the same pose. A box
nothing has matched over FORGET_AFTER_FRAMES frames in which the detector
boxed anything is forgotten too (frames with nothing boxed, a dark camera
or a stopped machine, do not count).

The memory is per machine (local state). A channel's is cleared when its zones
are redrawn, and the classification channel's also when its rotor settings
(fin count, fin over the exit, fin width) change.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

Bbox = tuple[int, int, int, int]

FIXED = "fixed"
REST = "rest"

# How closely a detection must match learned scenery to be dropped.
MATCH_IOU = 0.5
# A learning moment: how long it watches, and the share of its frames a box
# must be in to be learned.
LEARN_S = 3.0
LEARN_MIN_SHARE = 0.5
LEARN_MIN_FRAMES = 3
LEARN_GIVE_UP_S = 60.0
# Frames this soon after the rotor stops can still show it moving.
SETTLE_S = 0.4
# The motion check: frames a turn must give, and the share of them a learned box
# must be seen in to be fixed (at least) or on the rotor (at most).
MOTION_MIN_FRAMES = 6
MOTION_FIXED_SHARE = 0.6
MOTION_ROTOR_SHARE = 0.2
FORGET_AFTER_FRAMES = 20000
MAX_ENTRIES = 48
SAVE_EVERY_S = 5.0
SIGNATURE_EVERY_S = 15.0
SUMMARY_EVERY_S = 60.0
CLASSIFICATION_CHANNEL = 4


def iou(a: Bbox, b: Bbox) -> float:
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = float(ix * iy)
    area_a = float(max(0, a[2] - a[0]) * max(0, a[3] - a[1]))
    area_b = float(max(0, b[2] - b[0]) * max(0, b[3] - b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _median_box(boxes: list[Bbox]) -> Bbox:
    def med(values: list[int]) -> int:
        ordered = sorted(values)
        return int(ordered[len(ordered) // 2])

    return (
        med([b[0] for b in boxes]),
        med([b[1] for b in boxes]),
        med([b[2] for b in boxes]),
        med([b[3] for b in boxes]),
    )


@dataclass
class Entry:
    bbox: Bbox
    kind: str
    learned_at: float
    last_seen: float
    # The channel's count of frames with any box when this last matched; set
    # afresh on loading, so a restart never forgets anything by itself.
    seen_at: int = 0
    # The motion check's count for the turn in progress.
    move_frames: int = 0
    move_hits: int = 0

    def toDict(self) -> dict:
        return {
            "bbox": list(self.bbox),
            "kind": self.kind,
            "learned_at": self.learned_at,
            "last_seen": self.last_seen,
        }

    @staticmethod
    def fromDict(d: dict) -> Optional["Entry"]:
        try:
            bbox = tuple(int(v) for v in d["bbox"][:4])
            kind = str(d.get("kind", FIXED))
            if kind not in (FIXED, REST) or len(bbox) != 4:
                return None
            return Entry(
                bbox=bbox,  # type: ignore[arg-type]
                kind=kind,
                learned_at=float(d.get("learned_at", 0.0)),
                last_seen=float(d.get("last_seen", 0.0)),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class Pose:
    """Where the classification channel's rotor is, as its flow last said:
    turning or still, since when, and whether still with a fin over the exit."""

    moving: bool = False
    since: float = 0.0
    aligned: bool = False
    # Whether this rotor rests with a fin over the exit at all.
    rests_aligned: bool = False
    turn: int = 0


@dataclass
class _Learning:
    reason: str
    started: float
    requested: float = 0.0
    frames: int = 0
    # Clusters of boxes seen, one per thing: its boxes and the frames it was in.
    clusters: list = field(default_factory=list)


class ChannelScenery:
    def __init__(self, channel_id: int, owner: "SceneryMemory") -> None:
        self.channel_id = channel_id
        self.enabled = True
        self.entries: list[Entry] = []
        self.signature: Optional[str] = None
        self.dropped_total = 0
        self.active_frames = 0
        self.dropped_since_summary = 0
        self._learning: Optional[_Learning] = None
        self._owner = owner
        self._moving_seen = False

    # --- the hot path ------------------------------------------------------

    def process(self, bboxes: list, frame_ts: float) -> tuple[list, list]:
        """Learn from this frame if a learning moment is on, count the motion
        check, and return (kept, dropped)."""
        with self._owner.lock:
            pose = self._owner.pose if self.channel_id == CLASSIFICATION_CHANNEL else None
            if bboxes:
                self.active_frames += 1
            self._learn(bboxes, frame_ts, pose)
            self._motion(bboxes, frame_ts, pose)
            if not self.enabled or not self.entries or not bboxes:
                return list(bboxes), []
            at_rest = (
                pose is not None
                and pose.aligned
                and not pose.moving
                and frame_ts >= pose.since + SETTLE_S
            )
            kept: list = []
            dropped: list = []
            for b in bboxes:
                box = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
                match = None
                for e in self.entries:
                    if e.kind == REST and not at_rest:
                        continue
                    if iou(box, e.bbox) >= MATCH_IOU:
                        match = e
                        break
                if match is None:
                    kept.append(b)
                else:
                    match.last_seen = frame_ts
                    match.seen_at = self.active_frames
                    dropped.append(b)
            if dropped:
                self.dropped_total += len(dropped)
                self.dropped_since_summary += len(dropped)
            return kept, dropped

    # --- learning ------------------------------------------------------------

    def requestLearn(self, reason: str, now: float) -> None:
        with self._owner.lock:
            self._learning = _Learning(reason=reason, started=now + SETTLE_S, requested=now)

    @property
    def learning(self) -> bool:
        return self._learning is not None

    def _learn(self, bboxes: list, frame_ts: float, pose: Optional[Pose]) -> None:
        learning = self._learning
        if learning is None:
            return
        if frame_ts - learning.requested > LEARN_GIVE_UP_S:
            self._learning = None
            self._owner.log("warning", f"[scenery] channel {self.channel_id}: learning ({learning.reason}) "
                            f"gave up: the rotor did not stand still for {LEARN_S:g} s")
            return
        if frame_ts < learning.started:
            return
        if pose is not None and pose.moving:
            # The rotor turned under it: start the moment again once it stops.
            learning.started = frame_ts + SETTLE_S
            learning.frames = 0
            learning.clusters = []
            return
        if frame_ts < learning.started + LEARN_S:
            learning.frames += 1
            for b in bboxes:
                box = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
                for cluster in learning.clusters:
                    if iou(box, cluster["boxes"][-1]) >= MATCH_IOU:
                        cluster["boxes"].append(box)
                        cluster["frames"].add(learning.frames)
                        break
                else:
                    learning.clusters.append({"boxes": [box], "frames": {learning.frames}})
            return
        self._learning = None
        self._finishLearning(learning, frame_ts, pose)

    def _finishLearning(self, learning: _Learning, now: float, pose: Optional[Pose]) -> None:
        log = self._owner.log
        if learning.frames < LEARN_MIN_FRAMES:
            log("warning", f"[scenery] channel {self.channel_id}: learning ({learning.reason}) saw only "
                f"{learning.frames} frames; nothing changed")
            return
        if not learning.clusters:
            # Nothing boxed at all: a channel with no scenery, or a dark camera.
            # Either way it is no reason to forget anything.
            log("info", f"[scenery] channel {self.channel_id}: learning ({learning.reason}) saw nothing "
                f"boxed in {learning.frames} frames; nothing changed")
            return
        kind = REST if (pose is not None and pose.aligned) else FIXED
        need = max(LEARN_MIN_FRAMES, int(round(LEARN_MIN_SHARE * learning.frames)))
        found = [
            _median_box(c["boxes"]) for c in learning.clusters if len(c["frames"]) >= need
        ]
        seen_at_all = [_median_box(c["boxes"]) for c in learning.clusters]
        # Whatever applies at this pose and was not seen in any frame is gone.
        applies = (lambda e: True) if kind == REST else (lambda e: e.kind == FIXED)
        kept: list[Entry] = []
        forgotten = 0
        for e in self.entries:
            if applies(e) and not any(iou(e.bbox, s) >= MATCH_IOU for s in seen_at_all):
                forgotten += 1
                continue
            kept.append(e)
        learned = 0
        for box in found:
            match = next((e for e in kept if iou(e.bbox, box) >= MATCH_IOU), None)
            if match is not None:
                match.bbox = box
                match.last_seen = now
                match.seen_at = self.active_frames
                continue
            kept.append(Entry(bbox=box, kind=kind, learned_at=now, last_seen=now, seen_at=self.active_frames))
            learned += 1
        kept.sort(key=lambda e: e.last_seen, reverse=True)
        self.entries = kept[:MAX_ENTRIES]
        self._owner.dirty = True
        log("info", f"[scenery] channel {self.channel_id}: learned the empty scene ({learning.reason}, "
            f"{learning.frames} frames): {learned} new, {forgotten} forgotten, "
            f"{len(self.entries)} kept ({self._kinds()})")

    # --- the motion check ----------------------------------------------------

    def _motion(self, bboxes: list, frame_ts: float, pose: Optional[Pose]) -> None:
        if pose is None:
            return
        if pose.moving:
            if frame_ts < pose.since + SETTLE_S:
                return
            self._moving_seen = True
            boxes = [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in bboxes]
            for e in self.entries:
                e.move_frames += 1
                if any(iou(e.bbox, b) >= MATCH_IOU for b in boxes):
                    e.move_hits += 1
            return
        if not self._moving_seen:
            return
        # The turn is over: judge what it showed.
        self._moving_seen = False
        kept: list[Entry] = []
        changes: list[str] = []
        for e in self.entries:
            frames, hits = e.move_frames, e.move_hits
            e.move_frames = 0
            e.move_hits = 0
            if frames < MOTION_MIN_FRAMES:
                kept.append(e)
                continue
            share = hits / frames
            if share >= MOTION_FIXED_SHARE and e.kind != FIXED:
                e.kind = FIXED
                changes.append(f"{e.bbox} stays put: fixed")
            elif share <= MOTION_ROTOR_SHARE and e.kind == FIXED:
                if pose.rests_aligned:
                    e.kind = REST
                    changes.append(f"{e.bbox} turns with the rotor: only at rest")
                else:
                    changes.append(f"{e.bbox} turns with the rotor: forgotten")
                    continue
            kept.append(e)
        if changes:
            self.entries = kept
            self._owner.dirty = True
            self._owner.log("info", f"[scenery] channel {self.channel_id}: " + "; ".join(changes))

    # --- upkeep --------------------------------------------------------------

    def forgetStale(self) -> None:
        with self._owner.lock:
            before = len(self.entries)
            self.entries = [
                e for e in self.entries if self.active_frames - e.seen_at < FORGET_AFTER_FRAMES
            ]
            if len(self.entries) != before:
                self._owner.dirty = True
                self._owner.log("info", f"[scenery] channel {self.channel_id}: forgot "
                                f"{before - len(self.entries)} box(es) nothing matched in "
                                f"{FORGET_AFTER_FRAMES} frames")

    def clear(self, reason: str) -> None:
        with self._owner.lock:
            had = len(self.entries)
            self.entries = []
            self._learning = None
            self._owner.dirty = True
        if had:
            self._owner.log("info", f"[scenery] channel {self.channel_id}: forgot all {had} box(es) ({reason})")

    def _kinds(self) -> str:
        fixed = sum(1 for e in self.entries if e.kind == FIXED)
        return f"{fixed} fixed, {len(self.entries) - fixed} at rest"

    def status(self) -> dict:
        with self._owner.lock:
            return {
                "channel": self.channel_id,
                "enabled": self.enabled,
                "learning": self._learning is not None,
                "fixed": sum(1 for e in self.entries if e.kind == FIXED),
                "at_rest": sum(1 for e in self.entries if e.kind == REST),
                "dropped": self.dropped_total,
                "boxes": [e.toDict() for e in self.entries],
            }

    def toDict(self) -> dict:
        return {
            "enabled": self.enabled,
            "signature": self.signature,
            "entries": [e.toDict() for e in self.entries],
        }

    def load(self, d: dict) -> None:
        self.enabled = bool(d.get("enabled", True))
        self.signature = d.get("signature")
        self.entries = [e for e in (Entry.fromDict(x) for x in d.get("entries") or []) if e is not None][
            :MAX_ENTRIES
        ]


class SceneryMemory:
    """Every channel's scenery, saved per machine, and the classification
    channel rotor's pose, which its flow keeps up to date."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.pose = Pose()
        self.dirty = False
        self._channels: dict[int, ChannelScenery] = {}
        self._loaded = False
        self._logger: Any = None
        self._thread: Optional[threading.Thread] = None
        self._signatures: Optional[Callable[[], dict[int, str]]] = None

    def log(self, level: str, msg: str) -> None:
        logger = self._logger
        if logger is None:
            return
        try:
            getattr(logger, level)(msg)
        except Exception:
            pass

    def start(self, logger: Any, signatures: Optional[Callable[[], dict[int, str]]] = None) -> None:
        """Load what was saved and keep it saved, off the cameras' threads."""
        with self.lock:
            self._logger = logger
            self._signatures = signatures or _signatures
            if not self._loaded:
                self._load()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._upkeep, daemon=True, name="perception-scenery")
                self._thread.start()

    def channel(self, channel_id: int) -> ChannelScenery:
        scenery = self._channels.get(channel_id)
        if scenery is None:
            with self.lock:
                scenery = self._channels.get(channel_id)
                if scenery is None:
                    scenery = ChannelScenery(channel_id, self)
                    self._channels[channel_id] = scenery
        return scenery

    def setPose(self, *, moving: bool, aligned: bool = False, rests_aligned: bool = False) -> None:
        """The classification channel's rotor started turning, or stopped
        (with a fin over the exit or not)."""
        with self.lock:
            pose = self.pose
            if pose.moving == moving and pose.aligned == aligned and pose.rests_aligned == rests_aligned:
                return
            self.pose = Pose(
                moving=moving,
                since=time.time(),
                aligned=bool(aligned) and not moving,
                rests_aligned=bool(rests_aligned),
                turn=pose.turn + (1 if moving and not pose.moving else 0),
            )

    def statuses(self) -> list[dict]:
        return [self.channel(ch).status() for ch in sorted(set(self._channels) | {2, 3, 4})]

    # --- saving --------------------------------------------------------------

    def _load(self) -> None:
        self._loaded = True
        try:
            import local_state

            blob = local_state.get_perception_scenery() or {}
        except Exception as exc:
            self.log("warning", f"[scenery] could not read the saved scenery: {exc}")
            return
        for key, value in (blob.get("channels") or {}).items():
            try:
                channel_id = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                self.channel(channel_id).load(value)

    def _save(self) -> None:
        with self.lock:
            if not self.dirty:
                return
            blob = {"channels": {str(ch): s.toDict() for ch, s in self._channels.items()}}
            self.dirty = False
        try:
            import local_state

            local_state.set_perception_scenery(blob)
        except Exception as exc:
            self.dirty = True
            self.log("warning", f"[scenery] could not save the scenery: {exc}")

    def _upkeep(self) -> None:
        next_signature = 0.0
        next_summary = time.time() + SUMMARY_EVERY_S
        while True:
            time.sleep(SAVE_EVERY_S)
            now = time.time()
            try:
                if now >= next_signature:
                    next_signature = now + SIGNATURE_EVERY_S
                    self._checkSignatures()
                    for scenery in list(self._channels.values()):
                        scenery.forgetStale()
                if now >= next_summary:
                    next_summary = now + SUMMARY_EVERY_S
                    for scenery in list(self._channels.values()):
                        if scenery.dropped_since_summary:
                            self.log("info", f"[scenery] channel {scenery.channel_id}: dropped "
                                     f"{scenery.dropped_since_summary} box(es) matching its scenery in the "
                                     f"last {SUMMARY_EVERY_S:g} s")
                            scenery.dropped_since_summary = 0
                self._save()
            except Exception as exc:
                self.log("warning", f"[scenery] upkeep failed: {exc}")

    def _checkSignatures(self) -> None:
        getter = self._signatures
        if getter is None:
            return
        current = getter()
        for channel_id, signature in current.items():
            scenery = self.channel(channel_id)
            if scenery.signature is None:
                with self.lock:
                    scenery.signature = signature
                    self.dirty = True
            elif scenery.signature != signature:
                scenery.clear("its zones or rotor settings changed")
                with self.lock:
                    scenery.signature = signature
                    self.dirty = True


def _signatures() -> dict[int, str]:
    """What each channel's scenery was learned against: its zones as saved, and
    for the classification channel its rotor's fin settings."""
    out: dict[int, str] = {}
    try:
        from zones.store import loadChannel
    except Exception:
        return out
    rotor = ""
    try:
        from toml_config import getClassificationChannelRev01Config

        cfg = getClassificationChannelRev01Config()
        rotor = f"|{cfg.get('fin_count')}|{cfg.get('fin_at_exit')}|{cfg.get('fin_width_deg')}"
    except Exception:
        pass
    for channel_id in (2, 3, 4):
        zones = loadChannel(channel_id)
        if zones is None:
            continue
        signature = f"{getattr(zones, 'updated_at', None)}"
        if channel_id == CLASSIFICATION_CHANNEL:
            signature += rotor
        out[channel_id] = signature
    return out


# One per process: the cameras' workers are rebuilt when their zones or model
# change, and what they learned outlives them.
scenery = SceneryMemory()
