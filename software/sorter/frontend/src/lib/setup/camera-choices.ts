export type CameraChoice = {
	key: string;
	source: number | string | null;
	label: string;
};

export type UsbCamera = {
	index: number;
	name: string;
};

export function sourceKey(source: number | string | null | undefined): string {
	if (source === null || source === undefined) return '__none__';
	if (typeof source === 'number' && source < 0) return '__none__';
	if (typeof source === 'number') return `usb:${source}`;
	return `net:${source}`;
}

export function parseCameraSource(key: string): number | string | null {
	if (!key || key === '__none__') return null;
	if (key.startsWith('usb:')) {
		const source = Number(key.slice(4));
		return source >= 0 ? source : null;
	}
	if (key.startsWith('net:')) return key.slice(4);
	return null;
}

export function buildCameraChoices(
	usbCameras: UsbCamera[],
	roleSelections: Record<string, string>
): CameraChoice[] {
	const base: CameraChoice[] = [{ key: '__none__', source: null, label: 'Not assigned' }];
	for (const camera of usbCameras.filter((candidate) => candidate.index >= 0)) {
		base.push({
			key: sourceKey(camera.index),
			source: camera.index,
			label: `${camera.name} (Camera ${camera.index})`
		});
	}

	const seen = new Set(base.map((choice) => choice.key));
	for (const role of Object.keys(roleSelections)) {
		const key = roleSelections[role];
		if (!key || seen.has(key) || key === '__none__') continue;
		const source = parseCameraSource(key);
		if (typeof source === 'number' && source < 0) continue;
		if (source === null) continue;
		base.push({
			key,
			source,
			label:
				typeof source === 'number' ? `Configured camera ${source}` : `Configured stream ${source}`
		});
		seen.add(key);
	}

	return base;
}
