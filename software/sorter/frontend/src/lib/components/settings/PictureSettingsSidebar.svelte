<script lang="ts">
	import { backendHttpBaseUrl } from '$lib/backend';
	import { onDestroy } from 'svelte';
	import {
		androidCameraSettingsEqual,
		cloneAndroidCameraSettings,
		DEFAULT_ANDROID_CAMERA_CAPABILITIES,
		DEFAULT_ANDROID_CAMERA_SETTINGS,
		normalizeAndroidCameraCapabilities,
		normalizeAndroidCameraSettings,
		type AndroidCameraCapabilities,
		type AndroidCameraSettings,
		type AndroidProcessingMode
	} from '$lib/settings/android-camera-settings';
	import {
		type CameraCalibrationAnalysis,
		type CameraCalibrationGalleryEntry,
		type CameraCalibrationGalleryResponse,
		type CameraCalibrationAdvisorIteration,
		type CameraCalibrationMethod,
		type CameraCalibrationTaskStartResponse,
		type CameraCalibrationTaskStatusResponse,
		cloneUsbCameraSettings,
		normalizeCameraCalibrationAdvisorTrace,
		normalizeCameraCalibrationGalleryEntries,
		normalizeUsbCameraControls,
		normalizeUsbCameraSettings,
		usbCameraSaneDefaults,
		usbCameraSettingsEqual,
		type CameraDeviceProvider,
		type CameraDeviceSettingsResponse,
		type UsbCameraControl,
		type UsbCameraSettings
	} from '$lib/settings/camera-device-settings';
	import {
		clonePictureSettings,
		DEFAULT_PICTURE_SETTINGS,
		normalizePictureSettings,
		pictureSettingsEqual,
		type PictureSettings
	} from '$lib/settings/picture-settings';
	import type { CameraRole } from '$lib/settings/stations';
	import { RotateCcw, Save, SlidersHorizontal, Undo2, X } from 'lucide-svelte';
	import { Alert } from '$lib/components/primitives';
	import CalibrationPanel, { hasTileDetails } from './picture/CalibrationPanel.svelte';
	import DeviceControlsPanel from './picture/DeviceControlsPanel.svelte';
	import OrientationPanel from './picture/OrientationPanel.svelte';
	import LLMCalibrationTrace from '$lib/components/calibration/LLMCalibrationTrace.svelte';
	import Modal from '$lib/components/Modal.svelte';

	let {
		role,
		label,
		source = null,
		hasCamera = true,
		showHeader = true,
		calibrationReferenceImageSrc = '',
		calibrationReferenceLinkUrl = '',
		primaryActionLabel = 'Save',
		allowPrimaryActionWithoutChanges = false,
		onSaved,
		onClose,
		onPreviewChange,
		onCalibrationHighlightChange
	}: {
		role: CameraRole;
		label: string;
		source?: number | string | null;
		hasCamera?: boolean;
		showHeader?: boolean;
		calibrationReferenceImageSrc?: string;
		calibrationReferenceLinkUrl?: string;
		primaryActionLabel?: string;
		allowPrimaryActionWithoutChanges?: boolean;
		onSaved?: (() => void) | undefined;
		onClose?: (() => void) | undefined;
		onPreviewChange?:
			| ((role: CameraRole, savedSettings: PictureSettings, draftSettings: PictureSettings) => void)
			| undefined;
		onCalibrationHighlightChange?:
			| ((bbox: [number, number, number, number] | null) => void)
			| undefined;
	} = $props();

	type BooleanSettingKey = 'flip_horizontal' | 'flip_vertical';

	let loading = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let status = $state('');
	let loadedKey = $state('');

	let savedSettings = $state<PictureSettings>({ ...DEFAULT_PICTURE_SETTINGS });
	let draftSettings = $state<PictureSettings>({ ...DEFAULT_PICTURE_SETTINGS });

	let deviceProvider = $state<CameraDeviceProvider>('none');
	let deviceSupported = $state(false);
	let deviceMessage = $state('');

	let usbControls = $state<UsbCameraControl[]>([]);
	let savedUsbSettings = $state<UsbCameraSettings>({});
	let draftUsbSettings = $state<UsbCameraSettings>({});

	let savedAndroidSettings = $state<AndroidCameraSettings>({ ...DEFAULT_ANDROID_CAMERA_SETTINGS });
	let draftAndroidSettings = $state<AndroidCameraSettings>({ ...DEFAULT_ANDROID_CAMERA_SETTINGS });
	let androidCapabilities = $state<AndroidCameraCapabilities>({
		...DEFAULT_ANDROID_CAMERA_CAPABILITIES
	});

	let devicePreviewRequest = 0;
	let calibrating = $state(false);
	let calibrationResult = $state<CameraCalibrationAnalysis | null>(null);
	let calibrationStage = $state('');
	let calibrationProgress = $state(0);
	let calibrationMessage = $state('');
	let calibrationNeedsSave = $state(false);
	const CALIBRATION_METHOD_STORAGE_KEY = 'camera-calibration-method';
	const CALIBRATION_OPENROUTER_MODEL_STORAGE_KEY = 'camera-calibration-openrouter-model';
	const CALIBRATION_APPLY_COLOR_PROFILE_STORAGE_KEY = 'camera-calibration-apply-color-profile';
	const DEFAULT_CALIBRATION_OPENROUTER_MODEL = 'anthropic/claude-sonnet-4.6';

	function loadStoredCalibrationMethod(): CameraCalibrationMethod {
		if (typeof window === 'undefined') return 'target_plate';
		try {
			const raw = window.localStorage.getItem(CALIBRATION_METHOD_STORAGE_KEY);
			if (raw === 'llm_guided' || raw === 'target_plate') return raw;
		} catch {
			// ignore — storage may be disabled
		}
		return 'target_plate';
	}

	function loadStoredCalibrationOpenrouterModel(): string {
		if (typeof window === 'undefined') return DEFAULT_CALIBRATION_OPENROUTER_MODEL;
		try {
			const raw = window.localStorage.getItem(CALIBRATION_OPENROUTER_MODEL_STORAGE_KEY);
			if (typeof raw === 'string' && raw.trim()) return raw.trim();
		} catch {
			// ignore — storage may be disabled
		}
		return DEFAULT_CALIBRATION_OPENROUTER_MODEL;
	}

	function loadStoredCalibrationApplyColorProfile(): boolean {
		if (typeof window === 'undefined') return true;
		try {
			const raw = window.localStorage.getItem(CALIBRATION_APPLY_COLOR_PROFILE_STORAGE_KEY);
			if (raw === 'false') return false;
			if (raw === 'true') return true;
		} catch {
			// ignore — storage may be disabled
		}
		return true;
	}

	let calibrationMethod = $state<CameraCalibrationMethod>(loadStoredCalibrationMethod());
	let calibrationOpenrouterModel = $state(loadStoredCalibrationOpenrouterModel());
	let calibrationApplyColorProfile = $state(loadStoredCalibrationApplyColorProfile());
	let calibrationTraceEnlarged = $state(false);
	let calibrationTaskId = $state<string | null>(null);
	let calibrationAdvisorTrace = $state<CameraCalibrationAdvisorIteration[]>([]);
	let calibrationGalleryEntries = $state<CameraCalibrationGalleryEntry[]>([]);

	const DEVICE_PREVIEW_DEBOUNCE_MS = 180;

	function emitPreview(roleName: CameraRole, saved: PictureSettings, draft: PictureSettings) {
		onPreviewChange?.(roleName, clonePictureSettings(saved), clonePictureSettings(draft));
	}

	function emitCalibrationHighlight(analysis: CameraCalibrationAnalysis | null) {
		onCalibrationHighlightChange?.(analysis?.normalized_board_bbox ?? null);
	}

	function currentLoadKey() {
		return `${role}::${typeof source === 'string' ? source : source === null ? 'none' : source}`;
	}

	let devicePreviewAbortController: AbortController | null = null;
	let devicePreviewTimeout: ReturnType<typeof setTimeout> | null = null;

	function clearScheduledDevicePreview() {
		if (devicePreviewTimeout === null) return;
		clearTimeout(devicePreviewTimeout);
		devicePreviewTimeout = null;
	}

	function invalidateDevicePreview() {
		clearScheduledDevicePreview();
		devicePreviewRequest += 1;
		devicePreviewAbortController?.abort();
		devicePreviewAbortController = null;
	}

	function queueDevicePreview(options: { immediate?: boolean } = {}) {
		const { immediate = false } = options;
		invalidateDevicePreview();
		if (immediate) {
			void sendDevicePreview();
			return;
		}
		devicePreviewTimeout = setTimeout(() => {
			devicePreviewTimeout = null;
			void sendDevicePreview();
		}, DEVICE_PREVIEW_DEBOUNCE_MS);
	}

	$effect(() => {
		if (typeof window === 'undefined') return;
		try {
			window.localStorage.setItem(CALIBRATION_METHOD_STORAGE_KEY, calibrationMethod);
		} catch {
			// ignore — storage may be disabled
		}
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		try {
			window.localStorage.setItem(
				CALIBRATION_OPENROUTER_MODEL_STORAGE_KEY,
				calibrationOpenrouterModel
			);
		} catch {
			// ignore — storage may be disabled
		}
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		try {
			window.localStorage.setItem(
				CALIBRATION_APPLY_COLOR_PROFILE_STORAGE_KEY,
				calibrationApplyColorProfile ? 'true' : 'false'
			);
		} catch {
			// ignore — storage may be disabled
		}
	});

	async function loadCalibrationGallery(taskId: string): Promise<void> {
		try {
			const res = await fetch(
				`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/calibrate-target/${taskId}/gallery`,
				{ cache: 'no-store' }
			);
			if (!res.ok) throw new Error(await res.text());
			const data = (await res.json()) as CameraCalibrationGalleryResponse;
			calibrationGalleryEntries = normalizeCameraCalibrationGalleryEntries(data.entries);
		} catch {
			calibrationGalleryEntries = [];
		}
	}

	function updateRotation(value: number) {
		const nextDraftSettings = normalizePictureSettings({
			...draftSettings,
			rotation: value
		});
		draftSettings = nextDraftSettings;
		status = '';
		error = null;
		emitPreview(role, savedSettings, nextDraftSettings);
	}

	function updateBooleanSetting(key: BooleanSettingKey, value: boolean) {
		const nextDraftSettings = {
			...draftSettings,
			[key]: value
		};
		draftSettings = nextDraftSettings;
		status = '';
		error = null;
		emitPreview(role, savedSettings, nextDraftSettings);
	}

	function updateAndroidExposure(value: number) {
		draftAndroidSettings = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, exposure_compensation: Math.round(value) },
			androidCapabilities
		);
		status = '';
		error = null;
		queueDevicePreview();
	}

	function updateAndroidBoolean(key: 'ae_lock' | 'awb_lock', value: boolean) {
		draftAndroidSettings = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, [key]: value },
			androidCapabilities
		);
		status = '';
		error = null;
		queueDevicePreview();
	}

	function updateAndroidProcessingMode(value: string) {
		draftAndroidSettings = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, processing_mode: value as AndroidProcessingMode },
			androidCapabilities
		);
		status = '';
		error = null;
		queueDevicePreview();
	}

	function updateAndroidWhiteBalance(value: string) {
		draftAndroidSettings = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, white_balance_mode: value },
			androidCapabilities
		);
		status = '';
		error = null;
		queueDevicePreview();
	}

	function updateUsbNumeric(control: UsbCameraControl, value: number) {
		const min = typeof control.min === 'number' ? control.min : value;
		const max = typeof control.max === 'number' ? control.max : value;
		const clamped = Math.max(min, Math.min(max, value));
		draftUsbSettings = {
			...draftUsbSettings,
			[control.key]: clamped
		};
		status = '';
		error = null;
		queueDevicePreview();
	}

	function updateUsbBoolean(control: UsbCameraControl, value: boolean) {
		draftUsbSettings = {
			...draftUsbSettings,
			[control.key]: value
		};
		status = '';
		error = null;
		queueDevicePreview();
	}

	function currentDevicePayload(): AndroidCameraSettings | Record<string, number | boolean> | null {
		if (!deviceSupported) return null;
		if (deviceProvider === 'android-camera-app') {
			return normalizeAndroidCameraSettings(draftAndroidSettings, androidCapabilities);
		}
		if (deviceProvider === 'usb-opencv') {
			return cloneUsbCameraSettings(draftUsbSettings);
		}
		return null;
	}

	function savedDevicePayload(): AndroidCameraSettings | Record<string, number | boolean> | null {
		if (!deviceSupported) return null;
		if (deviceProvider === 'android-camera-app') {
			return normalizeAndroidCameraSettings(savedAndroidSettings, androidCapabilities);
		}
		if (deviceProvider === 'usb-opencv') {
			return cloneUsbCameraSettings(savedUsbSettings);
		}
		return null;
	}

	function applyDeviceResponse(data: CameraDeviceSettingsResponse) {
		deviceProvider =
			data.provider === 'android-camera-app' || data.provider === 'usb-opencv'
				? data.provider
				: data.provider === 'none'
					? 'none'
					: 'network-stream';
		deviceSupported = Boolean(data.supported);
		deviceMessage = data.message ?? '';

		if (deviceProvider === 'android-camera-app') {
			androidCapabilities = normalizeAndroidCameraCapabilities(data.capabilities);
			const normalized = normalizeAndroidCameraSettings(data.settings, androidCapabilities);
			savedAndroidSettings = normalized;
			draftAndroidSettings = cloneAndroidCameraSettings(normalized);
			usbControls = [];
			savedUsbSettings = {};
			draftUsbSettings = {};
			return;
		}

		if (deviceProvider === 'usb-opencv') {
			const controls = normalizeUsbCameraControls(data.controls);
			usbControls = controls;
			const normalized = normalizeUsbCameraSettings(data.settings, controls);
			savedUsbSettings = normalized;
			draftUsbSettings = cloneUsbCameraSettings(normalized);
			savedAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
			draftAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
			androidCapabilities = { ...DEFAULT_ANDROID_CAMERA_CAPABILITIES };
			return;
		}

		usbControls = [];
		savedUsbSettings = {};
		draftUsbSettings = {};
		savedAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
		draftAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
		androidCapabilities = { ...DEFAULT_ANDROID_CAMERA_CAPABILITIES };
	}

	async function loadLocalSettings() {
		const res = await fetch(`${backendHttpBaseUrl}/api/cameras/picture-settings/${role}`);
		if (!res.ok) throw new Error(await res.text());
		const data = await res.json();
		const normalized = normalizePictureSettings(data.settings ?? DEFAULT_PICTURE_SETTINGS);
		savedSettings = normalized;
		draftSettings = clonePictureSettings(normalized);
	}

	async function loadDeviceSettings() {
		const res = await fetch(`${backendHttpBaseUrl}/api/cameras/device-settings/${role}`);
		if (!res.ok) throw new Error(await res.text());
		const data = (await res.json()) as CameraDeviceSettingsResponse;
		applyDeviceResponse(data);
	}

	async function loadSettings() {
		invalidateDevicePreview();
		loading = true;
		error = null;
		status = '';
		calibrationNeedsSave = false;
		calibrationResult = null;
		calibrationStage = '';
		calibrationProgress = 0;
		calibrationMessage = '';
		calibrationTaskId = null;
		calibrationAdvisorTrace = [];
		calibrationGalleryEntries = [];
		emitCalibrationHighlight(null);
		try {
			await Promise.all([loadLocalSettings(), loadDeviceSettings()]);
			emitPreview(role, savedSettings, savedSettings);
		} catch (e: any) {
			error = e.message ?? 'Failed to load picture settings';
		} finally {
			loading = false;
		}
	}

	function normalizeCalibrationAnalysis(value: unknown): CameraCalibrationAnalysis | null {
		if (!value || typeof value !== 'object') return null;
		const record = value as Record<string, unknown>;
		const pattern = Array.isArray(record.pattern_size)
			? record.pattern_size.filter((item): item is number => typeof item === 'number')
			: [];
		const bbox = Array.isArray(record.board_bbox)
			? record.board_bbox.filter((item): item is number => typeof item === 'number')
			: [];
		const normalizedBbox = Array.isArray(record.normalized_board_bbox)
			? record.normalized_board_bbox.filter((item): item is number => typeof item === 'number')
			: [];
		if (pattern.length !== 2 || bbox.length !== 4 || normalizedBbox.length !== 4) return null;
		const numbers = [
			'total_cells',
			'bright_cell_count',
			'dark_cell_count',
			'color_cell_count',
			'score',
			'white_luma_mean',
			'black_luma_mean',
			'neutral_contrast',
			'clipped_white_fraction',
			'shadow_black_fraction',
			'white_balance_cast',
			'color_separation',
			'colorfulness',
			'reference_color_error_mean'
		] as const;
		for (const key of numbers) {
			if (typeof record[key] !== 'number') return null;
		}
		const tileSamples: CameraCalibrationAnalysis['tile_samples'] = {};
		if (record.tile_samples && typeof record.tile_samples === 'object') {
			for (const [key, rawValue] of Object.entries(
				record.tile_samples as Record<string, unknown>
			)) {
				if (!rawValue || typeof rawValue !== 'object') continue;
				const sample = rawValue as Record<string, unknown>;
				if (
					typeof sample.luma !== 'number' ||
					typeof sample.saturation !== 'number' ||
					typeof sample.clip_fraction !== 'number' ||
					typeof sample.shadow_fraction !== 'number' ||
					typeof sample.reference_error !== 'number' ||
					typeof sample.reference_match_percent !== 'number'
				) {
					continue;
				}
				tileSamples[key] = {
					luma: sample.luma,
					saturation: sample.saturation,
					clip_fraction: sample.clip_fraction,
					shadow_fraction: sample.shadow_fraction,
					reference_error: sample.reference_error,
					reference_match_percent: sample.reference_match_percent
				};
			}
		}
		return {
			pattern_size: [pattern[0], pattern[1]],
			board_bbox: [bbox[0], bbox[1], bbox[2], bbox[3]],
			normalized_board_bbox: [
				normalizedBbox[0],
				normalizedBbox[1],
				normalizedBbox[2],
				normalizedBbox[3]
			],
			total_cells: record.total_cells as number,
			bright_cell_count: record.bright_cell_count as number,
			dark_cell_count: record.dark_cell_count as number,
			color_cell_count: record.color_cell_count as number,
			score: record.score as number,
			white_luma_mean: record.white_luma_mean as number,
			black_luma_mean: record.black_luma_mean as number,
			neutral_contrast: record.neutral_contrast as number,
			clipped_white_fraction: record.clipped_white_fraction as number,
			shadow_black_fraction: record.shadow_black_fraction as number,
			white_balance_cast: record.white_balance_cast as number,
			color_separation: record.color_separation as number,
			colorfulness: record.colorfulness as number,
			reference_color_error_mean: record.reference_color_error_mean as number,
			tile_samples: tileSamples
		};
	}

	async function sendDevicePreview() {
		clearScheduledDevicePreview();
		const payload = currentDevicePayload();
		if (!payload) return;
		devicePreviewAbortController?.abort();
		const abortController = new AbortController();
		devicePreviewAbortController = abortController;
		const requestId = ++devicePreviewRequest;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/preview`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
				signal: abortController.signal
			});
			if (!res.ok) throw new Error(await res.text());
			const data = (await res.json()) as CameraDeviceSettingsResponse;
			if (requestId !== devicePreviewRequest) return;

			if (deviceProvider === 'android-camera-app') {
				draftAndroidSettings = normalizeAndroidCameraSettings(data.settings, androidCapabilities);
			} else if (deviceProvider === 'usb-opencv') {
				draftUsbSettings = normalizeUsbCameraSettings(data.settings, usbControls);
			}
		} catch (e: any) {
			if (e?.name === 'AbortError') return;
			if (requestId === devicePreviewRequest) {
				error = e.message ?? 'Failed to preview camera settings';
			}
		} finally {
			if (devicePreviewAbortController === abortController) {
				devicePreviewAbortController = null;
			}
		}
	}

	async function saveLocalSettingsPayload(payload: PictureSettings) {
		const res = await fetch(`${backendHttpBaseUrl}/api/cameras/picture-settings/${role}`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		});
		if (!res.ok) throw new Error(await res.text());
		const data = await res.json();
		return normalizePictureSettings(data.settings ?? payload);
	}

	async function saveDeviceSettings() {
		const payload = currentDevicePayload();
		if (!payload) return;
		const res = await fetch(`${backendHttpBaseUrl}/api/cameras/device-settings/${role}`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		});
		if (!res.ok) throw new Error(await res.text());
		const data = (await res.json()) as CameraDeviceSettingsResponse;

		if (deviceProvider === 'android-camera-app') {
			const normalized = normalizeAndroidCameraSettings(data.settings, androidCapabilities);
			savedAndroidSettings = normalized;
			draftAndroidSettings = cloneAndroidCameraSettings(normalized);
			return;
		}

		if (deviceProvider === 'usb-opencv') {
			const normalized = normalizeUsbCameraSettings(data.settings, usbControls);
			savedUsbSettings = normalized;
			draftUsbSettings = cloneUsbCameraSettings(normalized);
		}
	}

	async function saveSettings() {
		saving = true;
		error = null;
		const hadUnsavedChanges = hasUnsavedChanges();
		const isConfirmOnly =
			!hadUnsavedChanges && !calibrationNeedsSave && allowPrimaryActionWithoutChanges;
		try {
			status = '';
			if (hadUnsavedChanges) {
				invalidateDevicePreview();
				if (deviceSupported) {
					await saveDeviceSettings();
				}

				const localPayload = normalizePictureSettings(draftSettings);
				const normalizedLocal = await saveLocalSettingsPayload(localPayload);
				savedSettings = normalizedLocal;
				draftSettings = clonePictureSettings(normalizedLocal);
				status = deviceSupported ? 'Camera settings saved.' : 'Feed orientation saved.';
				emitPreview(role, normalizedLocal, normalizedLocal);
			} else if (calibrationNeedsSave) {
				status = 'Picture settings confirmed.';
			} else if (isConfirmOnly) {
				status = 'Picture settings confirmed.';
			}

			calibrationNeedsSave = false;
			onSaved?.();
		} catch (e: any) {
			error = e.message ?? 'Failed to save camera settings';
		} finally {
			saving = false;
		}
	}

	async function calibrateFromTarget() {
		calibrating = true;
		error = null;
		status = '';
		calibrationResult = null;
		calibrationStage = 'starting';
		calibrationProgress = 0.01;
		calibrationTaskId = null;
		calibrationAdvisorTrace = [];
		calibrationGalleryEntries = [];
		calibrationMessage =
			calibrationMethod === 'llm_guided'
				? 'Starting LLM-guided camera calibration.'
				: 'Starting camera calibration.';
		emitCalibrationHighlight(null);
		try {
			const calibrationPayload =
				calibrationMethod === 'llm_guided'
					? {
							method: calibrationMethod,
							openrouter_model: calibrationOpenrouterModel,
							apply_color_profile: calibrationApplyColorProfile
						}
					: {
							method: calibrationMethod
						};
			const res = await fetch(
				`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/calibrate-target`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(calibrationPayload)
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const start = (await res.json()) as CameraCalibrationTaskStartResponse;
			calibrationTaskId = start.task_id;
			if (typeof start.openrouter_model === 'string' && start.openrouter_model) {
				calibrationOpenrouterModel = start.openrouter_model;
			}
			let taskDone = false;
			while (!taskDone) {
				await new Promise((resolve) => setTimeout(resolve, 450));
				const poll = await fetch(
					`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/calibrate-target/${start.task_id}`
				);
				if (!poll.ok) throw new Error(await poll.text());
				const task = (await poll.json()) as CameraCalibrationTaskStatusResponse;
				calibrationStage = task.stage ?? '';
				calibrationProgress =
					typeof task.progress === 'number' ? task.progress : calibrationProgress;
				calibrationMessage = task.message ?? calibrationMessage;
				calibrationAdvisorTrace = normalizeCameraCalibrationAdvisorTrace(
					task.advisor_trace ?? task.result?.advisor_trace
				);
				if (calibrationMethod === 'llm_guided') {
					await loadCalibrationGallery(start.task_id);
				}
				if (
					calibrationMethod === 'llm_guided' &&
					!task.message &&
					calibrationAdvisorTrace.length > 0
				) {
					calibrationMessage = calibrationTraceLatestSummary(calibrationAdvisorTrace);
				}

				const normalizedTaskPreview = normalizeCalibrationAnalysis(task.analysis_preview);
				if (normalizedTaskPreview) {
					calibrationResult = normalizedTaskPreview;
					emitCalibrationHighlight(normalizedTaskPreview);
				}

				const normalizedTaskResult = normalizeCalibrationAnalysis(task.result?.analysis);
				if (
					normalizedTaskResult &&
					(hasTileDetails(normalizedTaskResult) || !hasTileDetails(calibrationResult))
				) {
					calibrationResult = normalizedTaskResult;
					emitCalibrationHighlight(normalizedTaskResult);
				}

				if (task.status === 'completed') {
					taskDone = true;
					await loadDeviceSettings();
					calibrationNeedsSave = true;
					status =
						task.result?.message ??
						task.message ??
						(calibrationMethod === 'llm_guided'
							? 'Camera calibrated with the LLM advisor.'
							: 'Camera calibrated from target plate.');
				} else if (task.status === 'failed') {
					throw new Error(
						task.error ??
							task.message ??
							(calibrationMethod === 'llm_guided'
								? 'Failed to calibrate camera with the LLM advisor'
								: 'Failed to calibrate camera from target plate')
					);
				}
			}
		} catch (e: any) {
			error =
				e.message ??
				(calibrationMethod === 'llm_guided'
					? 'Failed to calibrate camera with the LLM advisor'
					: 'Failed to calibrate camera from target plate');
			emitCalibrationHighlight(null);
		} finally {
			calibrating = false;
		}
	}

	function revertChanges() {
		draftSettings = clonePictureSettings(savedSettings);
		const devicePayload = savedDevicePayload();
		if (deviceProvider === 'android-camera-app') {
			draftAndroidSettings = cloneAndroidCameraSettings(savedAndroidSettings);
		} else if (deviceProvider === 'usb-opencv') {
			draftUsbSettings = cloneUsbCameraSettings(savedUsbSettings);
		}
		if (devicePayload) {
			queueDevicePreview({ immediate: true });
		}
		status = 'Reverted changes.';
		error = null;
		emitPreview(role, savedSettings, savedSettings);
	}

	function resetToDefaults() {
		draftSettings = clonePictureSettings(DEFAULT_PICTURE_SETTINGS);
		emitPreview(role, savedSettings, draftSettings);

		if (deviceProvider === 'android-camera-app') {
			draftAndroidSettings = normalizeAndroidCameraSettings(
				DEFAULT_ANDROID_CAMERA_SETTINGS,
				androidCapabilities
			);
			queueDevicePreview({ immediate: true });
			status = 'Reset Android camera controls and feed transforms to defaults. Save to apply.';
		} else if (deviceProvider === 'usb-opencv') {
			draftUsbSettings = usbCameraSaneDefaults(usbControls);
			queueDevicePreview({ immediate: true });
			status = 'Reset USB camera controls and feed transforms to sane defaults. Save to apply.';
		} else {
			status = 'Reset feed transforms to defaults. Save to apply.';
		}
		error = null;
	}

	function closeSidebar() {
		draftSettings = clonePictureSettings(savedSettings);
		if (deviceProvider === 'android-camera-app') {
			draftAndroidSettings = cloneAndroidCameraSettings(savedAndroidSettings);
			queueDevicePreview({ immediate: true });
		} else if (deviceProvider === 'usb-opencv') {
			draftUsbSettings = cloneUsbCameraSettings(savedUsbSettings);
			queueDevicePreview({ immediate: true });
		}
		status = '';
		error = null;
		calibrationNeedsSave = false;
		calibrationTaskId = null;
		calibrationAdvisorTrace = [];
		calibrationGalleryEntries = [];
		emitPreview(role, savedSettings, savedSettings);
		emitCalibrationHighlight(null);
		onClose?.();
	}

	function hasUnsavedChanges(): boolean {
		const localChanged = !pictureSettingsEqual(draftSettings, savedSettings);
		if (!deviceSupported) return localChanged;
		if (deviceProvider === 'android-camera-app') {
			return (
				localChanged || !androidCameraSettingsEqual(draftAndroidSettings, savedAndroidSettings)
			);
		}
		if (deviceProvider === 'usb-opencv') {
			return (
				localChanged || !usbCameraSettingsEqual(draftUsbSettings, savedUsbSettings, usbControls)
			);
		}
		return localChanged;
	}

	function canSave(): boolean {
		return hasUnsavedChanges() || calibrationNeedsSave || allowPrimaryActionWithoutChanges;
	}

	function calibrationTraceLatestSummary(trace: CameraCalibrationAdvisorIteration[]): string {
		for (let index = trace.length - 1; index >= 0; index -= 1) {
			const summary = trace[index]?.summary?.trim();
			if (summary) return summary;
		}
		return '';
	}

	onDestroy(() => {
		clearScheduledDevicePreview();
		devicePreviewRequest += 1;
	});

	$effect(() => {
		const nextKey = currentLoadKey();
		if (loadedKey !== nextKey) {
			loadedKey = nextKey;
			void loadSettings();
		}
	});
</script>

<aside
	class="flex h-full min-w-0 flex-col overflow-hidden border border-border bg-white shadow-sm xl:min-h-[32rem] dark:bg-bg"
>
	{#if showHeader}
		<div class="border-b border-border bg-surface px-4 py-3">
			<div class="flex items-start justify-between gap-3">
				<div class="flex items-start gap-3">
					<div
						class="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-white text-text dark:bg-bg"
					>
						<SlidersHorizontal size={16} />
					</div>
					<div class="min-w-0">
						<div class="text-sm font-semibold text-text">Picture Settings</div>
					</div>
				</div>
				{#if onClose}
					<button
						onclick={closeSidebar}
						class="inline-flex h-8 w-8 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-white hover:text-text dark:hover:bg-bg"
						aria-label="Close picture settings"
					>
						<X size={15} />
					</button>
				{/if}
			</div>
		</div>
	{/if}

	<div class="flex flex-1 flex-col gap-3 bg-white px-4 py-4 dark:bg-bg">
		{#if !hasCamera}
			<div class="border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted">
				Assign a camera to preview these changes live.
			</div>
		{/if}

		{#if error}
			<Alert variant="danger">
				<div class="text-[11px] font-semibold tracking-wider text-danger-dark uppercase dark:text-rose-300">
					Error
				</div>
				<div class="mt-1 text-xs leading-relaxed text-text">{error}</div>
			</Alert>
		{/if}

		{#if loading}
			<div class="py-10 text-center text-sm text-text-muted">Loading picture settings...</div>
		{:else}
			<div class="flex flex-col gap-3">
				<div class="flex flex-col gap-3">
					{#if deviceSupported}
						<CalibrationPanel
							bind:calibrationMethod
							bind:calibrationApplyColorProfile
							{calibrating}
							{saving}
							{hasCamera}
							{calibrationReferenceImageSrc}
							{calibrationReferenceLinkUrl}
							{calibrationResult}
							{calibrationStage}
							{calibrationProgress}
							{calibrationMessage}
							{calibrationNeedsSave}
							onCalibrate={calibrateFromTarget}
						/>

						{#if calibrationMethod === 'llm_guided' && (calibrating || calibrationAdvisorTrace.length > 0 || calibrationGalleryEntries.length > 0)}
							<LLMCalibrationTrace
								method={calibrationMethod}
								active={calibrating}
								taskId={calibrationTaskId}
								entries={calibrationAdvisorTrace}
								galleryEntries={calibrationGalleryEntries}
								backendBaseUrl={backendHttpBaseUrl}
								compact
								onEnlarge={() => (calibrationTraceEnlarged = true)}
							/>
						{/if}
					{/if}

					<DeviceControlsPanel
						{deviceProvider}
						{deviceSupported}
						{deviceMessage}
						{draftAndroidSettings}
						{androidCapabilities}
						{usbControls}
						{draftUsbSettings}
						onUpdateAndroidExposure={updateAndroidExposure}
						onUpdateAndroidBoolean={updateAndroidBoolean}
						onUpdateAndroidProcessingMode={updateAndroidProcessingMode}
						onUpdateAndroidWhiteBalance={updateAndroidWhiteBalance}
						onUpdateUsbNumeric={updateUsbNumeric}
						onUpdateUsbBoolean={updateUsbBoolean}
					/>
				</div>

				<OrientationPanel
					{draftSettings}
					onUpdateRotation={updateRotation}
					onUpdateBoolean={updateBooleanSetting}
				/>
			</div>

			<div class="mt-auto flex flex-col gap-2 border-t border-border pt-3">
				{#if status}
					<div class="text-xs text-text-muted">{status}</div>
				{/if}

				<div class="flex items-center gap-2">
					<button
						onclick={revertChanges}
						disabled={saving || calibrating || !hasUnsavedChanges()}
						title="Revert changes"
						aria-label="Revert changes"
						class="inline-flex h-9 w-9 cursor-pointer items-center justify-center border border-border bg-bg text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<Undo2 size={15} />
					</button>
					<button
						onclick={resetToDefaults}
						disabled={saving || calibrating}
						title="Reset to defaults"
						aria-label="Reset to defaults"
						class="inline-flex h-9 w-9 cursor-pointer items-center justify-center border border-border bg-bg text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<RotateCcw size={15} />
					</button>
					<button
						onclick={saveSettings}
						disabled={saving || calibrating || !canSave()}
						class={`inline-flex flex-1 cursor-pointer items-center justify-center gap-2 border px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${
							canSave()
								? 'border-success bg-success text-white hover:bg-success/90'
								: 'border-border bg-surface text-text-muted'
						}`}
					>
						<Save size={15} />
						<span>{saving ? `${primaryActionLabel}...` : primaryActionLabel}</span>
					</button>
				</div>
			</div>
		{/if}
	</div>
</aside>

<Modal bind:open={calibrationTraceEnlarged} wide title="LLM Calibration Log">
	<LLMCalibrationTrace
		method={calibrationMethod}
		active={calibrating}
		taskId={calibrationTaskId}
		entries={calibrationAdvisorTrace}
		galleryEntries={calibrationGalleryEntries}
		backendBaseUrl={backendHttpBaseUrl}
	/>
</Modal>
