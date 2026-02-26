import { backendHttpBaseUrl } from '$lib/backend';

interface BinData {
	size: string;
	category_id: string | null;
}

interface BinSectionData {
	bins: BinData[];
}

interface LayerData {
	sections: BinSectionData[];
}

export interface BinLayoutData {
	layers: LayerData[];
}

let layout = $state<BinLayoutData | null>(null);
let loading = $state(false);

async function fetchLayout() {
	if (layout || loading) return;
	loading = true;
	try {
		const res = await fetch(`${backendHttpBaseUrl}/bin-layout`);
		if (res.ok) {
			layout = await res.json();
		}
	} catch {
		// ignore
	} finally {
		loading = false;
	}
}

export function getBinLayout() {
	fetchLayout();
	return {
		get data() {
			return layout;
		}
	};
}
