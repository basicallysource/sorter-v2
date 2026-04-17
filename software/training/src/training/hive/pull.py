"""Pull reviewed samples from Hive into ``datasets/<zone>/raw/``.

Uses the stored API key (``train auth login``). Requires the admin-side
``/api/samples`` endpoints, which accept the same ``hv_*`` Bearer token that
unlocks the admin model-publishing path.

Output layout:

    datasets/<zone>/raw/
      manifest.json                # one entry per sample, list-of-dicts
      <sample_id>/
        image.jpg                  # primary cropped image
        full_frame.jpg             # optional if the sample has one
        metadata.json              # sample_payload + extra_metadata copy
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

from training import DATASETS_DIR


_PAGE_SIZE = 100


# Maps a training-zone identifier to the Hive source_role values that belong to it.
# Extend this when new roles show up in Hive.
ZONE_SOURCE_ROLES: dict[str, tuple[str, ...]] = {
    "classification_chamber": ("classification_chamber",),
    "c_channel": ("c_channel_2", "c_channel_3"),
    "c_channel_2": ("c_channel_2",),
    "c_channel_3": ("c_channel_3",),
    "carousel": ("carousel",),
}


def _request(session: requests.Session, url: str, **kwargs: Any) -> Any:
    resp = session.get(url, **kwargs)
    if not resp.ok:
        raise SystemExit(f"Hive request failed {resp.status_code}: {resp.text[:200]}")
    return resp


def _resolve_token(hive_url: str, cli_token: str | None) -> str:
    from training import auth as auth_store

    token = cli_token or auth_store.get_token(hive_url)
    if not token:
        raise SystemExit(
            f"No API key stored for {hive_url}. "
            f"Run `train auth login --hive-url {hive_url}` first."
        )
    return token


def _iter_samples(
    session: requests.Session,
    hive_url: str,
    *,
    source_role: str,
    review_status: str | None,
):
    page = 1
    while True:
        params: dict[str, Any] = {
            "page": page,
            "page_size": _PAGE_SIZE,
            "source_role": source_role,
        }
        if review_status:
            params["review_status"] = review_status
        resp = _request(session, f"{hive_url}/api/samples", params=params)
        payload = resp.json()
        items = payload.get("items") or []
        if not items:
            return
        for item in items:
            yield item
        if page >= int(payload.get("pages") or 1):
            return
        page += 1


def _download_asset(
    session: requests.Session,
    url: str,
    dest: Path,
) -> bool:
    resp = session.get(url, stream=True)
    if resp.status_code == 404:
        return False
    if not resp.ok:
        raise SystemExit(f"Asset download failed {resp.status_code}: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(1024 * 256):
            if chunk:
                fh.write(chunk)
    return True


def run(
    *,
    hive_url: str,
    zone: str,
    source_role: str | None = None,
    review_status: str | None = "accepted",
    token: str | None = None,
    output_dir: Path | None = None,
) -> int:
    """Entry called from the CLI."""
    hive_url = hive_url.rstrip("/")
    token = _resolve_token(hive_url, token)

    if source_role:
        roles: tuple[str, ...] = (source_role,)
    else:
        roles = ZONE_SOURCE_ROLES.get(zone, (zone,))

    target_dir = (output_dir or (DATASETS_DIR / zone / "raw")).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    manifest: list[dict[str, Any]] = []
    count = 0
    seen_ids: set[str] = set()
    for role in roles:
        for item in _iter_samples(
            session,
            hive_url,
            source_role=role,
            review_status=review_status,
        ):
            sample_id = item["id"]
            if sample_id in seen_ids:
                continue
            seen_ids.add(sample_id)

            sample_dir = target_dir / sample_id
            sample_dir.mkdir(parents=True, exist_ok=True)

            image_path = sample_dir / "image.jpg"
            if not image_path.exists():
                _download_asset(
                    session,
                    f"{hive_url}/api/samples/{sample_id}/assets/image",
                    image_path,
                )
            full_frame_path = sample_dir / "full_frame.jpg"
            if not full_frame_path.exists():
                _download_asset(
                    session,
                    f"{hive_url}/api/samples/{sample_id}/assets/full-frame",
                    full_frame_path,
                )

            detail_resp = _request(session, f"{hive_url}/api/samples/{sample_id}")
            detail = detail_resp.json()
            (sample_dir / "metadata.json").write_text(json.dumps(detail, indent=2, sort_keys=True))

            manifest.append(
                {
                    "id": sample_id,
                    "local_sample_id": item.get("local_sample_id"),
                    "source_role": item.get("source_role"),
                    "capture_reason": item.get("capture_reason"),
                    "review_status": item.get("review_status"),
                    "detection_count": item.get("detection_count"),
                    "detection_score": item.get("detection_score"),
                    "detection_bboxes": item.get("detection_bboxes"),
                    "image_width": item.get("image_width"),
                    "image_height": item.get("image_height"),
                    "uploaded_at": item.get("uploaded_at"),
                    "captured_at": item.get("captured_at"),
                    "has_full_frame": detail.get("has_full_frame", False),
                    "has_overlay": detail.get("has_overlay", False),
                    "dir": str(sample_dir.relative_to(target_dir.parent)),
                }
            )
            count += 1
            if count % 10 == 0:
                print(f"  pulled {count} samples…", file=sys.stderr)

    (target_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(
        f"Pulled {count} samples from {hive_url} zone={zone} roles={list(roles)} "
        f"status={review_status or '(any)'} → {target_dir}",
        file=sys.stderr,
    )
    return 0
