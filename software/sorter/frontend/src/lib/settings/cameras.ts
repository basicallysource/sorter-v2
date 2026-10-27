import { getBackendHttpBase } from '$lib/backend';
import type { CameraRole } from './stations';

// A camera by its index on the machine, a URL, or none.
export type CameraSource = number | string | null;

export const CAMERA_ROLES: CameraRole[] = ['c_channel_2', 'c_channel_3', 'carousel', 'classification_channel'];

export const ROLE_LABELS: Record<CameraRole, string> = {
	c_channel_2: 'C-channel 2',
	c_channel_3: 'C-channel 3',
	carousel: 'Carousel',
	classification_channel: 'Classification C-channel (C4)'
};

export function noCameras(): Record<CameraRole, CameraSource> {
	return { c_channel_2: null, c_channel_3: null, carousel: null, classification_channel: null };
}

export async function loadCameraAssignments(): Promise<Record<CameraRole, CameraSource>> {
	const out = noCameras();
	const res = await fetch(`${getBackendHttpBase()}/api/cameras/config`);
	if (!res.ok) return out;
	const config = await res.json();
	for (const role of CAMERA_ROLES) out[role] = config[role] ?? null;
	return out;
}
