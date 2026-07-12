export type BinInfo = {
	section_index: number;
	bin_index: number;
	global_index: number;
	size: string;
	angle: number;
	category_ids: string[];
	not_in_inventory?: boolean;
};

export type LayerInfo = {
	layer_index: number;
	enabled: boolean;
	section_count: number;
	section_enabled?: boolean[];
	bin_count: number;
	max_pieces_per_bin: number | null;
	bins: BinInfo[];
};

// Grouped rows carry `key` on the in-memory (runtime_stats) path and
// `item_key` on the persisted (sqlite) path — same value, different field name.
export type BinContentItem = {
	key?: string | null;
	item_key?: string | null;
	part_id?: string | null;
	color_id?: string | null;
	color_name?: string | null;
	category_id?: string | null;
	classification_status?: string | null;
	count: number;
	last_distributed_at?: number | null;
	thumbnail?: string | null;
	top_image?: string | null;
	bottom_image?: string | null;
	brickognize_preview_url?: string | null;
};

export type BinContents = {
	bin_key: string;
	layer_index: number;
	section_index: number;
	bin_index: number;
	piece_count: number;
	unique_item_count: number;
	last_distributed_at?: number | null;
	items: BinContentItem[];
	recent_pieces: BinContentItem[];
};

export type SetProgressSummary = { total_needed: number; total_found: number; pct: number };

export type SetMeta = { name: string; set_num?: string; img_url?: string };

export type SnapshotSummary = {
	id: string;
	status: string;
	label?: string | null;
	created_at: number;
	closed_at?: number | null;
	closed_reason?: string | null;
	layer_count: number;
	bin_count: number;
	piece_count: number;
};

export type SnapshotItem = Omit<BinContentItem, 'key'> & { item_key: string };

export type SnapshotLayer = {
	id: number;
	layer_index: number;
	section_index: number;
	bin_index: number;
	bin_epoch: number;
	piece_count: number;
	unique_item_count: number;
	category_ids: string[];
	flush_scope?: string | null;
	flushed_at: number;
	items: SnapshotItem[];
};

export type SnapshotDetail = SnapshotSummary & { layers: SnapshotLayer[] };
