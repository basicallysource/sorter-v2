import { backendHttpBaseUrl } from '$lib/backend';

interface SortingProfileMetadata {
	id: string | null;
	name: string | null;
	default_category_id: string;
	categories: Record<string, string>;
}

let metadata = $state<SortingProfileMetadata | null>(null);
let loading = $state(false);

async function fetchMetadata() {
	if (metadata || loading) return;
	loading = true;
	try {
		const res = await fetch(`${backendHttpBaseUrl}/sorting-profile`);
		if (res.ok) {
			metadata = await res.json();
		}
	} catch {
		// ignore
	} finally {
		loading = false;
	}
}

export function getSortingProfileMetadata() {
	fetchMetadata();
	return {
		get data() {
			return metadata;
		}
	};
}

export function getCategoryName(category_id: string): string {
	if (metadata?.categories[category_id]) {
		return metadata.categories[category_id];
	}
	return category_id;
}
