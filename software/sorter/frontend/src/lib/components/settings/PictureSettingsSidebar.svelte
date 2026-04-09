<script lang="ts">
	import { backendHttpBaseUrl } from '$lib/backend';
	import {
		androidCameraSettingsEqual,
		cloneAndroidCameraSettings,
		DEFAULT_ANDROID_CAMERA_CAPABILITIES,
		DEFAULT_ANDROID_CAMERA_SETTINGS,
		normalizeAndroidCameraCapabilities,
		normalizeAndroidCameraSettings,
		processingModeLabel,
		whiteBalanceModeLabel,
		type AndroidCameraCapabilities,
		type AndroidCameraSettings,
		type AndroidProcessingMode
	} from '$lib/settings/android-camera-settings';
	import {
		type CameraCalibrationAnalysis,
		type CameraCalibrationResponse,
		type CameraCalibrationTaskStartResponse,
		type CameraCalibrationTaskStatusResponse,
		cloneUsbCameraSettings,
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
	import { ChevronDown, RotateCcw, Save, SlidersHorizontal, Undo2, X } from 'lucide-svelte';

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

	let manualSettingsOpen = $state(false);
	let calibrationTargetHelpOpen = $state(false);
	let devicePreviewRequest = 0;
	let calibrating = $state(false);
	let calibrationResult = $state<CameraCalibrationAnalysis | null>(null);
	let calibrationStage = $state('');
	let calibrationProgress = $state(0);
	let calibrationMessage = $state('');
	let calibrationNeedsSave = $state(false);

	const CALIBRATION_TILE_ORDER = [
		'white_top',
		'black_top',
		'blue',
		'red',
		'green',
		'yellow',
		'black_bottom',
		'white_bottom'
	] as const;

	const CALIBRATION_TILE_LABELS: Record<string, string> = {
		white_top: 'White Top',
		black_top: 'Black Top',
		white_bottom: 'White Bottom',
		black_bottom: 'Black Bottom',
		red: 'Red',
		yellow: 'Yellow',
		green: 'Green',
		blue: 'Blue'
	};

	const CALIBRATION_TILE_SWATCH: Record<string, string> = {
		white_top: '#f8fafc',
		black_top: '#111827',
		white_bottom: '#e2e8f0',
		black_bottom: '#1f2937',
		red: '#dc2626',
		yellow: '#eab308',
		green: '#16a34a',
		blue: '#0284c7'
	};

	const ROTATION_OPTIONS = [0, 90, 180, 270] as const;

	function emitPreview(roleName: CameraRole, saved: PictureSettings, draft: PictureSettings) {
		onPreviewChange?.(roleName, clonePictureSettings(saved), clonePictureSettings(draft));
	}

	function emitCalibrationHighlight(analysis: CameraCalibrationAnalysis | null) {
		onCalibrationHighlightChange?.(analysis?.normalized_board_bbox ?? null);
	}

	function currentLoadKey() {
		return `${role}::${typeof source === 'string' ? source : source === null ? 'none' : source}`;
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
		void sendDevicePreview();
	}

	function updateAndroidBoolean(key: 'ae_lock' | 'awb_lock', value: boolean) {
		draftAndroidSettings = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, [key]: value },
			androidCapabilities
		);
		status = '';
		error = null;
		void sendDevicePreview();
	}

	function updateAndroidProcessingMode(value: string) {
		draftAndroidSettings = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, processing_mode: value as AndroidProcessingMode },
			androidCapabilities
		);
		status = '';
		error = null;
		void sendDevicePreview();
	}

	function updateAndroidWhiteBalance(value: string) {
		draftAndroidSettings = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, white_balance_mode: value },
			androidCapabilities
		);
		status = '';
		error = null;
		void sendDevicePreview();
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
		void sendDevicePreview();
	}

	function updateUsbBoolean(control: UsbCameraControl, value: boolean) {
		draftUsbSettings = {
			...draftUsbSettings,
			[control.key]: value
		};
		status = '';
		error = null;
		void sendDevicePreview();
	}

	function currentDevicePayload():
		| AndroidCameraSettings
		| Record<string, number | boolean>
		| null {
		if (!deviceSupported) return null;
		if (deviceProvider === 'android-camera-app') {
			return normalizeAndroidCameraSettings(draftAndroidSettings, androidCapabilities);
		}
		if (deviceProvider === 'usb-opencv') {
			return cloneUsbCameraSettings(draftUsbSettings);
		}
		return null;
	}

	function savedDevicePayload():
		| AndroidCameraSettings
		| Record<string, number | boolean>
		| null {
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
		loading = true;
		error = null;
		status = '';
		calibrationNeedsSave = false;
		calibrationResult = null;
		calibrationStage = '';
		calibrationProgress = 0;
		calibrationMessage = '';
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
			for (const [key, rawValue] of Object.entries(record.tile_samples as Record<string, unknown>)) {
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
		const payload = currentDevicePayload();
		if (!payload) return;
		const requestId = ++devicePreviewRequest;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/preview`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
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
			if (requestId === devicePreviewRequest) {
				error = e.message ?? 'Failed to preview camera settings';
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
		const isConfirmOnly = !hadUnsavedChanges && !calibrationNeedsSave && allowPrimaryActionWithoutChanges;
		try {
			status = '';
			if (hadUnsavedChanges) {
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
		calibrationMessage = 'Starting camera calibration.';
		emitCalibrationHighlight(null);
		try {
			const res = await fetch(
				`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/calibrate-target`,
				{
					method: 'POST'
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const start = (await res.json()) as CameraCalibrationTaskStartResponse;
			let taskDone = false;
			while (!taskDone) {
				await new Promise((resolve) => setTimeout(resolve, 450));
				const poll = await fetch(
					`${backendHttpBaseUrl}/api/cameras/device-settings/${role}/calibrate-target/${start.task_id}`
				);
				if (!poll.ok) throw new Error(await poll.text());
				const task = (await poll.json()) as CameraCalibrationTaskStatusResponse;
				calibrationStage = task.stage ?? '';
				calibrationProgress = typeof task.progress === 'number' ? task.progress : calibrationProgress;
				calibrationMessage = task.message ?? calibrationMessage;

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
					status = task.result?.message ?? task.message ?? 'Camera calibrated from target plate.';
				} else if (task.status === 'failed') {
					throw new Error(task.error ?? task.message ?? 'Failed to calibrate camera from target plate');
				}
			}
		} catch (e: any) {
			error = e.message ?? 'Failed to calibrate camera from target plate';
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
			void sendDevicePreview();
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
			void sendDevicePreview();
			status = 'Reset Android camera controls and feed transforms to defaults. Save to apply.';
		} else if (deviceProvider === 'usb-opencv') {
			draftUsbSettings = usbCameraSaneDefaults(usbControls);
			void sendDevicePreview();
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
			void sendDevicePreview();
		} else if (deviceProvider === 'usb-opencv') {
			draftUsbSettings = cloneUsbCameraSettings(savedUsbSettings);
			void sendDevicePreview();
		}
		status = '';
		error = null;
		calibrationNeedsSave = false;
		emitPreview(role, savedSettings, savedSettings);
		emitCalibrationHighlight(null);
		onClose?.();
	}

	function formatUsbValue(control: UsbCameraControl): string {
		const raw = draftUsbSettings[control.key];
		if (typeof raw === 'boolean') return raw ? 'On' : 'Off';
		if (typeof raw !== 'number') return 'n/a';
		const step = typeof control.step === 'number' ? control.step : 1;
		return step >= 1 ? String(Math.round(raw)) : raw.toFixed(2);
	}

	function hasUnsavedChanges(): boolean {
		const localChanged = !pictureSettingsEqual(draftSettings, savedSettings);
		if (!deviceSupported) return localChanged;
		if (deviceProvider === 'android-camera-app') {
			return localChanged || !androidCameraSettingsEqual(draftAndroidSettings, savedAndroidSettings);
		}
		if (deviceProvider === 'usb-opencv') {
			return localChanged || !usbCameraSettingsEqual(draftUsbSettings, savedUsbSettings, usbControls);
		}
		return localChanged;
	}

	function canSave(): boolean {
		return hasUnsavedChanges() || calibrationNeedsSave || allowPrimaryActionWithoutChanges;
	}

	function calibrationStageLabel(stage: string): string {
		switch (stage) {
			case 'preparing':
				return 'Preparing';
			case 'baseline':
				return 'Analyzing Baseline';
			case 'exposure_search':
				return 'Searching Exposure';
			case 'exposure_refine':
				return 'Refining Exposure';
			case 'white_balance_search':
				return 'Searching White Balance';
			case 'white_balance_refine':
				return 'Refining White Balance';
			case 'profile_generation':
				return 'Generating Color Profile';
			case 'tone_search':
				return 'Refining Tone Controls';
			case 'polish_search':
				return 'Polishing Calibration';
			case 'saving':
				return 'Saving';
			case 'verifying':
				return 'Verifying';
			case 'completed':
				return 'Completed';
			case 'failed':
				return 'Failed';
			default:
				return 'Starting';
		}
	}

	function calibrationTileEntries(analysis: CameraCalibrationAnalysis | null) {
		if (!analysis) return [];
		return CALIBRATION_TILE_ORDER
			.map((key) => {
				const sample = analysis.tile_samples[key];
				if (!sample) return null;
				const matchPercent = Math.max(0, Math.min(100, sample.reference_match_percent));
				return {
					key,
					label: CALIBRATION_TILE_LABELS[key] ?? key,
					swatch: CALIBRATION_TILE_SWATCH[key] ?? '#94a3b8',
					matchPercent,
					matchTone:
						matchPercent >= 85 ? 'good'
						: matchPercent >= 65 ? 'okay'
						: 'weak',
					...sample
				};
			})
			.filter((entry): entry is NonNullable<typeof entry> => entry !== null);
	}

	function calibrationAverageMatch(analysis: CameraCalibrationAnalysis | null): number {
		const entries = calibrationTileEntries(analysis);
		if (entries.length === 0) return 0;
		return entries.reduce((sum, entry) => sum + entry.matchPercent, 0) / entries.length;
	}

	function calibrationLowestMatch(analysis: CameraCalibrationAnalysis | null): number {
		const entries = calibrationTileEntries(analysis);
		if (entries.length === 0) return 0;
		return Math.min(...entries.map((entry) => entry.matchPercent));
	}

	function calibrationFeedback(analysis: CameraCalibrationAnalysis | null): {
		tone: 'good' | 'okay' | 'weak';
		label: string;
		message: string;
	} | null {
		if (!analysis) return null;
		const averageMatch = calibrationAverageMatch(analysis);
		const lowestMatch = calibrationLowestMatch(analysis);
		if (averageMatch >= 80 && lowestMatch >= 60) {
			return {
				tone: 'good',
				label: 'Calibration looks solid',
				message: 'The checker is reading consistently across the target.'
			};
		}
		if (averageMatch >= 60 && lowestMatch >= 35) {
			return {
				tone: 'okay',
				label: 'Calibration is usable',
				message: 'You can improve it further by reducing glare and filling more of the frame with the checker.'
			};
		}
		return {
			tone: 'weak',
			label: 'Calibration looks weak',
			message: 'Try reducing glare, keeping the target flatter, and making the Color Check larger in the preview before recalibrating.'
		};
	}

	function hasTileDetails(analysis: CameraCalibrationAnalysis | null) {
		return !!analysis && Object.keys(analysis.tile_samples).length > 0;
	}

	function calibrationSummaryVisible(analysis: CameraCalibrationAnalysis | null): boolean {
		return !!analysis && !calibrating && (calibrationNeedsSave || calibrationStage === 'completed');
	}

	$effect(() => {
		const nextKey = currentLoadKey();
		if (loadedKey !== nextKey) {
			loadedKey = nextKey;
			void loadSettings();
		}
	});
</script>

<aside
	class="flex h-full min-w-0 flex-col overflow-hidden border border-border bg-white shadow-sm dark:bg-bg xl:min-h-[32rem]"
>
	{#if showHeader}
		<div
			class="border-b border-border bg-surface px-4 py-3"
		>
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
			<div
				class="border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
			>
				Assign a camera to preview these changes live.
			</div>
		{/if}

		{#if error}
			<div
				class="border border-[#D01012]/40 bg-[#D01012]/[0.06] px-3 py-2 dark:border-rose-500/40 dark:bg-rose-500/[0.08]"
			>
				<div class="text-[11px] font-semibold uppercase tracking-wider text-[#7A0A0B] dark:text-rose-300">
					Error
				</div>
				<div class="mt-1 text-xs leading-relaxed text-text">{error}</div>
			</div>
		{/if}

		{#if loading}
			<div class="py-10 text-center text-sm text-text-muted">
				Loading picture settings...
			</div>
		{:else}
			<div class="flex flex-col gap-3">
				<div class="flex flex-col gap-3">
					{#if deviceSupported}
						<div class="grid gap-3">
							<div class="flex items-start gap-3">
								{#if calibrationReferenceImageSrc}
									<img
										src={calibrationReferenceImageSrc}
										alt="LEGO Color Check reference"
										class="h-16 w-16 shrink-0 border border-border bg-surface object-contain"
									/>
								{:else}
									<svg viewBox="0 0 40 60" width="36" height="54" class="shrink-0 rounded-sm border border-black/10 dark:border-white/10">
										<rect x="0" y="0" width="10" height="10" fill="#f0f0f0"/>
										<rect x="10" y="0" width="10" height="10" fill="#111111"/>
										<rect x="20" y="0" width="10" height="10" fill="#e0eef8"/>
										<rect x="30" y="0" width="10" height="10" fill="#0a0a2a"/>
										<rect x="0" y="10" width="20" height="20" fill="#1a8cff"/>
										<rect x="20" y="10" width="20" height="20" fill="#e02020"/>
										<rect x="0" y="30" width="20" height="20" fill="#16a34a"/>
										<rect x="20" y="30" width="20" height="20" fill="#eab308"/>
										<rect x="0" y="50" width="10" height="10" fill="#0a0a2a"/>
										<rect x="10" y="50" width="10" height="10" fill="#f0f0f0"/>
										<rect x="20" y="50" width="10" height="10" fill="#222222"/>
										<rect x="30" y="50" width="10" height="10" fill="#e0eef8"/>
										<line x1="10" y1="0" x2="10" y2="60" stroke="#00000018" stroke-width="0.5"/>
										<line x1="20" y1="0" x2="20" y2="60" stroke="#00000018" stroke-width="0.5"/>
										<line x1="30" y1="0" x2="30" y2="60" stroke="#00000018" stroke-width="0.5"/>
										<line x1="0" y1="10" x2="40" y2="10" stroke="#00000018" stroke-width="0.5"/>
										<line x1="0" y1="20" x2="40" y2="20" stroke="#00000018" stroke-width="0.5"/>
										<line x1="0" y1="30" x2="40" y2="30" stroke="#00000018" stroke-width="0.5"/>
										<line x1="0" y1="40" x2="40" y2="40" stroke="#00000018" stroke-width="0.5"/>
										<line x1="0" y1="50" x2="40" y2="50" stroke="#00000018" stroke-width="0.5"/>
									</svg>
								{/if}
								<div class="min-w-0 text-xs leading-5 text-text-muted">
									<div class="font-medium text-text">How to calibrate</div>
									<div class="mt-1">
										Place the Color Check fully inside the live preview, keep it flat and well lit, and use the preview to tune exposure, white balance, and orientation before you calibrate.
									</div>
								</div>
							</div>

							{#if calibrationReferenceLinkUrl}
								<div class="border-t border-border pt-3 text-xs leading-5 text-text-muted">
									<button
										onclick={() => (calibrationTargetHelpOpen = !calibrationTargetHelpOpen)}
										class="flex w-full cursor-pointer items-center justify-between gap-3 text-left transition-colors hover:text-text"
										aria-expanded={calibrationTargetHelpOpen}
									>
										<span class="font-medium text-text">Where do I get a calibration color checker?</span>
										<ChevronDown
											size={15}
											class={`shrink-0 text-text-muted transition-transform duration-200 ${calibrationTargetHelpOpen ? 'rotate-180' : ''}`}
										/>
									</button>
									{#if calibrationTargetHelpOpen}
										<div class="mt-2 grid gap-2 border-t border-border pt-2">
											<div>
												Use the BrickLink Studio model to buy the parts and rebuild the same LEGO Color Check target for your machine.
											</div>
											<a
												href={calibrationReferenceLinkUrl}
												target="_blank"
												rel="noreferrer"
												class="w-fit text-[11px] font-medium text-primary transition-colors hover:underline"
											>
												Open BrickLink model
											</a>
										</div>
									{/if}
								</div>
							{/if}

							{#if calibrationResult}
								<div
									class="border border-primary/40 bg-primary/[0.06] px-3 py-2 dark:border-[#4D8DFF]/40 dark:bg-[#4D8DFF]/[0.08]"
								>
									<div
										class="text-[11px] font-semibold uppercase tracking-wider text-primary-dark dark:text-[#7BAEFF]"
									>
										Calibration hint
									</div>
									<div class="mt-1 text-xs leading-relaxed text-text">
										The blue frame in the preview marks the detected Color Check area from the latest calibration pass.
									</div>
								</div>
							{/if}
						</div>

						<button
							onclick={calibrateFromTarget}
							disabled={!hasCamera || calibrating || saving}
							class="inline-flex w-full cursor-pointer items-center justify-center gap-2 border border-primary bg-primary px-4 py-2 text-sm font-medium text-primary-contrast transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
						>
							<span>{calibrating ? 'Calibrating...' : 'Calibrate'}</span>
						</button>

						{#if calibrationResult}
							{@const summaryVisible = calibrationSummaryVisible(calibrationResult)}
							<div class={`grid gap-1.5 ${summaryVisible ? 'grid-cols-2' : 'grid-cols-1'}`}>
								<div class="border border-border bg-bg px-2.5 py-2">
									<div class="text-[11px] uppercase tracking-wider text-text-muted">Match Avg</div>
									<div class="mt-0.5 font-mono text-sm tabular-nums text-text">
										{calibrationAverageMatch(calibrationResult).toFixed(0)}%
									</div>
								</div>
								{#if summaryVisible}
									<div class="border border-border bg-bg px-2.5 py-2">
										<div class="text-[11px] uppercase tracking-wider text-text-muted">Ref Error</div>
										<div class="mt-0.5 font-mono text-sm tabular-nums text-text">
											{calibrationResult.reference_color_error_mean.toFixed(1)}
										</div>
									</div>
									<div class="border border-border bg-bg px-2.5 py-2">
										<div class="text-[11px] uppercase tracking-wider text-text-muted">White / Black</div>
										<div class="mt-0.5 font-mono text-sm tabular-nums text-text">
											{calibrationResult.white_luma_mean.toFixed(1)} / {calibrationResult.black_luma_mean.toFixed(1)}
										</div>
									</div>
									<div class="border border-border bg-bg px-2.5 py-2">
										<div class="text-[11px] uppercase tracking-wider text-text-muted">WB Cast</div>
										<div class="mt-0.5 font-mono text-sm tabular-nums text-text">
											{calibrationResult.white_balance_cast.toFixed(3)}
										</div>
									</div>
								{/if}
							</div>

							{#if summaryVisible && calibrationFeedback(calibrationResult)}
								{@const feedback = calibrationFeedback(calibrationResult)}
								<div
									class={`border px-3 py-2 ${
										feedback?.tone === 'good'
											? 'border-[#00852B]/40 bg-[#00852B]/[0.06] dark:border-emerald-500/40 dark:bg-emerald-500/[0.08]'
											: feedback?.tone === 'okay'
												? 'border-[#F2A900]/50 bg-[#F2A900]/[0.07] dark:border-amber-500/40 dark:bg-amber-500/[0.08]'
												: 'border-[#D01012]/40 bg-[#D01012]/[0.06] dark:border-rose-500/40 dark:bg-rose-500/[0.08]'
									}`}
								>
									<div
										class={`text-[11px] font-semibold uppercase tracking-wider ${
											feedback?.tone === 'good'
												? 'text-[#003D14] dark:text-emerald-300'
												: feedback?.tone === 'okay'
													? 'text-[#4A3300] dark:text-amber-300'
													: 'text-[#5C0708] dark:text-rose-300'
										}`}
									>
										{feedback?.label}
									</div>
									<div class="mt-1 text-xs leading-relaxed text-text">{feedback?.message}</div>
								</div>
							{/if}

							{#if calibrationTileEntries(calibrationResult).length > 0}
								<div class="grid gap-2">
									<div class="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
										Live Tile Levels
									</div>
									<div class="grid grid-cols-2 gap-1.5">
										{#each calibrationTileEntries(calibrationResult) as tile}
											<div class="flex items-center justify-between gap-2 border border-border bg-bg px-2.5 py-2">
												<div class="flex min-w-0 items-center gap-2">
													<span
														class="inline-block h-3 w-3 shrink-0 rounded-[2px] border border-black/15"
														style={`background:${tile.swatch}`}
													></span>
													<span class="truncate text-xs text-text">{tile.label}</span>
												</div>
												<span
													class:text-[#003D14]={tile.matchTone === 'good'}
													class:text-[#4A3300]={tile.matchTone === 'okay'}
													class:text-[#5C0708]={tile.matchTone === 'weak'}
													class:dark:text-emerald-300={tile.matchTone === 'good'}
													class:dark:text-amber-300={tile.matchTone === 'okay'}
													class:dark:text-rose-300={tile.matchTone === 'weak'}
													class="font-mono text-xs font-semibold tabular-nums"
												>
													{tile.matchPercent.toFixed(0)}%
												</span>
											</div>
										{/each}
									</div>
								</div>
							{/if}
							{/if}

							{#if calibrating || calibrationMessage}
								<div class="flex flex-col gap-2">
									<div class="flex items-center justify-between gap-3 text-xs">
										<span class="font-medium text-text">
											{calibrationStageLabel(calibrationStage)}
										</span>
										<span class="font-mono text-text-muted">
											{Math.round(calibrationProgress * 100)}%
										</span>
									</div>
									<div class="h-2 overflow-hidden rounded-full bg-bg">
										<div
											class="h-full bg-sky-500 transition-[width] duration-300"
											style={`width: ${Math.max(4, Math.min(100, calibrationProgress * 100))}%`}
										></div>
									</div>
									{#if calibrationMessage}
										<div class="text-xs text-text-muted">
											{calibrationMessage}
										</div>
									{/if}
								</div>
							{/if}
					{/if}

					{#if deviceProvider === 'android-camera-app' && deviceSupported}
						<label class="flex flex-col gap-2">
							<div class="flex items-center justify-between gap-3 text-sm">
								<span class="font-medium text-text">Processing Mode</span>
							</div>
							<select
								class="border border-border bg-surface px-3 py-2 text-sm text-text"
								value={draftAndroidSettings.processing_mode}
								onchange={(event) => updateAndroidProcessingMode(event.currentTarget.value)}
							>
								{#each androidCapabilities.processing_modes as mode}
									<option value={mode}>{processingModeLabel(mode)}</option>
								{/each}
							</select>
							<div class="text-xs text-text-muted">
								{#if draftAndroidSettings.processing_mode === 'standard'}
									Uses the phone's normal live camera pipeline.
								{:else if androidCapabilities.image_analysis_supported_modes.includes(draftAndroidSettings.processing_mode)}
									This processing mode is reported as live-stream compatible on this device.
								{:else}
									This mode is exposed by the device, but the phone has not reported live image-analysis support for it yet.
								{/if}
							</div>
						</label>

						<label class="flex flex-col gap-2">
							<div class="flex items-center justify-between gap-3 text-sm">
								<span class="font-medium text-text">Exposure Compensation</span>
								<span class="font-mono text-xs text-text-muted">
									{draftAndroidSettings.exposure_compensation}
								</span>
							</div>
							<div class="flex items-center gap-2">
								<button
									type="button"
									class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg"
									onclick={() => updateAndroidExposure(Math.max(androidCapabilities.exposure_compensation_min, draftAndroidSettings.exposure_compensation - 1))}
								>&minus;</button>
								<input
									class="flex-1"
									type="range"
									min={androidCapabilities.exposure_compensation_min}
									max={androidCapabilities.exposure_compensation_max}
									step="1"
									value={draftAndroidSettings.exposure_compensation}
									oninput={(event) => updateAndroidExposure(Number(event.currentTarget.value))}
								/>
								<button
									type="button"
									class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg"
									onclick={() => updateAndroidExposure(Math.min(androidCapabilities.exposure_compensation_max, draftAndroidSettings.exposure_compensation + 1))}
								>&plus;</button>
							</div>
						</label>

						<label class="flex flex-col gap-2">
							<div class="flex items-center justify-between gap-3 text-sm">
								<span class="font-medium text-text">White Balance</span>
							</div>
							<select
								class="border border-border bg-surface px-3 py-2 text-sm text-text"
								value={draftAndroidSettings.white_balance_mode}
								onchange={(event) => updateAndroidWhiteBalance(event.currentTarget.value)}
							>
								{#each androidCapabilities.white_balance_modes as mode}
									<option value={mode}>{whiteBalanceModeLabel(mode)}</option>
								{/each}
							</select>
						</label>

						<div class="grid gap-2 sm:grid-cols-2">
							{#if androidCapabilities.supports_ae_lock}
								<label
									class="flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
								>
									<input
										type="checkbox"
										checked={draftAndroidSettings.ae_lock}
										onchange={(event) =>
											updateAndroidBoolean('ae_lock', event.currentTarget.checked)}
									/>
									<span>Exposure Lock</span>
								</label>
							{/if}

							{#if androidCapabilities.supports_awb_lock}
								<label
									class="flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
								>
									<input
										type="checkbox"
										checked={draftAndroidSettings.awb_lock}
										onchange={(event) =>
											updateAndroidBoolean('awb_lock', event.currentTarget.checked)}
									/>
									<span>White Balance Lock</span>
								</label>
							{/if}
						</div>
					{:else if deviceProvider === 'usb-opencv' && deviceSupported && usbControls.length > 0}
						<button
							onclick={() => (manualSettingsOpen = !manualSettingsOpen)}
							class="flex w-full cursor-pointer items-center justify-between border border-border bg-surface px-3 py-2 text-sm font-medium text-text transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
						>
							<span>Manual Settings</span>
							<ChevronDown
								size={15}
								class="transition-transform duration-200 {manualSettingsOpen ? 'rotate-180' : ''}"
							/>
						</button>

						{#if manualSettingsOpen}
						{#each usbControls as control (control.key)}
							{#if control.kind === 'boolean'}
								<label
									class="flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
								>
									<input
										type="checkbox"
										checked={Boolean(draftUsbSettings[control.key])}
										onchange={(event) => updateUsbBoolean(control, event.currentTarget.checked)}
									/>
									<span>{control.label}</span>
								</label>
							{:else}
								{@const usbVal = typeof draftUsbSettings[control.key] === 'number'
									? Number(draftUsbSettings[control.key])
									: Number(control.value ?? control.min ?? 0)}
								{@const usbMin = Number(control.min ?? 0)}
								{@const usbMax = Number(control.max ?? 100)}
								{@const usbStep = Number(control.step ?? 1)}
								<label class="flex flex-col gap-2">
									<div class="flex items-center justify-between gap-3 text-sm">
										<span class="font-medium text-text">{control.label}</span>
										<span class="font-mono text-xs text-text-muted">
											{formatUsbValue(control)}
										</span>
									</div>
									<div class="flex items-center gap-2">
										<button
											type="button"
											class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg"
											onclick={() => updateUsbNumeric(control, Math.max(usbMin, usbVal - usbStep))}
										>&minus;</button>
										<input
											class="flex-1"
											type="range"
											min={usbMin}
											max={usbMax}
											step={usbStep}
											value={usbVal}
											oninput={(event) => updateUsbNumeric(control, Number(event.currentTarget.value))}
										/>
										<button
											type="button"
											class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg"
											onclick={() => updateUsbNumeric(control, Math.min(usbMax, usbVal + usbStep))}
										>&plus;</button>
									</div>
									{#if control.help}
										<div class="text-xs text-text-muted">
											{control.help}
										</div>
									{/if}
								</label>
							{/if}
						{/each}
						{/if}
					{:else}
						<div
							class="border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
						>
							{deviceMessage || 'This source does not currently expose adjustable real camera controls.'}
						</div>
					{/if}
				</div>

				<div class="grid gap-2 border-t border-border pt-3">
					<div class="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
						Orientation
					</div>
					<div class="grid gap-2">
						<div>
							<div class="mb-1 text-xs font-medium text-text">Rotate</div>
							<div class="grid grid-cols-4 gap-1">
								{#each ROTATION_OPTIONS as rotation}
									<button
										onclick={() => updateRotation(rotation)}
										class={`inline-flex items-center justify-center border px-2 py-2 text-xs font-medium transition-colors ${
											draftSettings.rotation === rotation
												? 'border-primary bg-primary text-primary-contrast hover:bg-primary-hover'
												: 'border-border bg-surface text-text hover:bg-bg'
										}`}
										aria-pressed={draftSettings.rotation === rotation}
									>
										{rotation}deg
									</button>
								{/each}
							</div>
						</div>
						<div>
							<div class="mb-1 text-xs font-medium text-text">Mirror</div>
							<div class="grid grid-cols-2 gap-1">
								<button
									onclick={() => updateBooleanSetting('flip_horizontal', !draftSettings.flip_horizontal)}
									class={`inline-flex items-center justify-center border px-2 py-2 text-xs font-medium transition-colors ${
										draftSettings.flip_horizontal
											? 'border-primary bg-primary text-primary-contrast hover:bg-primary-hover'
											: 'border-border bg-surface text-text hover:bg-bg'
									}`}
									aria-pressed={draftSettings.flip_horizontal}
								>
									Flip Horizontally
								</button>
								<button
									onclick={() => updateBooleanSetting('flip_vertical', !draftSettings.flip_vertical)}
									class={`inline-flex items-center justify-center border px-2 py-2 text-xs font-medium transition-colors ${
										draftSettings.flip_vertical
											? 'border-primary bg-primary text-primary-contrast hover:bg-primary-hover'
											: 'border-border bg-surface text-text hover:bg-bg'
									}`}
									aria-pressed={draftSettings.flip_vertical}
								>
									Flip Vertically
								</button>
							</div>
						</div>
					</div>
				</div>
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
								? 'border-[#00852B] bg-[#00852B] text-white hover:bg-[#00852B]/90'
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
