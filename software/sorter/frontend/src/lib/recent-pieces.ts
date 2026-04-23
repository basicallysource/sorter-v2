import type { KnownObjectData } from '$lib/api/events';

export type LifecyclePhase = 'tracking' | 'capturing' | 'classified' | 'distributed';

export function hasC4Evidence(obj: KnownObjectData): boolean {
	return Boolean(
		obj.carousel_detected_confirmed_at ||
			obj.first_carousel_seen_ts ||
			obj.carousel_snapping_started_at ||
			obj.carousel_snapping_completed_at ||
			obj.classified_at ||
			typeof obj.classification_channel_zone_center_deg === 'number' ||
			obj.classification_channel_zone_state
	);
}

export function hasRecentPiecePreview(obj: KnownObjectData): boolean {
	return Boolean(
		obj.thumbnail ||
			obj.top_image ||
			obj.bottom_image ||
			obj.preview_jpeg_path ||
			obj.drop_snapshot
	);
}

export function hasRecentPieceIdentity(obj: KnownObjectData): boolean {
	return (
		(obj.tracked_global_id !== null && obj.tracked_global_id !== undefined) ||
		Boolean(
			obj.first_carousel_seen_ts || obj.carousel_detected_confirmed_at
		)
	);
}

export function hasCapturingEvidence(obj: KnownObjectData): boolean {
	return Boolean(
		obj.carousel_snapping_started_at ||
		obj.carousel_snapping_completed_at ||
		obj.classified_at ||
		obj.part_id ||
		hasRecentPiecePreview(obj)
	);
}

export function lifecyclePhase(obj: KnownObjectData): LifecyclePhase {
	if (obj.stage === 'distributed' || obj.distributed_at) return 'distributed';
	if (
		obj.classification_status === 'classified' ||
		obj.classification_status === 'unknown' ||
		obj.classification_status === 'not_found' ||
		obj.classification_status === 'multi_drop_fail' ||
		obj.classified_at
	) {
		return 'classified';
	}
	if (hasCapturingEvidence(obj)) return 'capturing';
	if (hasRecentPieceIdentity(obj)) return 'tracking';
	return 'capturing';
}

export function shouldShowInRecentPieces(obj: KnownObjectData): boolean {
	if (obj.classification_channel_zone_state === 'lost' && obj.stage !== 'distributed') return false;
	if (
		lifecyclePhase(obj) === 'classified' &&
		!obj.distributed_at &&
		obj.classification_channel_zone_state !== 'active'
	) {
		return false;
	}
	if (!hasC4Evidence(obj) && obj.stage !== 'distributed' && !obj.distributed_at) return false;
	if (obj.stage !== 'created') return true;
	if (hasRecentPieceIdentity(obj)) return true;
	if (obj.classification_status !== 'pending') return true;
	return Boolean(
		hasC4Evidence(obj) && (obj.part_id || hasRecentPiecePreview(obj) || obj.classification_status)
	);
}

// Stable identity for a physical piece. The tracker global id is the physical
// identity across dossier splits; uuid is only the fallback for legacy rows
// without a tracked id.
export function recentPhysicalKey(obj: KnownObjectData): string {
	// Kept for back-compat: always returns *some* string. Prefer
	// `recentPhysicalKeyOrNull` in new code so callers can drop items without
	// a stable identity instead of inventing a random key.
	return recentPhysicalKeyOrNull(obj) ?? `fallback:${obj.uuid ?? Math.random()}`;
}

export function recentPhysicalKeyOrNull(obj: KnownObjectData): string | null {
	if (obj?.tracked_global_id !== null && obj?.tracked_global_id !== undefined) {
		return `gid:${obj.tracked_global_id}`;
	}
	if (obj?.uuid) return `uuid:${obj.uuid}`;
	return null;
}

export function dataImageUrl(payload: string | null | undefined): string | null {
	return payload ? `data:image/jpeg;base64,${payload}` : null;
}

export function capturedCropUrl(obj: KnownObjectData, base?: string | null): string | null {
	return (
		dataImageUrl(obj.top_image) ??
		dataImageUrl(obj.bottom_image) ??
		dataImageUrl(obj.thumbnail) ??
		(base ? pieceCropUrl(obj.preview_jpeg_path, base) : null) ??
		dataImageUrl(obj.drop_snapshot)
	);
}

// Maps a DB-stored relative crop path
// `piece_crops/<uuid>/seg<seq>/<kind>_<idx>.jpg` onto the API URL served by
// `/api/piece-crops/{uuid}/seg{seq}/{kind}/{idx}.jpg`. Returns null on any
// malformed input so callers fall back to a b64 payload or hide the tile.
export function pieceCropUrl(
	disk_path: string | null | undefined,
	base: string
): string | null {
	if (typeof disk_path !== 'string' || disk_path.length === 0) return null;
	const stripped = disk_path.replace(/^piece_crops\//, '');
	const m = stripped.match(/^([^/]+)\/seg(\d+)\/(wedge|piece|snapshot|matrix)_(\d+)\.jpg$/);
	if (!m) return null;
	const [, piece_uuid, seq, kind, idx] = m;
	return `${base}/api/piece-crops/${piece_uuid}/seg${seq}/${kind}/${Number(idx)}.jpg`;
}
