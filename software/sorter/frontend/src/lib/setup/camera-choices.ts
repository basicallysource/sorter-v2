export type CameraChoice = {
	key: string;
	source: number | string | null;
	label: string;
	previewSrc: string | null;
	previewKind: 'mjpeg' | 'image';
};

export type UsbCamera = {
	index: number;
	name: string;
};

export type NetworkCamera = {
	id: string;
	name: string;
	source: string;
	preview_url?: string | null;
	transport: string;
};

export function sourceKey(source: number | string | null | undefined): string {
	if (source === null || source === undefined) return '__none__';
	if (typeof source === 'number') return `usb:${source}`;
	return `net:${source}`;
}

export function parseCameraSource(key: string): number | string | null {
	if (!key || key === '__none__') return null;
	if (key.startsWith('usb:')) return Number(key.slice(4));
	if (key.startsWith('net:')) return key.slice(4);
	return null;
}

export function buildCameraChoices(
	usbCameras: UsbCamera[],
	networkCameras: NetworkCamera[],
	roleSelections: Record<string, string>,
	backendBaseUrl: string
): CameraChoice[] {
	const base: CameraChoice[] = [
		{
			key: '__none__',
			source: null,
			label: 'Not assigned',
			previewSrc: null,
			previewKind: 'image'
		}
	];
	for (const camera of usbCameras) {
		base.push({
			key: sourceKey(camera.index),
			source: camera.index,
			label: `${camera.name} (Camera ${camera.index})`,
			previewSrc: `${backendBaseUrl}/api/cameras/stream/${camera.index}`,
			previewKind: 'mjpeg'
		});
	}
	for (const camera of networkCameras) {
		base.push({
			key: sourceKey(camera.source),
			source: camera.source,
			label: `${camera.name} (${camera.transport})`,
			previewSrc: camera.preview_url ?? camera.source,
			previewKind: camera.preview_url ? 'image' : 'mjpeg'
		});
	}

	const seen = new Set(base.map((choice) => choice.key));
	for (const role of Object.keys(roleSelections)) {
		const key = roleSelections[role];
		if (!key || seen.has(key) || key === '__none__') continue;
		const source = parseCameraSource(key);
		base.push({
			key,
			source,
			label:
				typeof source === 'number'
					? `Configured camera ${source}`
					: `Configured stream ${source}`,
			previewSrc:
				typeof source === 'number' ? `${backendBaseUrl}/api/cameras/stream/${source}` : source,
			previewKind: 'mjpeg'
		});
		seen.add(key);
	}

	return base;
}
