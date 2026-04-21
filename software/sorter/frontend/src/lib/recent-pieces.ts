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
	return Boolean(obj.thumbnail || obj.top_image || obj.bottom_image || obj.drop_snapshot);
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
	if (!hasC4Evidence(obj) && obj.stage !== 'distributed' && !obj.distributed_at) return false;
	if (obj.stage !== 'created') return true;
	if (hasRecentPieceIdentity(obj)) return true;
	if (obj.classification_status !== 'pending') return true;
	return Boolean(
		hasC4Evidence(obj) && (obj.part_id || hasRecentPiecePreview(obj) || obj.classification_status)
	);
}

export function recentPhysicalKey(obj: KnownObjectData): string {
	if (obj.tracked_global_id !== null && obj.tracked_global_id !== undefined) {
		return `gid:${obj.tracked_global_id}`;
	}
	const preview = obj.thumbnail ?? obj.top_image ?? obj.bottom_image ?? obj.drop_snapshot;
	if (preview) return `preview:${preview.slice(0, 96)}`;
	const c4Ts =
		obj.carousel_detected_confirmed_at ??
		obj.first_carousel_seen_ts ??
		obj.classified_at ??
		obj.distributed_at ??
		obj.updated_at ??
		obj.created_at ??
		0;
	const angle =
		typeof obj.classification_channel_zone_center_deg === 'number'
			? Math.round(obj.classification_channel_zone_center_deg)
			: 'na';
	return `c4:${Math.round(c4Ts * 4)}:${angle}:${obj.part_id ?? obj.classification_status ?? 'pending'}`;
}

export function dataImageUrl(payload: string | null | undefined): string | null {
	return payload ? `data:image/jpeg;base64,${payload}` : null;
}

export function capturedCropUrl(obj: KnownObjectData): string | null {
	return (
		dataImageUrl(obj.top_image) ??
		dataImageUrl(obj.bottom_image) ??
		dataImageUrl(obj.thumbnail) ??
		dataImageUrl(obj.drop_snapshot)
	);
}
