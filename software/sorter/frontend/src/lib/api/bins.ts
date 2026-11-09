// The machine's bins as they are laid out (backend server/routers/bins.py):
// layers from the top, each split into sections round the chute, each
// section holding a few bins.

import type { BinInfo, LayerInfo } from '$lib/components/bins/types';
import type { BinAddress } from './chute';
import { getJson } from './http';

export type BinsLayout = {
	layers: LayerInfo[];
	// A piece no bin takes falls out of the bottom into a tray; otherwise it
	// goes to the discard bin.
	falls_through: boolean;
	discard_bin: BinAddress | null;
	current_angle: number | null;
	active_layer: number | null;
};

export function getBinsLayout(base: string): Promise<BinsLayout> {
	return getJson<BinsLayout>(base, '/api/bins/layout');
}

// The bin's number on its layer, as the Bins page shows it.
export function binNumber(bin: BinInfo): number {
	return bin.global_index + 1;
}

// "Layer 3, bin 4", counted from 1 the way the pages show them.
export function binName(layers: LayerInfo[], address: BinAddress): string {
	const layer = layers.find((entry) => entry.layer_index === address.layer_index);
	const bin = layer?.bins.find(
		(entry) => entry.section_index === address.section_index && entry.bin_index === address.bin_index
	);
	const number = bin ? binNumber(bin) : null;
	return number === null
		? `Layer ${address.layer_index + 1}, section ${address.section_index + 1}, bin ${address.bin_index + 1}`
		: `Layer ${address.layer_index + 1}, bin ${number}`;
}
