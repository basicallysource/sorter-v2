import type {
	ClassificationAttempt,
	ClassificationAttemptStrategy,
	RecognitionImage
} from '$lib/api/events';
import type { PieceDetailEnvelope } from '$lib/pieces';

// One renderable crop, whether it came from the in-memory KnownObject lookup
// (base64 payload) or the on-disk piece-image store (file URL). Disk images
// survive reboots; memory ones additionally carry the raw base64 needed by
// the reclassify panel.
export type DisplayImage = {
	src: string;
	source: string;
	used: boolean;
	excluded_from_result: boolean;
	ts?: number | null;
	score?: number | null;
	channel?: number | null;
	created_at?: number | null;
	b64?: string | null;
};

export type ImageState = {
	status: 'loading' | 'ok' | 'missing';
	// Where the crops were hydrated from. Memory has the full KnownObject
	// (attempts, stock photo); disk is the durable fallback after restarts.
	origin?: 'memory' | 'disk';
	images: DisplayImage[];
	strategy?: ClassificationAttemptStrategy | null;
	attempts?: ClassificationAttempt[];
	// Creation time of the owning KnownObject (epoch seconds) — the reference
	// each pic is aged against.
	createdAt?: number | null;
	// Brickognize stock photo of the identified part (remote URL), shown on the
	// right of the contact sheet next to the crops we actually captured.
	stockUrl?: string | null;
};

// Mirrors a backend piece_image_store.listPieceImages row.
export type DiskImage = {
	id: number;
	seq: number;
	source: string | null;
	channel: number | null;
	ts: number | null;
	created_at: number | null;
	sharpness: number | null;
	available_locally: boolean;
	synced: boolean;
	used: boolean;
	excluded_from_result: boolean;
	score: number | null;
};

export function memoryToDisplay(img: RecognitionImage): DisplayImage {
	return {
		src: `data:image/jpeg;base64,${img.image}`,
		source: img.source,
		used: img.used ?? false,
		excluded_from_result: img.excluded_from_result ?? false,
		ts: img.ts,
		score: img.score,
		channel: img.channel,
		created_at: img.created_at,
		b64: img.image
	};
}

export function diskToDisplay(base: string, uuid: string, img: DiskImage): DisplayImage {
	return {
		src: `${base}/api/pieces/${encodeURIComponent(uuid)}/images/${img.id}`,
		source: img.source ?? 'c4_burst',
		used: img.used,
		excluded_from_result: img.excluded_from_result,
		ts: img.ts,
		score: img.score,
		channel: img.channel,
		created_at: img.created_at
	};
}

export async function fetchDiskImages(base: string, uuid: string): Promise<DiskImage[]> {
	const res = await fetch(`${base}/api/pieces/${encodeURIComponent(uuid)}/images`);
	if (!res.ok) return [];
	const json = await res.json();
	const rows: DiskImage[] = Array.isArray(json?.images) ? json.images : [];
	return rows.filter((r) => r.available_locally);
}

// Crops hydrate through the tiered detail endpoint: a memory hit carries the
// richest payload (attempts strip, stock photo, reclassify b64) but only spans
// the current backend process; the on-disk piece-image store covers everything
// since it was enabled — including pieces from before the last restart. Disk
// images are plain file URLs served immutable, so the browser caches them.
export async function fetchPieceImageState(
	base: string,
	uuid: string,
	seen_at: number | null
): Promise<ImageState> {
	let stock_url: string | null = null;
	try {
		const res = await fetch(`${base}/api/pieces/${encodeURIComponent(uuid)}`);
		if (res.ok) {
			const env = (await res.json()) as PieceDetailEnvelope;
			stock_url = env.summary?.preview_url ?? null;
			if (env.detail_available && env.detail) {
				return {
					status: 'ok',
					origin: 'memory',
					images: (env.detail.recognition_image_set ?? []).map(memoryToDisplay),
					strategy: env.detail.classification_strategy ?? null,
					attempts: env.detail.classification_attempts ?? [],
					createdAt: env.detail.created_at ?? null,
					stockUrl: env.detail.brickognize_preview_url ?? stock_url
				};
			}
		}
	} catch {
		// fall through to the disk store
	}
	try {
		const available = await fetchDiskImages(base, uuid);
		if (available.length > 0) {
			return {
				status: 'ok',
				origin: 'disk',
				images: available.map((r) => diskToDisplay(base, uuid, r)),
				createdAt: seen_at,
				stockUrl: stock_url
			};
		}
	} catch {
		// ignore
	}
	if (stock_url) {
		return { status: 'ok', origin: 'disk', images: [], createdAt: seen_at, stockUrl: stock_url };
	}
	return { status: 'missing', images: [] };
}
