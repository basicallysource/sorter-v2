export interface SortingProfileCategory {
	name: string;
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
	match_mode: string;
	conditions: SortingProfileCondition[];
	children: SortingProfileRule[];
	disabled: boolean;
}

export interface SortingProfileFallbackMode {
	rebrickable_categories: boolean;
	by_color: boolean;
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
}

let cached = $state<SortingProfileMetadata | null>(null);
let in_flight: Promise<SortingProfileMetadata> | null = null;

async function load(): Promise<SortingProfileMetadata> {
	if (cached) return cached;
	if (in_flight) return in_flight;
	in_flight = fetch('/sorting-profile/metadata')
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

function getCategoryName(category_id: string): string | null {
	if (!cached) return null;
	return cached.categories[category_id]?.name ?? null;
}

export const sortingProfileStore = {
	get data() {
		return cached;
	},
	load,
	getCategoryName
};
