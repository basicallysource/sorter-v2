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
		onSaved,
		onClose,
		onPreviewChange,
		onCalibrationHighlightChange
	}: {
		role: CameraRole;
		label: string;
		source?: number | string | null;
		hasCamera?: boolean;
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
	let devicePreviewRequest = 0;
	let calibrating = $state(false);
	let calibrationResult = $state<CameraCalibrationAnalysis | null>(null);
	let calibrationStage = $state('');
	let calibrationProgress = $state(0);
	let calibrationMessage = $state('');

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
		status = '';
		try {
			if (deviceSupported) {
				await saveDeviceSettings();
			}

			const localPayload = normalizePictureSettings(draftSettings);
			const normalizedLocal = await saveLocalSettingsPayload(localPayload);
			savedSettings = normalizedLocal;
			draftSettings = clonePictureSettings(normalizedLocal);
			status = deviceSupported ? 'Camera settings saved.' : 'Feed orientation saved.';
			emitPreview(role, normalizedLocal, normalizedLocal);
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

	function hasTileDetails(analysis: CameraCalibrationAnalysis | null) {
		return !!analysis && Object.keys(analysis.tile_samples).length > 0;
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
	class="flex h-full min-w-0 flex-col border border-border bg-bg xl:min-h-[32rem]"
>
	<div
		class="border-b border-border bg-surface px-4 py-3"
	>
		<div class="flex items-start justify-between gap-3">
			<div class="flex items-start gap-3">
				<div
					class="flex h-9 w-9 items-center justify-center rounded-full bg-bg text-text"
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
					class="inline-flex h-8 w-8 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-bg hover:text-text"
					aria-label="Close picture settings"
				>
					<X size={15} />
				</button>
			{/if}
		</div>
	</div>

	<div class="flex flex-1 flex-col gap-3 px-4 py-4">
		{#if !hasCamera}
			<div
				class="border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
			>
				Assign a camera to preview these changes live.
			</div>
		{/if}

		{#if error}
			<div
				class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400"
			>
				{error}
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
						<div class="flex items-start gap-3">
							<svg viewBox="0 0 40 60" width="36" height="54" class="shrink-0 rounded-sm border border-black/10 dark:border-white/10">
								<!-- Row 1: white, black, white, dark navy -->
								<rect x="0" y="0" width="10" height="10" fill="#f0f0f0"/>
								<rect x="10" y="0" width="10" height="10" fill="#111111"/>
								<rect x="20" y="0" width="10" height="10" fill="#e0eef8"/>
								<rect x="30" y="0" width="10" height="10" fill="#0a0a2a"/>
								<!-- Rows 2-3: blue (2x2), red (2x2) -->
								<rect x="0" y="10" width="20" height="20" fill="#1a8cff"/>
								<rect x="20" y="10" width="20" height="20" fill="#e02020"/>
								<!-- Rows 4-5: green (2x2), yellow (2x2) -->
								<rect x="0" y="30" width="20" height="20" fill="#16a34a"/>
								<rect x="20" y="30" width="20" height="20" fill="#eab308"/>
								<!-- Row 6: dark navy, white, dark gray, white -->
								<rect x="0" y="50" width="10" height="10" fill="#0a0a2a"/>
								<rect x="10" y="50" width="10" height="10" fill="#f0f0f0"/>
								<rect x="20" y="50" width="10" height="10" fill="#222222"/>
								<rect x="30" y="50" width="10" height="10" fill="#e0eef8"/>
								<!-- Grid lines -->
								<line x1="10" y1="0" x2="10" y2="60" stroke="#00000018" stroke-width="0.5"/>
								<line x1="20" y1="0" x2="20" y2="60" stroke="#00000018" stroke-width="0.5"/>
								<line x1="30" y1="0" x2="30" y2="60" stroke="#00000018" stroke-width="0.5"/>
								<line x1="0" y1="10" x2="40" y2="10" stroke="#00000018" stroke-width="0.5"/>
								<line x1="0" y1="20" x2="40" y2="20" stroke="#00000018" stroke-width="0.5"/>
								<line x1="0" y1="30" x2="40" y2="30" stroke="#00000018" stroke-width="0.5"/>
								<line x1="0" y1="40" x2="40" y2="40" stroke="#00000018" stroke-width="0.5"/>
								<line x1="0" y1="50" x2="40" y2="50" stroke="#00000018" stroke-width="0.5"/>
							</svg>
							<p class="text-xs leading-4 text-text-muted">
								Place the color calibration plate fully in view, then calibrate.
							</p>
						</div>

						<button
							onclick={calibrateFromTarget}
							disabled={!hasCamera || calibrating || saving}
							class="inline-flex w-full cursor-pointer items-center justify-center gap-2 border border-sky-500 bg-sky-500/15 px-3 py-2 text-sm text-sky-700 transition-colors hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-sky-300"
						>
							<span>{calibrating ? 'Calibrating...' : 'Calibrate'}</span>
						</button>

						{#if calibrationResult}
								<div class="grid grid-cols-2 gap-1.5 text-[11px]">
									<div class="border border-border bg-bg px-2.5 py-2">
										<div class="text-text-muted">Score</div>
										<div class="font-mono text-[13px] text-text">
											{calibrationResult.score.toFixed(1)}
										</div>
									</div>
									<div class="border border-border bg-bg px-2.5 py-2">
										<div class="text-text-muted">Ref Error</div>
										<div class="font-mono text-[13px] text-text">
											{calibrationResult.reference_color_error_mean.toFixed(1)}
										</div>
									</div>
									<div class="border border-border bg-bg px-2.5 py-2">
										<div class="text-text-muted">White / Black</div>
										<div class="font-mono text-[13px] text-text">
											{calibrationResult.white_luma_mean.toFixed(1)} / {calibrationResult.black_luma_mean.toFixed(1)}
										</div>
									</div>
									<div class="border border-border bg-bg px-2.5 py-2">
										<div class="text-text-muted">WB Cast</div>
										<div class="font-mono text-[13px] text-text">
											{calibrationResult.white_balance_cast.toFixed(3)}
										</div>
									</div>
								</div>

								{#if calibrationTileEntries(calibrationResult).length > 0}
									<div class="grid gap-2">
										<div class="text-[11px] uppercase tracking-[0.14em] text-text-muted">
											Live Tile Levels
										</div>
										<div class="grid grid-cols-2 gap-1.5">
											{#each calibrationTileEntries(calibrationResult) as tile}
												<div class="grid gap-1 border border-border bg-bg px-2.5 py-2">
													<div class="flex items-center justify-between gap-2 text-[10px]">
														<div class="flex items-center gap-2">
															<span
																class="inline-block h-3 w-3 rounded-[2px] border border-black/15"
																style={`background:${tile.swatch}`}
															></span>
															<span class="font-medium text-text">{tile.label}</span>
														</div>
														<span
															class:text-emerald-700={tile.matchTone === 'good'}
															class:text-amber-700={tile.matchTone === 'okay'}
															class:text-rose-700={tile.matchTone === 'weak'}
															class:dark:text-emerald-300={tile.matchTone === 'good'}
															class:dark:text-amber-300={tile.matchTone === 'okay'}
															class:dark:text-rose-300={tile.matchTone === 'weak'}
															class="font-mono text-[10px] font-semibold"
														>
															{tile.matchPercent.toFixed(0)}%
														</span>
													</div>
													<div class="flex items-center justify-between gap-2 text-[10px]">
														<span class="text-text-muted">
															dE {tile.reference_error.toFixed(1)}
														</span>
														<span class="text-text-muted">
															L {tile.luma.toFixed(0)} / S {tile.saturation.toFixed(0)}
														</span>
													</div>
													<div class="flex items-center justify-between gap-2 text-[10px]">
														<span class="text-text-muted">
															C {(tile.clip_fraction * 100).toFixed(0)}
														</span>
														<span class="text-text-muted">
															Sh {(tile.shadow_fraction * 100).toFixed(0)}
														</span>
													</div>
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
							<input
								type="range"
								min={androidCapabilities.exposure_compensation_min}
								max={androidCapabilities.exposure_compensation_max}
								step="1"
								value={draftAndroidSettings.exposure_compensation}
								oninput={(event) => updateAndroidExposure(Number(event.currentTarget.value))}
							/>
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
								<label class="flex flex-col gap-2">
									<div class="flex items-center justify-between gap-3 text-sm">
										<span class="font-medium text-text">{control.label}</span>
										<span class="font-mono text-xs text-text-muted">
											{formatUsbValue(control)}
										</span>
									</div>
									<input
										type="range"
										min={control.min ?? 0}
										max={control.max ?? 100}
										step={control.step ?? 1}
										value={typeof draftUsbSettings[control.key] === 'number'
											? Number(draftUsbSettings[control.key])
											: Number(control.value ?? control.min ?? 0)}
										oninput={(event) => updateUsbNumeric(control, Number(event.currentTarget.value))}
									/>
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

				<div class="flex items-center gap-3 border-t border-border pt-3">
					<select
						class="border border-border bg-surface px-2 py-1.5 text-xs text-text"
						value={String(draftSettings.rotation)}
						onchange={(event) => updateRotation(Number(event.currentTarget.value))}
					>
						<option value="0">0deg</option>
						<option value="90">90deg</option>
						<option value="180">180deg</option>
						<option value="270">270deg</option>
					</select>
					<label class="flex items-center gap-1.5 text-xs text-text">
						<input
							type="checkbox"
							checked={draftSettings.flip_horizontal}
							onchange={(event) =>
								updateBooleanSetting('flip_horizontal', event.currentTarget.checked)}
						/>
						<span>Flip H</span>
					</label>
					<label class="flex items-center gap-1.5 text-xs text-text">
						<input
							type="checkbox"
							checked={draftSettings.flip_vertical}
							onchange={(event) =>
								updateBooleanSetting('flip_vertical', event.currentTarget.checked)}
						/>
						<span>Flip V</span>
					</label>
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
						disabled={saving || calibrating || !hasUnsavedChanges()}
						class="inline-flex flex-1 cursor-pointer items-center justify-center gap-2 border border-emerald-500 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-700 transition-colors hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-emerald-300"
					>
						<Save size={15} />
						<span>{saving ? 'Saving...' : 'Save'}</span>
					</button>
				</div>
			</div>
		{/if}
	</div>
</aside>
