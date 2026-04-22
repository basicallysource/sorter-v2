export interface SortingProfileCategory {
	name: string;
}

export interface SortingProfileSetMeta {
	name?: string;
	img_url?: string;
	year?: number;
	num_parts?: number;
}

export interface SortingProfileCondition {
	id: string;
	field: string;
	op: string;
	value: string | number;
}

export interface SortingProfileRule {
	id: string;
	name: string;
	rule_type?: string;
	set_num?: string;
	set_meta?: SortingProfileSetMeta;
	match_mode: string;
	conditions: SortingProfileCondition[];
	children: SortingProfileRule[];
	disabled: boolean;
}

export interface SortingProfileFallbackMode {
	rebrickable_categories: boolean;
	bricklink_categories?: boolean;
	by_color: boolean;
}

export interface SortingProfileSyncState {
	target_id?: string | null;
	target_name?: string | null;
	target_url?: string | null;
	profile_id?: string | null;
	profile_name?: string | null;
	version_id?: string | null;
	version_number?: number | null;
	version_label?: string | null;
	artifact_hash?: string | null;
	applied_at?: string | null;
	activated_at?: string | null;
	last_error?: string | null;
	progress_last_synced_at?: string | null;
	progress_last_error?: string | null;
}

export interface SortingProfileMetadata {
	id: string;
	name: string;
	description: string;
	created_at: string;
	updated_at: string;
	default_category_id: string;
	categories: Record<string, SortingProfileCategory>;
	rules: SortingProfileRule[];
	fallback_mode: SortingProfileFallbackMode;
	sync_state?: SortingProfileSyncState | null;
}

let cached = $state<SortingProfileMetadata | null>(null);
let in_flight: Promise<SortingProfileMetadata> | null = null;
let cachedBaseUrl = '';

async function load(baseUrl = ''): Promise<SortingProfileMetadata> {
	if (cached && cachedBaseUrl === baseUrl) return cached;
	if (cachedBaseUrl !== baseUrl) {
		cached = null;
		in_flight = null;
	}
	if (in_flight) return in_flight;
	cachedBaseUrl = baseUrl;
	in_flight = fetch(`${baseUrl}/sorting-profile/metadata`)
		.then((res) => {
			if (!res.ok) throw new Error(`Failed to load sorting profile metadata: ${res.status}`);
			return res.json();
		})
		.then((data: SortingProfileMetadata) => {
			cached = data;
			in_flight = null;
			return data;
		})
		.catch((err) => {
			in_flight = null;
			throw err;
	});
	return in_flight;
}

async function reload(baseUrl = ''): Promise<SortingProfileMetadata> {
	cached = null;
	in_flight = null;
	cachedBaseUrl = baseUrl;
	return load(baseUrl);
}

function getCategoryName(category_id: string): string | null {
	if (!cached) return null;
	return cached.categories[category_id]?.name ?? null;
}

function getSetCategoryMeta(category_id: string): { name: string; set_num?: string; img_url?: string } | null {
	if (!cached) return null;
	const match = cached.rules.find((rule) => rule.id === category_id && rule.rule_type === 'set');
	if (!match) return null;
	return {
		name: match.name,
		set_num: match.set_num,
		img_url: match.set_meta?.img_url
	};
}

export const sortingProfileStore = {
	get data() {
		return cached;
	},
	load,
	reload,
	getCategoryName,
	getSetCategoryMeta
};
