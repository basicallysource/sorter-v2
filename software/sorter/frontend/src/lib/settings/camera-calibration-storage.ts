import type { CameraCalibrationMethod } from '$lib/settings/camera-device-settings';

const CALIBRATION_METHOD_STORAGE_KEY = 'camera-calibration-method';
const CALIBRATION_OPENROUTER_MODEL_STORAGE_KEY = 'camera-calibration-openrouter-model';
const CALIBRATION_APPLY_COLOR_PROFILE_STORAGE_KEY = 'camera-calibration-apply-color-profile';

export const DEFAULT_CALIBRATION_OPENROUTER_MODEL = 'anthropic/claude-sonnet-4.6';

function readStorage(key: string): string | null {
	if (typeof window === 'undefined') return null;
	try {
		return window.localStorage.getItem(key);
	} catch {
		return null;
	}
}

function writeStorage(key: string, value: string): void {
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(key, value);
	} catch {
		// Storage can be disabled or quota-limited; preferences are best-effort.
	}
}

export function loadStoredCalibrationMethod(): CameraCalibrationMethod {
	const raw = readStorage(CALIBRATION_METHOD_STORAGE_KEY);
	return raw === 'llm_guided' || raw === 'target_plate' ? raw : 'target_plate';
}

export function persistCalibrationMethod(value: CameraCalibrationMethod): void {
	writeStorage(CALIBRATION_METHOD_STORAGE_KEY, value);
}

export function loadStoredCalibrationOpenrouterModel(): string {
	const raw = readStorage(CALIBRATION_OPENROUTER_MODEL_STORAGE_KEY);
	return typeof raw === 'string' && raw.trim() ? raw.trim() : DEFAULT_CALIBRATION_OPENROUTER_MODEL;
}

export function persistCalibrationOpenrouterModel(value: string): void {
	writeStorage(CALIBRATION_OPENROUTER_MODEL_STORAGE_KEY, value);
}

export function loadStoredCalibrationApplyColorProfile(): boolean {
	const raw = readStorage(CALIBRATION_APPLY_COLOR_PROFILE_STORAGE_KEY);
	if (raw === 'false') return false;
	if (raw === 'true') return true;
	return true;
}

export function persistCalibrationApplyColorProfile(value: boolean): void {
	writeStorage(CALIBRATION_APPLY_COLOR_PROFILE_STORAGE_KEY, value ? 'true' : 'false');
}
