export type PictureSettings = {
	rotation: number;
	flip_horizontal: boolean;
	flip_vertical: boolean;
};

export const DEFAULT_PICTURE_SETTINGS: PictureSettings = {
	rotation: 0,
	flip_horizontal: false,
	flip_vertical: false
};

export function clonePictureSettings(settings: PictureSettings): PictureSettings {
	return {
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
		rotation: normalizeRotation(settings.rotation),
		flip_horizontal: Boolean(settings.flip_horizontal),
		flip_vertical: Boolean(settings.flip_vertical)
	};
}

export function pictureSettingsEqual(a: PictureSettings, b: PictureSettings): boolean {
	return (
		a.rotation === b.rotation &&
		a.flip_horizontal === b.flip_horizontal &&
		a.flip_vertical === b.flip_vertical
	);
}
