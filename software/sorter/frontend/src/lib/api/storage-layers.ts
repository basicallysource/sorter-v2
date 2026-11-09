// The storage layers: how many there are and how many bins each has
// (backend server/routers/hardware.py). Layers are counted from the top: the
// first in the list is the top one.

import { getJson, postJson } from './http';

export type StorageLayer = {
	// Counted from 1.
	index: number;
	bin_count: number;
	section_count: number;
	enabled: boolean;
	servo_open_angle: number | null;
	servo_closed_angle: number | null;
	max_pieces_per_bin: number | null;
	max_dimension_mm: number | null;
};

export type StorageLayers = {
	allowed_bin_counts: number[];
	max_dimension_defaults: Record<string, number>;
	layers: StorageLayer[];
};

// What a save sends for one layer. Every field the layer has is sent back as
// it was loaded, so a save that changes one thing changes nothing else.
export type StorageLayerUpdate = {
	bin_count: number;
	enabled: boolean;
	servo_open_angle: number | null;
	servo_closed_angle: number | null;
	max_pieces_per_bin: number | null;
	max_dimension_mm: number | null;
};

export function updateFrom(layer: StorageLayer): StorageLayerUpdate {
	return {
		bin_count: layer.bin_count,
		enabled: layer.enabled,
		servo_open_angle: layer.servo_open_angle,
		servo_closed_angle: layer.servo_closed_angle,
		max_pieces_per_bin: layer.max_pieces_per_bin,
		max_dimension_mm: layer.max_dimension_mm
	};
}

export async function getStorageLayers(base: string): Promise<StorageLayers> {
	const config = await getJson<{ storage_layers: StorageLayers }>(base, '/api/hardware-config');
	return config.storage_layers;
}

export function saveStorageLayers(
	base: string,
	layers: StorageLayerUpdate[]
): Promise<{ ok: true; settings: StorageLayers; restart_required: boolean; message: string }> {
	return postJson(base, '/api/hardware-config/storage-layers', { layers });
}
