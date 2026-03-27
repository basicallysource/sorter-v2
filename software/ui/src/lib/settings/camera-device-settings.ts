import type { AndroidCameraCapabilities } from '$lib/settings/android-camera-settings';

export type CameraDeviceProvider =
	| 'none'
	| 'network-stream'
	| 'android-camera-app'
	| 'usb-opencv';

export type UsbCameraControl = {
	key: string;
	label: string;
	kind: 'boolean' | 'number';
	help?: string;
	value?: number | boolean;
	default?: number | boolean;
	min?: number;
	max?: number;
	step?: number;
};

export type UsbCameraSettings = Record<string, number | boolean>;

export type CameraDeviceSettingsResponse = {
	ok: boolean;
	role: string;
	source: string | number | null;
	provider: CameraDeviceProvider | string;
	settings?: Record<string, unknown>;
	capabilities?: Partial<AndroidCameraCapabilities>;
	controls?: UsbCameraControl[];
	supported?: boolean;
	message?: string;
};

export function normalizeUsbCameraControls(value: unknown): UsbCameraControl[] {
	if (!Array.isArray(value)) return [];
	const controls = value
		.map((item) => {
			if (!item || typeof item !== 'object') return null;
			const record = item as Record<string, unknown>;
			if (typeof record.key !== 'string' || typeof record.label !== 'string') return null;
			if (record.kind !== 'boolean' && record.kind !== 'number') return null;
			return {
				key: record.key,
				label: record.label,
				kind: record.kind,
				help: typeof record.help === 'string' ? record.help : undefined,
				value:
					typeof record.value === 'boolean'
						? record.value
						: typeof record.value === 'number'
							? record.value
							: undefined,
				default:
					typeof record.default === 'boolean'
						? record.default
						: typeof record.default === 'number'
							? record.default
							: undefined,
				min: typeof record.min === 'number' ? record.min : undefined,
				max: typeof record.max === 'number' ? record.max : undefined,
				step: typeof record.step === 'number' ? record.step : undefined
			} satisfies UsbCameraControl;
		})
		.filter((item) => item !== null);
	return controls as UsbCameraControl[];
}

export function normalizeUsbCameraSettings(
	settings: unknown,
	controls: UsbCameraControl[]
): UsbCameraSettings {
	if (!settings || typeof settings !== 'object') return {};
	const record = settings as Record<string, unknown>;
	const result: UsbCameraSettings = {};
	for (const control of controls) {
		const rawValue = record[control.key];
		if (control.kind === 'boolean') {
			if (typeof rawValue === 'boolean') {
				result[control.key] = rawValue;
			} else if (typeof control.value === 'boolean') {
				result[control.key] = control.value;
			}
			continue;
		}

		const fallback =
			typeof control.value === 'number'
				? control.value
				: typeof control.min === 'number'
					? control.min
					: 0;
		const numeric =
			typeof rawValue === 'number'
				? rawValue
				: typeof rawValue === 'string'
					? Number(rawValue)
					: fallback;
		if (!Number.isFinite(numeric)) {
			result[control.key] = fallback;
			continue;
		}
		const min = typeof control.min === 'number' ? control.min : numeric;
		const max = typeof control.max === 'number' ? control.max : numeric;
		result[control.key] = Math.max(min, Math.min(max, numeric));
	}
	return result;
}

export function cloneUsbCameraSettings(settings: UsbCameraSettings): UsbCameraSettings {
	return { ...settings };
}

export function usbCameraSaneDefaults(controls: UsbCameraControl[]): UsbCameraSettings {
	const defaults: UsbCameraSettings = {};
	for (const control of controls) {
		if (typeof control.default === 'boolean' || typeof control.default === 'number') {
			defaults[control.key] = control.default;
			continue;
		}
		if (control.kind === 'boolean') {
			if (
				control.key === 'auto_exposure' ||
				control.key === 'auto_white_balance' ||
				control.key === 'autofocus'
			) {
				defaults[control.key] = true;
			} else if (typeof control.value === 'boolean') {
				defaults[control.key] = control.value;
			}
			continue;
		}

		if (typeof control.value === 'number') {
			defaults[control.key] = control.value;
			continue;
		}
		if (typeof control.min === 'number') {
			defaults[control.key] = control.min;
		}
	}
	return defaults;
}

export function usbCameraSettingsEqual(
	a: UsbCameraSettings,
	b: UsbCameraSettings,
	controls: UsbCameraControl[]
): boolean {
	for (const control of controls) {
		if (a[control.key] !== b[control.key]) return false;
	}
	return true;
}
