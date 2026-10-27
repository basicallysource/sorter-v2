// Training data: runs that label every piece the machine sees with the colors
// being fed. The calls to the machine's /api/training routes, and the small
// helpers the settings pages and the dashboard share.

import { categoryLabel } from '$lib/components/bins/pieces';

export type TrainingMode = 'color';
export type PieceFilter = 'all' | 'disagree' | 'excluded';

// A color by its BrickLink id (a string of digits); name and rgb are null when
// the machine's palette does not know it.
export type TrainingColor = { id: string; name: string | null; rgb: string | null };

// A stretch of a run with one set of colors; choosing other colors mid-run
// ends one segment and opens the next.
export type TrainingSegment = {
	id: string;
	color_ids: string[];
	colors: TrainingColor[];
	started_at: number;
	ended_at: number | null;
	pieces: number;
};

export type TrainingRun = {
	id: string;
	mode: TrainingMode;
	// Every color its segments used, in order.
	color_ids: string[];
	colors: TrainingColor[];
	// Oldest first.
	segments: TrainingSegment[];
	started_at: number;
	ended_at: number | null;
	collecting: boolean;
	excluded: boolean;
	pieces: number;
	labeled: number;
	excluded_pieces: number;
};

// A bin by its 0-based indexes, as GET /api/bins/layout gives them.
export type TrainingBin = { layer: number; section: number; bin: number };

export type TrainingConfig = {
	enabled: boolean;
	mode: TrainingMode;
	color_ids: string[];
	colors: TrainingColor[];
	// Every piece goes to this bin while training mode is on; null routes by
	// the sorting profile.
	bin: TrainingBin | null;
};

export type TrainingState = {
	config: TrainingConfig;
	current_run: TrainingRun | null;
	// Newest first.
	runs: TrainingRun[];
};

export type TrainingPiece = {
	uuid: string;
	run_id: string;
	segment_id: string | null;
	seen_at: number;
	part_id: string | null;
	part_name: string | null;
	// The machine's own call, and the operator's correction of it.
	color_id: string | null;
	color_name: string | null;
	color_corrected_id: string | null;
	// The run's label.
	training_color_id: string | null;
	training_color_name: string | null;
	training_label_source: 'run' | 'prediction' | 'nearest' | null;
	training_excluded: boolean;
	image_id: number | null;
};

export type RunPieces = { run: TrainingRun; pieces: TrainingPiece[]; total: number };

export const PAGE_SIZE = 200;

// The reason a request failed: the backend's `detail` when it gave one.
function reason(body: unknown, status: number): string {
	const detail = (body as { detail?: unknown } | null)?.detail;
	if (typeof detail === 'string' && detail) return detail;
	if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg;
	return `The machine answered ${status}.`;
}

async function call<T>(base: string, path: string, method = 'GET', body?: unknown): Promise<T> {
	const res = await fetch(`${base}${path}`, {
		method,
		headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	const data = await res.json().catch(() => null);
	if (!res.ok) throw new Error(reason(data, res.status));
	return data as T;
}

export function getTraining(base: string): Promise<TrainingState> {
	return call(base, '/api/training');
}

export function saveTrainingConfig(
	base: string,
	change: {
		enabled?: boolean;
		mode?: TrainingMode;
		color_ids?: string[];
		bin?: TrainingBin | null;
	}
): Promise<TrainingState> {
	return call(base, '/api/training/config', 'POST', change);
}

// Starts a run with the chosen colors.
export function startRun(base: string): Promise<TrainingState> {
	return call(base, '/api/training/runs', 'POST');
}

export function endRun(base: string, runId: string): Promise<TrainingState> {
	return call(base, `/api/training/runs/${encodeURIComponent(runId)}/end`, 'POST');
}

export function getRunPieces(
	base: string,
	runId: string,
	{
		limit = PAGE_SIZE,
		offset = 0,
		filter = 'all'
	}: { limit?: number; offset?: number; filter?: PieceFilter } = {}
): Promise<RunPieces> {
	const query = new URLSearchParams({ limit: String(limit), offset: String(offset), filter });
	return call(base, `/api/training/runs/${encodeURIComponent(runId)}?${query}`);
}

export function setRunExcluded(
	base: string,
	runId: string,
	excluded: boolean
): Promise<TrainingRun> {
	return call(base, `/api/training/runs/${encodeURIComponent(runId)}`, 'PATCH', { excluded });
}

export function setPieceExcluded(
	base: string,
	uuid: string,
	excluded: boolean
): Promise<TrainingPiece> {
	return call(base, `/api/training/pieces/${encodeURIComponent(uuid)}`, 'POST', { excluded });
}

// A bin that can take every piece: one on an enabled layer, with the
// categories the sorting profile gives it.
export type BinChoice = TrainingBin & { categoryIds: string[] };

type LayoutResponse = {
	layers?: {
		layer_index: number;
		enabled: boolean;
		bins: { section_index: number; bin_index: number; category_ids?: string[] }[];
	}[];
};

export async function getBinChoices(base: string): Promise<BinChoice[]> {
	const layout = await call<LayoutResponse>(base, '/api/bins/layout');
	return (layout.layers ?? [])
		.filter((layer) => layer.enabled)
		.flatMap((layer) =>
			layer.bins.map((b) => ({
				layer: layer.layer_index,
				section: b.section_index,
				bin: b.bin_index,
				categoryIds: b.category_ids ?? []
			}))
		);
}

export function binKey(b: TrainingBin): string {
	return `${b.layer}:${b.section}:${b.bin}`;
}

// "Layer 3, section 6, bin 2 · Transparent", counted from 1 as the Bins page
// does, with the bin's categories when they are known.
export function binLabel(b: TrainingBin, choices: BinChoice[] = []): string {
	const name = `Layer ${b.layer + 1}, section ${b.section + 1}, bin ${b.bin + 1}`;
	const choice = choices.find((c) => binKey(c) === binKey(b));
	const categories = choice ? categoryLabel(choice.categoryIds) : '';
	return categories ? `${name} · ${categories}` : name;
}

export function pieceImageUrl(base: string, piece: TrainingPiece): string | null {
	if (piece.image_id == null) return null;
	return `${base}/api/pieces/${encodeURIComponent(piece.uuid)}/images/${piece.image_id}`;
}

// The color the machine itself gave the piece: the correction, if there is one.
export function machineColorId(piece: TrainingPiece): string | null {
	return piece.color_corrected_id ?? piece.color_id;
}

// A labeled piece the machine saw as another color: the ones worth a look.
export function disagrees(piece: TrainingPiece): boolean {
	const machine = machineColorId(piece);
	return piece.training_color_id != null && machine != null && machine !== piece.training_color_id;
}

// "13 Oct, 11:58 am"
export function formatWhen(ts: number): string {
	const date = new Date(ts * 1000);
	const day = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
	return `${day}, ${formatTime(ts)}`;
}

// The colors to offer first: the newest used first (this run's latest
// segment, then earlier runs), then the commonest LEGO colors: Black, White,
// Light and Dark Bluish Gray, Red, Blue, Yellow, Tan, Reddish Brown, Green,
// Dark Tan, Orange (BrickLink ids).
const COMMON = ['11', '1', '86', '85', '5', '7', '3', '2', '88', '6', '69', '4'];

export function recentColorIds(state: TrainingState): string[] {
	const ids: string[] = [];
	const add = (id: string) => {
		if (!ids.includes(id)) ids.push(id);
	};
	const runs = state.current_run ? [state.current_run, ...state.runs] : state.runs;
	for (const run of runs) {
		for (const segment of [...(run.segments ?? [])].reverse()) segment.color_ids.forEach(add);
		run.color_ids.forEach(add);
	}
	COMMON.forEach(add);
	return ids;
}

// "11:58 am"
export function formatTime(ts: number): string {
	return new Date(ts * 1000)
		.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
		.toLowerCase();
}

// "1 h 12 min", "8 min", "40 s"
export function formatDuration(seconds: number): string {
	const s = Math.max(0, Math.round(seconds));
	if (s < 60) return `${s} s`;
	const min = Math.round(s / 60);
	if (min < 60) return `${min} min`;
	const h = Math.floor(min / 60);
	return min % 60 ? `${h} h ${min % 60} min` : `${h} h`;
}
