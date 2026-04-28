import { backendHttpBaseUrl } from '$lib/backend';
import type {
	CameraCalibrationGalleryResponse,
	CameraCalibrationMethod,
	CameraCalibrationTaskStartResponse,
	CameraCalibrationTaskStatusResponse,
	CameraDeviceSettingsResponse
} from '$lib/settings/camera-device-settings';
import {
	DEFAULT_PICTURE_SETTINGS,
	normalizePictureSettings,
	type PictureSettings
} from '$lib/settings/picture-settings';
import type { CameraRole } from '$lib/settings/stations';

function apiBase(baseUrl = backendHttpBaseUrl): string {
	return baseUrl.replace(/\/$/, '');
}

async function parseJsonResponse<T>(res: Response): Promise<T> {
	if (!res.ok) throw new Error(await res.text());
	return (await res.json()) as T;
}

function pictureSettingsFromUnknown(value: unknown, fallback: PictureSettings): PictureSettings {
	const record =
		value && typeof value === 'object' ? (value as Partial<PictureSettings>) : fallback;
	return normalizePictureSettings({
		rotation: typeof record.rotation === 'number' ? record.rotation : fallback.rotation,
		flip_horizontal:
			typeof record.flip_horizontal === 'boolean'
				? record.flip_horizontal
				: fallback.flip_horizontal,
		flip_vertical:
			typeof record.flip_vertical === 'boolean' ? record.flip_vertical : fallback.flip_vertical
	});
}

export async function loadPictureSettings(
	role: CameraRole,
	options: { baseUrl?: string } = {}
): Promise<PictureSettings> {
	const res = await fetch(`${apiBase(options.baseUrl)}/api/cameras/picture-settings/${role}`);
	const data = await parseJsonResponse<{ settings?: unknown }>(res);
	return pictureSettingsFromUnknown(data.settings, DEFAULT_PICTURE_SETTINGS);
}

export async function savePictureSettings(
	role: CameraRole,
	payload: PictureSettings,
	options: { baseUrl?: string } = {}
): Promise<PictureSettings> {
	const res = await fetch(`${apiBase(options.baseUrl)}/api/cameras/picture-settings/${role}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	const data = await parseJsonResponse<{ settings?: unknown }>(res);
	return pictureSettingsFromUnknown(data.settings, payload);
}

export async function loadCameraDeviceSettings(
	role: CameraRole,
	options: { baseUrl?: string } = {}
): Promise<CameraDeviceSettingsResponse> {
	const res = await fetch(`${apiBase(options.baseUrl)}/api/cameras/device-settings/${role}`);
	return parseJsonResponse<CameraDeviceSettingsResponse>(res);
}

export async function previewCameraDeviceSettings(
	role: CameraRole,
	payload: unknown,
	options: { baseUrl?: string; signal?: AbortSignal } = {}
): Promise<CameraDeviceSettingsResponse> {
	const res = await fetch(
		`${apiBase(options.baseUrl)}/api/cameras/device-settings/${role}/preview`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
			signal: options.signal
		}
	);
	return parseJsonResponse<CameraDeviceSettingsResponse>(res);
}

export async function saveCameraDeviceSettings(
	role: CameraRole,
	payload: unknown,
	options: { baseUrl?: string } = {}
): Promise<CameraDeviceSettingsResponse> {
	const res = await fetch(`${apiBase(options.baseUrl)}/api/cameras/device-settings/${role}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	return parseJsonResponse<CameraDeviceSettingsResponse>(res);
}

export async function loadCameraColorProfile(
	role: CameraRole,
	options: { baseUrl?: string } = {}
): Promise<unknown> {
	const res = await fetch(`${apiBase(options.baseUrl)}/api/cameras/color-profile/${role}`, {
		cache: 'no-store'
	});
	const data = await parseJsonResponse<{ profile?: unknown }>(res);
	return data.profile;
}

export async function removeCameraColorProfile(
	role: CameraRole,
	options: { baseUrl?: string } = {}
): Promise<{ profile: unknown; message?: string }> {
	const res = await fetch(`${apiBase(options.baseUrl)}/api/cameras/color-profile/${role}`, {
		method: 'DELETE'
	});
	const data = await parseJsonResponse<{ profile?: unknown; message?: string }>(res);
	return { profile: data.profile, message: data.message };
}

export type StartCameraCalibrationPayload =
	| { method: Exclude<CameraCalibrationMethod, 'llm_guided'> }
	| { method: 'llm_guided'; openrouter_model: string; apply_color_profile: boolean };

export async function startCameraCalibration(
	role: CameraRole,
	payload: StartCameraCalibrationPayload,
	options: { baseUrl?: string } = {}
): Promise<CameraCalibrationTaskStartResponse> {
	const res = await fetch(
		`${apiBase(options.baseUrl)}/api/cameras/device-settings/${role}/calibrate-target`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		}
	);
	return parseJsonResponse<CameraCalibrationTaskStartResponse>(res);
}

export async function loadCameraCalibrationTask(
	role: CameraRole,
	taskId: string,
	options: { baseUrl?: string } = {}
): Promise<CameraCalibrationTaskStatusResponse> {
	const res = await fetch(
		`${apiBase(options.baseUrl)}/api/cameras/device-settings/${role}/calibrate-target/${taskId}`
	);
	return parseJsonResponse<CameraCalibrationTaskStatusResponse>(res);
}

export async function loadCameraCalibrationGallery(
	role: CameraRole,
	taskId: string,
	options: { baseUrl?: string } = {}
): Promise<CameraCalibrationGalleryResponse> {
	const res = await fetch(
		`${apiBase(options.baseUrl)}/api/cameras/device-settings/${role}/calibrate-target/${taskId}/gallery`,
		{ cache: 'no-store' }
	);
	return parseJsonResponse<CameraCalibrationGalleryResponse>(res);
}
