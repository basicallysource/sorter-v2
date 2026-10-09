import { getBackendHttpBase } from '$lib/backend';
import type { Bin } from '$lib/components/ui/ProfileBin.svelte';

// A bin as Hive describes it for people (its picture, conditions in words, part
// count and examples); a profile saved before that has only a name.
export type SortingProfileCategory = Bin;

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
	category_order?: string[];
	rules: SortingProfileRule[];
	fallback_mode: SortingProfileFallbackMode;
	stats?: { total_parts?: number; sorted?: number } | null;
	requires?: string[];
	sync_state?: SortingProfileSyncState | null;
}

let cached = $state<SortingProfileMetadata | null>(null);
let in_flight: Promise<SortingProfileMetadata> | null = null;
let cachedBaseUrl = '';
// Bumped by every fetch, so a slow answer for the profile before a switch can
// never land on top of the one after it.
let generation = 0;
// The active profile's identity, as the machine last reported it.
let followedKey: string | null = null;

async function load(baseUrl = getBackendHttpBase()): Promise<SortingProfileMetadata> {
	if (cached && cachedBaseUrl === baseUrl) return cached;
	if (cachedBaseUrl !== baseUrl) {
		cached = null;
		in_flight = null;
	}
	if (in_flight) return in_flight;
	cachedBaseUrl = baseUrl;
	const gen = ++generation;
	const request: Promise<SortingProfileMetadata> = fetch(`${baseUrl}/sorting-profile/metadata`)
		.then((res) => {
			if (!res.ok) throw new Error(`Failed to load sorting profile metadata: ${res.status}`);
			return res.json();
		})
		.then((data: SortingProfileMetadata) => {
			if (gen === generation) {
				cached = data;
				in_flight = null;
			}
			return data;
		})
		.catch((err) => {
			if (gen === generation) in_flight = null;
			throw err;
		});
	in_flight = request;
	return request;
}

async function reload(baseUrl = getBackendHttpBase()): Promise<SortingProfileMetadata> {
	cached = null;
	in_flight = null;
	cachedBaseUrl = baseUrl;
	return load(baseUrl);
}

// Keep the cached profile the one the machine is sorting with. The machine
// reports its active profile live; whoever switched it (this tab, another
// tab, the API, a Hive sync), a new identity means fetch it again.
function follow(key: string, baseUrl = getBackendHttpBase()): void {
	if (key === followedKey) return;
	const switched = followedKey !== null;
	followedKey = key;
	void (switched ? reload(baseUrl) : load(baseUrl)).catch(() => {});
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
	follow,
	getCategoryName,
	getSetCategoryMeta
};
