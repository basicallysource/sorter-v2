export type AndroidProcessingMode = 'standard' | 'auto' | 'hdr' | 'night';

export type AndroidCameraSettings = {
	exposure_compensation: number;
	ae_lock: boolean;
	awb_lock: boolean;
	white_balance_mode: string;
	processing_mode: AndroidProcessingMode;
};

export type AndroidCameraCapabilities = {
	exposure_compensation_min: number;
	exposure_compensation_max: number;
	exposure_compensation_step: number;
	supports_ae_lock: boolean;
	supports_awb_lock: boolean;
	supports_hdr: boolean;
	supports_hdr_scene_mode: boolean;
	supports_hdr_extension: boolean;
	supports_night_extension: boolean;
	supports_auto_extension: boolean;
	white_balance_modes: string[];
	processing_modes: AndroidProcessingMode[];
	image_analysis_supported_modes: AndroidProcessingMode[];
};

const ALL_PROCESSING_MODES: AndroidProcessingMode[] = ['standard', 'auto', 'hdr', 'night'];

export const DEFAULT_ANDROID_CAMERA_SETTINGS: AndroidCameraSettings = {
	exposure_compensation: 0,
	ae_lock: false,
	awb_lock: false,
	white_balance_mode: 'auto',
	processing_mode: 'standard'
};

export const DEFAULT_ANDROID_CAMERA_CAPABILITIES: AndroidCameraCapabilities = {
	exposure_compensation_min: 0,
	exposure_compensation_max: 0,
	exposure_compensation_step: 1,
	supports_ae_lock: false,
	supports_awb_lock: false,
	supports_hdr: false,
	supports_hdr_scene_mode: false,
	supports_hdr_extension: false,
	supports_night_extension: false,
	supports_auto_extension: false,
	white_balance_modes: ['auto'],
	processing_modes: ['standard'],
	image_analysis_supported_modes: ['standard']
};

export function cloneAndroidCameraSettings(
	settings: AndroidCameraSettings
): AndroidCameraSettings {
	return {
		exposure_compensation: settings.exposure_compensation,
		ae_lock: settings.ae_lock,
		awb_lock: settings.awb_lock,
		white_balance_mode: settings.white_balance_mode,
		processing_mode: settings.processing_mode
	};
}

function normalizeProcessingModes(value: unknown): AndroidProcessingMode[] {
	if (!Array.isArray(value)) return ['standard'];
	const filtered = value.filter(
		(mode): mode is AndroidProcessingMode =>
			typeof mode === 'string' && ALL_PROCESSING_MODES.includes(mode as AndroidProcessingMode)
	);
	return filtered.length > 0 ? Array.from(new Set(filtered)) : ['standard'];
}

export function normalizeAndroidCameraCapabilities(
	capabilities: Partial<AndroidCameraCapabilities> | null | undefined
): AndroidCameraCapabilities {
	const whiteBalanceModes = Array.isArray(capabilities?.white_balance_modes)
		? capabilities.white_balance_modes.filter(
				(value): value is string => typeof value === 'string' && value.length > 0
			)
		: [];
	const processingModes = normalizeProcessingModes(capabilities?.processing_modes);
	const imageAnalysisSupportedModes = normalizeProcessingModes(
		capabilities?.image_analysis_supported_modes
	);

	return {
		exposure_compensation_min: Math.round(Number(capabilities?.exposure_compensation_min ?? 0)),
		exposure_compensation_max: Math.round(Number(capabilities?.exposure_compensation_max ?? 0)),
		exposure_compensation_step: Number(capabilities?.exposure_compensation_step ?? 1) || 1,
		supports_ae_lock: Boolean(capabilities?.supports_ae_lock),
		supports_awb_lock: Boolean(capabilities?.supports_awb_lock),
		supports_hdr: Boolean(capabilities?.supports_hdr),
		supports_hdr_scene_mode: Boolean(capabilities?.supports_hdr_scene_mode),
		supports_hdr_extension: Boolean(capabilities?.supports_hdr_extension),
		supports_night_extension: Boolean(capabilities?.supports_night_extension),
		supports_auto_extension: Boolean(capabilities?.supports_auto_extension),
		white_balance_modes:
			whiteBalanceModes.length > 0
				? whiteBalanceModes
				: DEFAULT_ANDROID_CAMERA_CAPABILITIES.white_balance_modes,
		processing_modes: processingModes,
		image_analysis_supported_modes: imageAnalysisSupportedModes
	};
}

export function normalizeAndroidCameraSettings(
	settings: Partial<AndroidCameraSettings> | null | undefined,
	capabilities: AndroidCameraCapabilities = DEFAULT_ANDROID_CAMERA_CAPABILITIES
): AndroidCameraSettings {
	const whiteBalanceMode =
		typeof settings?.white_balance_mode === 'string' &&
		capabilities.white_balance_modes.includes(settings.white_balance_mode)
			? settings.white_balance_mode
			: 'auto';
	const processingMode =
		typeof settings?.processing_mode === 'string' &&
		capabilities.processing_modes.includes(settings.processing_mode as AndroidProcessingMode)
			? (settings.processing_mode as AndroidProcessingMode)
			: 'standard';

	return {
		exposure_compensation: Math.min(
			capabilities.exposure_compensation_max,
			Math.max(
				capabilities.exposure_compensation_min,
				Math.round(Number(settings?.exposure_compensation ?? 0))
			)
		),
		ae_lock: capabilities.supports_ae_lock && Boolean(settings?.ae_lock),
		awb_lock: capabilities.supports_awb_lock && Boolean(settings?.awb_lock),
		white_balance_mode: whiteBalanceMode,
		processing_mode: processingMode
	};
}

export function androidCameraSettingsEqual(
	a: AndroidCameraSettings,
	b: AndroidCameraSettings
): boolean {
	return (
		a.exposure_compensation === b.exposure_compensation &&
		a.ae_lock === b.ae_lock &&
		a.awb_lock === b.awb_lock &&
		a.white_balance_mode === b.white_balance_mode &&
		a.processing_mode === b.processing_mode
	);
}

export function androidCameraBaseUrl(source: string | number | null | undefined): string | null {
	if (typeof source !== 'string' || source.length === 0) return null;
	try {
		const parsed = new URL(source);
		return `${parsed.protocol}//${parsed.host}`;
	} catch {
		return null;
	}
}

export function whiteBalanceModeLabel(mode: string): string {
	switch (mode) {
		case 'cloudy-daylight':
			return 'Cloudy Daylight';
		case 'warm-fluorescent':
			return 'Warm Fluorescent';
		default:
			return mode
				.split('-')
				.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
				.join(' ');
	}
}

export function processingModeLabel(mode: AndroidProcessingMode): string {
	switch (mode) {
		case 'auto':
			return 'Auto';
		case 'hdr':
			return 'HDR';
		case 'night':
			return 'Night';
		default:
			return 'Standard';
	}
}
