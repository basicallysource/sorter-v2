// Shared layer configuration — the single source of truth for how many layers
// the machine has. Both tabs read and mutate this: the 3D-parts tab configures
// each layer's bin size, the aluminium tab just adds/removes layers. The layer
// COUNT drives per-layer part quantities on both.

import { browser } from '$app/environment';

export type LayerSize = 'third' | 'half';

const KEY = 'sorter-layers-v1';
const DEFAULT: LayerSize[] = ['third', 'third', 'half'];

function load(): LayerSize[] {
	if (!browser) return [...DEFAULT];
	try {
		const raw = localStorage.getItem(KEY);
		const v = raw ? JSON.parse(raw) : null;
		if (Array.isArray(v) && v.length) return v as LayerSize[];
	} catch {
		/* ignore */
	}
	return [...DEFAULT];
}

export const layerStore = $state<{ sizes: LayerSize[] }>({ sizes: load() });

export function layerCount(): number {
	return layerStore.sizes.length;
}

export function addLayer(size: LayerSize = 'third'): void {
	layerStore.sizes = [...layerStore.sizes, size];
}

export function removeLastLayer(): void {
	if (layerStore.sizes.length > 1) layerStore.sizes = layerStore.sizes.slice(0, -1);
}

export function removeLayerAt(i: number): void {
	if (layerStore.sizes.length > 1) layerStore.sizes = layerStore.sizes.filter((_, j) => j !== i);
}

export function setSize(i: number, size: LayerSize): void {
	layerStore.sizes = layerStore.sizes.map((s, j) => (j === i ? size : s));
}

export function setSizes(sizes: LayerSize[]): void {
	if (sizes.length) layerStore.sizes = [...sizes];
}

if (browser) {
	$effect.root(() => {
		$effect(() => {
			try {
				localStorage.setItem(KEY, JSON.stringify(layerStore.sizes));
			} catch {
				/* storage full / disabled */
			}
		});
	});
}
