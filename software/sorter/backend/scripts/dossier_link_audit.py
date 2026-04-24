"""Offline audit for piece-dossier stitching candidates.

The runtime tracker may split one physical LEGO piece into multiple short
dossiers. This script reads the local SQLite state without mutating it, scores
candidate links by time, class, angle and crop similarity, and writes a compact
report plus visual contact sheets for manual verification.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_DB = Path("local_state.sqlite")
DEFAULT_OUTPUT = Path(".tmp-dossier-links")


@dataclass(slots=True)
class Segment:
    role: str
    tracked_global_id: int | None
    first_seen_ts: float | None
    last_seen_ts: float | None
    hit_count: int
    snapshot_path: str | None
    sector_snapshots: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Dossier:
    piece_uuid: str
    tracked_global_id: int | None
    created_at: float | None
    updated_at: float | None
    stage: str
    classification_status: str
    zone_center_deg: float | None
    zone_state: str | None
    part_id: str | None
    color_id: str | None
    part_name: str | None
    preview_jpeg_path: str | None
    segments: list[Segment] = field(default_factory=list)

    @property
    def event_ts(self) -> float | None:
        segment_ts = [
            s.first_seen_ts
            for s in self.segments
            if isinstance(s.first_seen_ts, (int, float)) and s.first_seen_ts > 0
        ]
        if segment_ts:
            return min(float(v) for v in segment_ts)
        for value in (self.created_at, self.updated_at):
            if isinstance(value, (int, float)) and 0 < value < 1_000_000_000:
                return float(value)
        return None

    @property
    def best_image_path(self) -> str | None:
        if self.preview_jpeg_path:
            return self.preview_jpeg_path
        best: tuple[float, str] | None = None
        for segment in self.segments:
            for sector in segment.sector_snapshots:
                path = sector.get("jpeg_path")
                ts = sector.get("captured_ts")
                if isinstance(path, str) and path:
                    score = float(ts) if isinstance(ts, (int, float)) else 0.0
                    if best is None or score > best[0]:
                        best = (score, path)
            if best is None and segment.snapshot_path:
                best = (0.0, segment.snapshot_path)
        return best[1] if best else None


@dataclass(slots=True)
class ImageFeatures:
    path: str
    width: int
    height: int
    dhash: int
    histogram: np.ndarray


@dataclass(slots=True)
class LinkCandidate:
    source_uuid: str
    target_uuid: str
    confidence: float
    relation: str
    time_gap_s: float | None
    angle_delta_deg: float | None
    image_similarity: float | None
    class_relation: str
    reasons: list[str]


class UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self._parent.setdefault(item, item)
        parent = self._parent[item]
        if parent != item:
            self._parent[item] = self.find(parent)
        return self._parent[item]

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for item in list(self._parent):
            out.setdefault(self.find(item), []).append(item)
        return out


def _safe_json(raw: Any, fallback: Any) -> Any:
    if not isinstance(raw, str) or not raw:
        return fallback
    try:
        return json.loads(raw)
    except ValueError:
        return fallback


def _safe_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def _safe_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) else None


def _payload_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return str(value) if isinstance(value, str) and value else None


def load_dossiers(db_path: Path) -> list[Dossier]:
    uri = f"file:{db_path.resolve()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        dossiers: dict[str, Dossier] = {}
        for row in conn.execute(
            "SELECT piece_uuid, tracked_global_id, created_at, updated_at, stage, "
            "classification_status, classification_channel_zone_center_deg, payload_json "
            "FROM piece_dossiers"
        ):
            payload = _safe_json(row["payload_json"], {})
            piece_uuid = str(row["piece_uuid"])
            dossiers[piece_uuid] = Dossier(
                piece_uuid=piece_uuid,
                tracked_global_id=_safe_int(row["tracked_global_id"]),
                created_at=_safe_float(row["created_at"]),
                updated_at=_safe_float(row["updated_at"]),
                stage=str(row["stage"] or ""),
                classification_status=str(row["classification_status"] or ""),
                zone_center_deg=_safe_float(row["classification_channel_zone_center_deg"]),
                zone_state=_payload_text(payload, "classification_channel_zone_state"),
                part_id=_payload_text(payload, "part_id"),
                color_id=_payload_text(payload, "color_id"),
                part_name=_payload_text(payload, "part_name"),
                preview_jpeg_path=_payload_text(payload, "preview_jpeg_path"),
            )
        for row in conn.execute(
            "SELECT piece_uuid, role, tracked_global_id, first_seen_ts, last_seen_ts, "
            "hit_count, snapshot_path, sector_snapshots_json FROM piece_segments"
        ):
            piece_uuid = str(row["piece_uuid"])
            dossier = dossiers.get(piece_uuid)
            if dossier is None:
                continue
            sectors = _safe_json(row["sector_snapshots_json"], [])
            dossier.segments.append(
                Segment(
                    role=str(row["role"] or ""),
                    tracked_global_id=_safe_int(row["tracked_global_id"]),
                    first_seen_ts=_safe_float(row["first_seen_ts"]),
                    last_seen_ts=_safe_float(row["last_seen_ts"]),
                    hit_count=int(row["hit_count"] or 0),
                    snapshot_path=(
                        str(row["snapshot_path"]) if row["snapshot_path"] else None
                    ),
                    sector_snapshots=sectors if isinstance(sectors, list) else [],
                )
            )
        return sorted(
            dossiers.values(),
            key=lambda d: d.event_ts if d.event_ts is not None else float("inf"),
        )
    finally:
        conn.close()


def resolve_blob_path(path: str | None, *, backend_dir: Path) -> Path | None:
    if not path:
        return None
    raw = Path(path)
    if raw.is_absolute():
        return raw if raw.exists() else None
    candidates = [
        backend_dir / "blob" / raw,
        backend_dir / raw,
        backend_dir.parent.parent / raw,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _dhash(gray: Image.Image) -> int:
    small = gray.resize((9, 8), Image.Resampling.LANCZOS)
    pixels = np.asarray(small, dtype=np.int16)
    bits = pixels[:, 1:] > pixels[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bool(bit))
    return value


def _histogram(rgb: Image.Image) -> np.ndarray:
    small = rgb.resize((96, 96), Image.Resampling.LANCZOS)
    arr = np.asarray(small.convert("RGB"), dtype=np.uint8)
    # Ignore near-white background and near-black label borders when possible.
    mask = ~(
        ((arr[:, :, 0] > 238) & (arr[:, :, 1] > 238) & (arr[:, :, 2] > 238))
        | ((arr[:, :, 0] < 12) & (arr[:, :, 1] < 12) & (arr[:, :, 2] < 12))
    )
    pixels = arr[mask]
    if pixels.size == 0:
        pixels = arr.reshape(-1, 3)
    bins = np.floor_divide(pixels, 32).clip(0, 7)
    indices = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
    hist = np.bincount(indices, minlength=512).astype(np.float64)
    total = float(hist.sum())
    return hist / total if total > 0 else hist


def image_features(path: Path) -> ImageFeatures | None:
    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            return ImageFeatures(
                path=str(path),
                width=rgb.width,
                height=rgb.height,
                dhash=_dhash(rgb.convert("L")),
                histogram=_histogram(rgb),
            )
    except Exception:
        return None


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def image_similarity(a: ImageFeatures | None, b: ImageFeatures | None) -> float | None:
    if a is None or b is None:
        return None
    hist_intersection = float(np.minimum(a.histogram, b.histogram).sum())
    hash_sim = 1.0 - (hamming(a.dhash, b.dhash) / 64.0)
    size_ratio = min(a.width * a.height, b.width * b.height) / max(
        a.width * a.height,
        b.width * b.height,
    )
    return max(0.0, min(1.0, 0.55 * hist_intersection + 0.35 * hash_sim + 0.10 * size_ratio))


def angle_delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(((float(b) - float(a) + 180.0) % 360.0) - 180.0)


def class_relation(a: Dossier, b: Dossier) -> tuple[str, float]:
    a_key = (a.part_id, a.color_id)
    b_key = (b.part_id, b.color_id)
    if a_key[0] and a_key[1] and b_key[0] and b_key[1]:
        return ("match", 1.0) if a_key == b_key else ("conflict", -1.0)
    if a.part_id and b.part_id and a.part_id != b.part_id:
        return "conflict", -1.0
    return "compatible_unknown", 0.55


def score_pair(
    a: Dossier,
    b: Dossier,
    *,
    features: dict[str, ImageFeatures | None],
    max_gap_s: float,
) -> LinkCandidate | None:
    a_ts = a.event_ts
    b_ts = b.event_ts
    if a_ts is None or b_ts is None:
        return None
    gap = float(b_ts) - float(a_ts)
    if gap < 0 or gap > max_gap_s:
        return None
    relation, class_score = class_relation(a, b)
    if relation == "conflict":
        return None
    same_gid = (
        a.tracked_global_id is not None
        and b.tracked_global_id is not None
        and a.tracked_global_id == b.tracked_global_id
    )
    delta = angle_delta(a.zone_center_deg, b.zone_center_deg)
    img_sim = image_similarity(features.get(a.piece_uuid), features.get(b.piece_uuid))
    time_score = math.exp(-gap / max(0.1, max_gap_s / 2.0))
    angle_score = math.exp(-(delta or 45.0) / 22.0)
    image_score = img_sim if img_sim is not None else 0.5
    gid_score = 1.0 if same_gid else 0.0
    superseded_score = 1.0 if a.zone_state in {"superseded", "lost"} else 0.2
    confidence = (
        0.24 * time_score
        + 0.20 * gid_score
        + 0.19 * class_score
        + 0.17 * image_score
        + 0.13 * angle_score
        + 0.07 * superseded_score
    )
    reasons: list[str] = []
    if same_gid:
        reasons.append("same_tracked_global_id")
    if relation == "match":
        reasons.append("same_part_color")
    elif relation == "compatible_unknown":
        reasons.append("class_unknown_but_compatible")
    if delta is not None and delta <= 8.0:
        reasons.append("near_angle")
    if img_sim is not None and img_sim >= 0.72:
        reasons.append("similar_crop")
    if a.zone_state in {"superseded", "lost"}:
        reasons.append(f"source_{a.zone_state}")
    link_relation = "track_split"
    if _has_c3_role(a) and _has_c4_role(b):
        link_relation = "cross_channel"
        confidence += 0.08
        reasons.append("c3_to_c4_roles")
    return LinkCandidate(
        source_uuid=a.piece_uuid,
        target_uuid=b.piece_uuid,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        relation=link_relation,
        time_gap_s=round(gap, 4),
        angle_delta_deg=round(delta, 4) if delta is not None else None,
        image_similarity=round(img_sim, 4) if img_sim is not None else None,
        class_relation=relation,
        reasons=reasons,
    )


def _has_c3_role(dossier: Dossier) -> bool:
    roles = {s.role for s in dossier.segments}
    return bool(roles & {"c3", "c3_feed", "third_channel", "c_channel_3"})


def _has_c4_role(dossier: Dossier) -> bool:
    roles = {s.role for s in dossier.segments}
    return bool(roles & {"c4", "c4_feed", "carousel", "classification_channel"})


def find_candidates(
    dossiers: list[Dossier],
    *,
    features: dict[str, ImageFeatures | None],
    max_gap_s: float,
    min_confidence: float,
) -> list[LinkCandidate]:
    out: list[LinkCandidate] = []
    ordered = [d for d in dossiers if d.event_ts is not None]
    for idx, source in enumerate(ordered):
        for target in ordered[idx + 1 :]:
            source_ts = source.event_ts
            target_ts = target.event_ts
            if source_ts is None or target_ts is None:
                continue
            if target_ts - source_ts > max_gap_s:
                break
            candidate = score_pair(
                source,
                target,
                features=features,
                max_gap_s=max_gap_s,
            )
            if candidate is not None and candidate.confidence >= min_confidence:
                out.append(candidate)
    return sorted(out, key=lambda c: c.confidence, reverse=True)


def build_groups(candidates: list[LinkCandidate], *, min_confidence: float) -> list[list[str]]:
    union = UnionFind()
    for candidate in candidates:
        if candidate.confidence >= min_confidence:
            union.union(candidate.source_uuid, candidate.target_uuid)
    groups = [sorted(items) for items in union.groups().values() if len(items) > 1]
    return sorted(groups, key=len, reverse=True)


def _thumb(path: Path | None, size: tuple[int, int] = (150, 150)) -> Image.Image:
    if path is None or not path.exists():
        img = Image.new("RGB", size, (245, 243, 238))
        draw = ImageDraw.Draw(img)
        draw.text((16, 64), "missing", fill=(90, 90, 90))
        return img
    try:
        with Image.open(path) as raw:
            img = raw.convert("RGB")
            img.thumbnail(size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", size, (245, 243, 238))
            x = (size[0] - img.width) // 2
            y = (size[1] - img.height) // 2
            canvas.paste(img, (x, y))
            return canvas
    except Exception:
        return _thumb(None, size=size)


def write_contact_sheet(
    group: list[str],
    *,
    dossiers_by_uuid: dict[str, Dossier],
    backend_dir: Path,
    output_path: Path,
) -> None:
    ordered = sorted(
        (dossiers_by_uuid[u] for u in group),
        key=lambda d: d.event_ts if d.event_ts is not None else float("inf"),
    )
    cell_w = 190
    cell_h = 220
    cols = min(6, max(1, len(ordered)))
    rows = math.ceil(len(ordered) / cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (238, 236, 231))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for idx, dossier in enumerate(ordered):
        x = (idx % cols) * cell_w
        y = (idx // cols) * cell_h
        resolved = resolve_blob_path(dossier.best_image_path, backend_dir=backend_dir)
        sheet.paste(_thumb(resolved), (x + 20, y + 8))
        lines = [
            dossier.piece_uuid[:12],
            f"gid={dossier.tracked_global_id} t={dossier.event_ts:.2f}"
            if dossier.event_ts is not None
            else f"gid={dossier.tracked_global_id}",
            f"{dossier.part_id or '?'} / {dossier.color_id or '?'}",
            f"{dossier.zone_state or '?'} {dossier.zone_center_deg:.1f}"
            if dossier.zone_center_deg is not None
            else dossier.zone_state or "?",
        ]
        for line_no, line in enumerate(lines):
            draw.text((x + 8, y + 164 + line_no * 13), line[:30], fill=(30, 30, 30), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def summarize_groups(
    groups: list[list[str]],
    *,
    dossiers_by_uuid: dict[str, Dossier],
    candidates: list[LinkCandidate],
) -> list[dict[str, Any]]:
    candidate_lookup = {(c.source_uuid, c.target_uuid): c for c in candidates}
    out: list[dict[str, Any]] = []
    for idx, group in enumerate(groups):
        ordered = sorted(
            (dossiers_by_uuid[u] for u in group),
            key=lambda d: d.event_ts if d.event_ts is not None else float("inf"),
        )
        links = []
        for a, b in zip(ordered, ordered[1:]):
            link = candidate_lookup.get((a.piece_uuid, b.piece_uuid))
            if link is not None:
                links.append(asdict(link))
        out.append(
            {
                "group_index": idx,
                "canonical_piece_uuid": ordered[0].piece_uuid,
                "piece_uuids": [d.piece_uuid for d in ordered],
                "count": len(ordered),
                "tracked_global_ids": sorted(
                    {
                        d.tracked_global_id
                        for d in ordered
                        if d.tracked_global_id is not None
                    }
                ),
                "part_ids": sorted({d.part_id for d in ordered if d.part_id}),
                "color_ids": sorted({d.color_id for d in ordered if d.color_id}),
                "start_ts": ordered[0].event_ts,
                "end_ts": ordered[-1].event_ts,
                "links": links,
            }
        )
    return out


def write_markdown(
    report: dict[str, Any],
    *,
    output_path: Path,
) -> None:
    lines = [
        "# Dossier Link Audit",
        "",
        f"- dossiers: {report['summary']['dossier_count']}",
        f"- segments: {report['summary']['segment_count']}",
        f"- candidates: {report['summary']['candidate_count']}",
        f"- groups: {report['summary']['group_count']}",
        f"- cross-channel candidate count: {report['summary']['cross_channel_candidate_count']}",
        "",
        "## Top Groups",
        "",
    ]
    for group in report["groups"][:10]:
        lines.append(
            f"### Group {group['group_index']} · {group['count']} dossiers · "
            f"canonical `{group['canonical_piece_uuid']}`"
        )
        lines.append(
            f"- gids: {group['tracked_global_ids']} · parts: {group['part_ids']} · colors: {group['color_ids']}"
        )
        lines.append(f"- contact sheet: `{group.get('contact_sheet', '')}`")
        if group["links"]:
            confidences = [link["confidence"] for link in group["links"]]
            lines.append(
                f"- link confidence: min {min(confidences):.3f}, max {max(confidences):.3f}"
            )
        lines.append("")
    if not report["groups"]:
        lines.append("No groups above threshold.")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def run_audit(
    *,
    db_path: Path,
    backend_dir: Path,
    output_dir: Path,
    max_gap_s: float,
    min_confidence: float,
    group_min_confidence: float,
    max_sheets: int,
) -> dict[str, Any]:
    dossiers = load_dossiers(db_path)
    dossiers_by_uuid = {d.piece_uuid: d for d in dossiers}
    features: dict[str, ImageFeatures | None] = {}
    for dossier in dossiers:
        resolved = resolve_blob_path(dossier.best_image_path, backend_dir=backend_dir)
        features[dossier.piece_uuid] = image_features(resolved) if resolved else None
    candidates = find_candidates(
        dossiers,
        features=features,
        max_gap_s=max_gap_s,
        min_confidence=min_confidence,
    )
    groups = build_groups(candidates, min_confidence=group_min_confidence)
    group_summaries = summarize_groups(
        groups,
        dossiers_by_uuid=dossiers_by_uuid,
        candidates=candidates,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for group in group_summaries[:max_sheets]:
        sheet_path = output_dir / f"group_{group['group_index']:02d}.jpg"
        write_contact_sheet(
            group["piece_uuids"],
            dossiers_by_uuid=dossiers_by_uuid,
            backend_dir=backend_dir,
            output_path=sheet_path,
        )
        group["contact_sheet"] = str(sheet_path)
    report = {
        "summary": {
            "db_path": str(db_path),
            "dossier_count": len(dossiers),
            "segment_count": sum(len(d.segments) for d in dossiers),
            "candidate_count": len(candidates),
            "group_count": len(group_summaries),
            "cross_channel_candidate_count": sum(
                1 for c in candidates if c.relation == "cross_channel"
            ),
            "roles": sorted({s.role for d in dossiers for s in d.segments}),
            "max_gap_s": max_gap_s,
            "min_confidence": min_confidence,
            "group_min_confidence": group_min_confidence,
        },
        "top_candidates": [asdict(c) for c in candidates[:50]],
        "groups": group_summaries,
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_markdown(report, output_path=output_dir / "report.md")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-gap-s", type=float, default=8.0)
    parser.add_argument("--min-confidence", type=float, default=0.66)
    parser.add_argument("--group-min-confidence", type=float, default=0.72)
    parser.add_argument("--max-sheets", type=int, default=8)
    args = parser.parse_args()
    backend_dir = Path(__file__).resolve().parents[1]
    repo_root = backend_dir.parents[2]
    output_dir = args.output if args.output.is_absolute() else repo_root / args.output
    report = run_audit(
        db_path=args.db,
        backend_dir=backend_dir,
        output_dir=output_dir,
        max_gap_s=args.max_gap_s,
        min_confidence=args.min_confidence,
        group_min_confidence=args.group_min_confidence,
        max_sheets=args.max_sheets,
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
