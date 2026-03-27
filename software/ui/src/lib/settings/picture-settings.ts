export type PictureSettings = {
	brightness: number;
	contrast: number;
	saturation: number;
	gamma: number;
	rotation: number;
	flip_horizontal: boolean;
	flip_vertical: boolean;
};

export const DEFAULT_PICTURE_SETTINGS: PictureSettings = {
	brightness: 0,
	contrast: 1,
	saturation: 1,
	gamma: 1,
	rotation: 0,
	flip_horizontal: false,
	flip_vertical: false
};

export function clonePictureSettings(settings: PictureSettings): PictureSettings {
	return {
		brightness: settings.brightness,
		contrast: settings.contrast,
		saturation: settings.saturation,
		gamma: settings.gamma,
		rotation: settings.rotation,
		flip_horizontal: settings.flip_horizontal,
		flip_vertical: settings.flip_vertical
	};
}

function normalizeRotation(value: number): number {
	const normalized = ((Math.round(Number(value) / 90) * 90) % 360 + 360) % 360;
	return normalized;
}

export function normalizePictureSettings(settings: PictureSettings): PictureSettings {
	return {
		brightness: Math.round(Number(settings.brightness)),
		contrast: Number(Number(settings.contrast).toFixed(2)),
		saturation: Number(Number(settings.saturation).toFixed(2)),
		gamma: Number(Number(settings.gamma).toFixed(2)),
		rotation: normalizeRotation(settings.rotation),
		flip_horizontal: Boolean(settings.flip_horizontal),
		flip_vertical: Boolean(settings.flip_vertical)
	};
}

export function pictureSettingsEqual(a: PictureSettings, b: PictureSettings): boolean {
	return (
		a.brightness === b.brightness &&
		a.contrast === b.contrast &&
		a.saturation === b.saturation &&
		a.gamma === b.gamma &&
		a.rotation === b.rotation &&
		a.flip_horizontal === b.flip_horizontal &&
		a.flip_vertical === b.flip_vertical
	);
}
