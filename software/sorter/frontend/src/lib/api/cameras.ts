// Which camera looks at which part of the machine (backend server/routers/cameras.py).

import { getJson, postJson } from './http';

export type UsbCamera = { index: number; name: string };

export async function listUsbCameras(base: string): Promise<UsbCamera[]> {
	const payload = await getJson<{ usb?: UsbCamera[] }>(base, '/api/cameras/list');
	return Array.isArray(payload?.usb) ? payload.usb.filter((camera) => camera.index >= 0) : [];
}

// One source per role: a camera's index, a stream's address, or null for none.
export function assignCameras(
	base: string,
	assignments: Record<string, number | string | null>
): Promise<unknown> {
	return postJson(base, '/api/cameras/assign', assignments);
}
