import {
	diskToDisplay,
	fetchDiskImages,
	fetchDiskLinkImages,
	memoryToDisplay,
	type DisplayImage
} from '$lib/components/records/piece-images';
import {
	findLegoColor,
	type PieceDetailEnvelope,
	type PiecePrediction,
	type PieceSummary,
	type PredictionImage
} from '$lib/pieces';

// What the layouts on /layouts draw a piece from: one shape, so every layout
// shows the same piece the same way and they differ only in arrangement.

export type Channel = 'C4' | 'C3' | 'C2';

// One picture of a piece.
export type Shot = {
	key: string;
	src: string;
	channel: Channel;
	// It produced the applied result.
	used: boolean;
	ts: number | null;
	// Under the enlarged picture.
	label: string;
};

export type PieceView = {
	uuid: string;
	summary: PieceSummary;
	name: string;
	partId: string | null;
	// Brickognize's picture of the part.
	reference: string | null;
	color: { id: number; name: string; hex: string | null } | null;
	// How sure the part is, and the color, as whole percents.
	partPct: number | null;
	colorPct: number | null;
	partBy: string | null;
	colorBy: string | null;
	value: string | null;
	bin: string | null;
	// Short ("4:58 PM") and with seconds.
	when: string | null;
	whenExact: string | null;
	// Every picture, the classification channel's first, then C3, then C2.
	shots: Shot[];
	predictions: PiecePrediction[];
	// The picture a prediction saw, when the page still has it.
	saw: (image: PredictionImage) => Shot | null;
};

export const CHANNELS: Channel[] = ['C4', 'C3', 'C2'];
// The order a piece rides through the machine.
export const RIDE: Channel[] = ['C2', 'C3', 'C4'];

export const CHANNEL_NAMES: Record<Channel, string> = {
	C2: 'Second feeder',
	C3: 'Third feeder',
	C4: 'Classification'
};

const PROVIDERS: Record<string, string> = {
	brickognize: 'Brickognize',
	hive_basically: 'basically color model'
};

export function shotsOf(piece: PieceView, channel: Channel): Shot[] {
	return piece.shots.filter((shot) => shot.channel === channel);
}

// The picture that stands for the piece: the first one that produced the
// result, else its first picture.
export function bestShot(piece: PieceView): Shot | null {
	return piece.shots.find((shot) => shot.used) ?? piece.shots[0] ?? null;
}

export function confidenceClass(pct: number | null): string {
	if (pct == null) return 'text-ink-muted';
	if (pct >= 90) return 'text-success-ink';
	if (pct >= 80) return 'text-warning-ink';
	if (pct >= 60) return 'text-warning-ink/70';
	return 'text-danger-ink';
}

function clock(ts: number | null | undefined, seconds: boolean): string | null {
	if (ts == null) return null;
	return new Date(ts * 1000).toLocaleTimeString(undefined, {
		hour: 'numeric',
		minute: '2-digit',
		...(seconds ? { second: '2-digit' } : {})
	});
}

export function shotTime(shot: Shot | null | undefined): string | null {
	return clock(shot?.ts, true);
}

function channelOf(img: DisplayImage): Channel {
	if (img.source === 'c4_burst') return 'C4';
	return img.channel === 2 ? 'C2' : img.channel === 3 ? 'C3' : 'C4';
}

function percent(v: number | null | undefined): number | null {
	return typeof v === 'number' && Number.isFinite(v) ? Math.round(v * 100) : null;
}

function toShots(images: DisplayImage[]): Shot[] {
	const rank = { C4: 0, C3: 1, C2: 2 };
	return images
		.map((img, i) => ({ img, i, channel: channelOf(img) }))
		.sort(
			(a, b) => rank[a.channel] - rank[b.channel] || (a.img.ts ?? 0) - (b.img.ts ?? 0) || a.i - b.i
		)
		.map(({ img, i, channel }) => ({
			key: String(i),
			src: img.src,
			channel,
			used: img.used,
			ts: img.ts ?? null,
			label: [
				channel,
				img.source === 'link_match' && typeof img.score === 'number'
					? `linked, ${(img.score * 100).toFixed(1)}% match`
					: null,
				clock(img.ts, true),
				typeof img.sharpness === 'number' && Number.isFinite(img.sharpness)
					? `sharpness ${Math.round(img.sharpness)}`
					: null,
				img.used ? 'produced the result' : null
			]
				.filter(Boolean)
				.join(' · ')
		}));
}

async function loadPiece(base: string, uuid: string): Promise<PieceView | null> {
	const res = await fetch(`${base}/api/pieces/${encodeURIComponent(uuid)}`);
	if (!res.ok) return null;
	const env = (await res.json()) as PieceDetailEnvelope;
	const summary = env.summary;
	let burst: DisplayImage[];
	let linked: DisplayImage[];
	if (env.detail_available && env.detail) {
		burst = (env.detail.recognition_image_set ?? []).map(memoryToDisplay);
		linked = (env.detail.link_match_image_set ?? []).map(memoryToDisplay);
	} else {
		burst = (await fetchDiskImages(base, uuid).catch(() => [])).map((row) =>
			diskToDisplay(base, uuid, row)
		);
		linked = await fetchDiskLinkImages(base, uuid);
	}
	const shots = toShots([...burst, ...linked]);
	// A prediction names its pictures by set and place: burst 2, link 0.
	const bySet = new Map<string, Shot>();
	const place = (set: string, images: DisplayImage[]) =>
		images.forEach((img, i) => {
			const shot = shots.find((s) => s.src === img.src);
			if (shot) bySet.set(`${set}:${img.seq ?? i}`, shot);
		});
	place('burst', burst);
	place('link', linked);

	const color = findLegoColor(summary.color_id, summary.color_name);
	const value = summary.est_value;
	return {
		uuid,
		summary,
		name: summary.part_name ?? summary.part_id ?? `Piece ${uuid.slice(0, 8)}`,
		partId: summary.part_name ? (summary.part_id ?? null) : null,
		reference: env.detail?.brickognize_preview_url ?? summary.preview_url ?? null,
		color:
			color && /^\d+$/.test(color.id)
				? { id: Number(color.id), name: color.name, hex: color.hex }
				: null,
		partPct: percent(summary.confidence),
		colorPct: percent(summary.color_confidence),
		partBy: summary.mold_provider ? (PROVIDERS[summary.mold_provider] ?? null) : null,
		colorBy: summary.color_provider ? (PROVIDERS[summary.color_provider] ?? null) : null,
		value:
			typeof value === 'number' && value > 0
				? `$${value >= 0.01 ? value.toFixed(2) : value.toFixed(3)}`
				: null,
		bin: summary.bin
			? `L${summary.bin.x + 1} · S${summary.bin.y + 1} · B${summary.bin.z + 1}`
			: null,
		when: clock(summary.seen_at, false),
		whenExact: clock(summary.seen_at, true),
		shots,
		predictions: env.predictions ?? [],
		saw: (image) => bySet.get(`${image.set === 'link' ? 'link' : 'burst'}:${image.seq}`) ?? null
	};
}

// The newest identified pieces, one after another: the machine is sorting
// while this page is looked at.
export async function loadPieces(base: string, count: number): Promise<PieceView[]> {
	const res = await fetch(`${base}/api/pieces?limit=${count * 3}`);
	if (!res.ok) throw new Error(`pieces ${res.status}`);
	const listed = ((await res.json()).items ?? []) as PieceSummary[];
	const out: PieceView[] = [];
	for (const summary of listed) {
		if (out.length >= count) break;
		if (!summary.part_id || !summary.has_images) continue;
		const piece = await loadPiece(base, summary.uuid).catch(() => null);
		if (piece && piece.shots.length > 0) out.push(piece);
	}
	return out;
}
