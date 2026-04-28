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
		type CameraCalibrationAdvisorIteration,
		type CameraCalibrationMethod,
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
	import { RotateCcw, Save, SlidersHorizontal, Undo2, X } from 'lucide-svelte';
	import { Alert } from '$lib/components/primitives';
	import CalibrationPanel, { hasTileDetails } from './picture/CalibrationPanel.svelte';
	import CaptureModePanel from './picture/CaptureModePanel.svelte';
	import DriftDetection from './picture/DriftDetection.svelte';
	import ColorProfilePanel, {
		normalizeCameraColorProfile,
		type CameraColorProfile
	} from './picture/ColorProfilePanel.svelte';
	import DeviceControlsPanel from './picture/DeviceControlsPanel.svelte';
	import OrientationPanel from './picture/OrientationPanel.svelte';
	import LLMCalibrationTrace from '$lib/components/calibration/LLMCalibrationTrace.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import {
		loadCameraColorProfile,
		loadCameraDeviceSettings,
		loadPictureSettings,
		previewCameraDeviceSettings,
		removeCameraColorProfile,
		saveCameraDeviceSettings,
		savePictureSettings
	} from '$lib/settings/camera-settings-service';
	import {
		loadStoredCalibrationApplyColorProfile,
		loadStoredCalibrationMethod,
		loadStoredCalibrationOpenrouterModel,
		persistCalibrationApplyColorProfile,
		persistCalibrationMethod,
		persistCalibrationOpenrouterModel
	} from '$lib/settings/camera-calibration-storage';
	import { runCameraCalibrationFlow } from '$lib/settings/camera-calibration-flow.svelte';

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
	let calibrationMethod = $state<CameraCalibrationMethod>(loadStoredCalibrationMethod());
	let calibrationOpenrouterModel = $state(loadStoredCalibrationOpenrouterModel());
	let calibrationApplyColorProfile = $state(loadStoredCalibrationApplyColorProfile());
	let colorProfile = $state<CameraColorProfile | null>(null);
	let colorProfileLoading = $state(false);
	let colorProfileRemoving = $state(false);
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

	$effect(() => persistCalibrationMethod(calibrationMethod));
	$effect(() => persistCalibrationOpenrouterModel(calibrationOpenrouterModel));
	$effect(() => persistCalibrationApplyColorProfile(calibrationApplyColorProfile));

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
		const normalized = await loadPictureSettings(role);
		savedSettings = normalized;
		draftSettings = clonePictureSettings(normalized);
	}

	async function loadDeviceSettings() {
		applyDeviceResponse(await loadCameraDeviceSettings(role));
	}

	async function loadColorProfile() {
		colorProfileLoading = true;
		try {
			colorProfile = normalizeCameraColorProfile(await loadCameraColorProfile(role));
		} catch {
			colorProfile = null;
		} finally {
			colorProfileLoading = false;
		}
	}

	async function removeColorProfile() {
		if (colorProfileRemoving) return;
		colorProfileRemoving = true;
		error = null;
		try {
			const data = await removeCameraColorProfile(role);
			colorProfile = normalizeCameraColorProfile(data.profile);
			status = data.message ?? 'Color correction removed.';
		} catch (e: any) {
			error = e.message ?? 'Failed to remove color correction';
		} finally {
			colorProfileRemoving = false;
		}
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
			await Promise.all([loadLocalSettings(), loadDeviceSettings(), loadColorProfile()]);
			emitPreview(role, savedSettings, savedSettings);
		} catch (e: any) {
			error = e.message ?? 'Failed to load picture settings';
		} finally {
			loading = false;
		}
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
			const data = await previewCameraDeviceSettings(role, payload, {
				signal: abortController.signal
			});
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
		return savePictureSettings(role, payload);
	}

	async function saveDeviceSettings() {
		const payload = currentDevicePayload();
		if (!payload) return;
		const data = await saveCameraDeviceSettings(role, payload);

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
			const task = await runCameraCalibrationFlow({
				role,
				method: calibrationMethod,
				openrouterModel: calibrationOpenrouterModel,
				applyColorProfile: calibrationApplyColorProfile,
				onUpdate: async (update) => {
					if (update.taskId) calibrationTaskId = update.taskId;
					if (update.openrouterModel) calibrationOpenrouterModel = update.openrouterModel;
					if (typeof update.stage === 'string') calibrationStage = update.stage;
					if (typeof update.progress === 'number') calibrationProgress = update.progress;
					if (typeof update.message === 'string') calibrationMessage = update.message;
					if (update.advisorTrace) calibrationAdvisorTrace = update.advisorTrace;
					if (update.galleryEntries) calibrationGalleryEntries = update.galleryEntries;

					if (update.analysisPreview) {
						calibrationResult = update.analysisPreview;
						emitCalibrationHighlight(update.analysisPreview);
					}

					if (
						update.analysisResult &&
						(hasTileDetails(update.analysisResult) || !hasTileDetails(calibrationResult))
					) {
						calibrationResult = update.analysisResult;
						emitCalibrationHighlight(update.analysisResult);
					}
				}
			});
			await Promise.all([loadDeviceSettings(), loadColorProfile()]);
			calibrationNeedsSave = true;
			status =
				task.result?.message ??
				task.message ??
				(calibrationMethod === 'llm_guided'
					? 'Camera calibrated with the LLM advisor.'
					: 'Camera calibrated from target plate.');
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
			<div class="border border-dashed border-border bg-surface px-3 py-2 text-sm text-text-muted">
				Assign a camera to preview these changes live.
			</div>
		{/if}

		{#if error}
			<Alert variant="danger">
				<div
					class="text-xs font-semibold tracking-wider text-danger-dark uppercase dark:text-rose-300"
				>
					Error
				</div>
				<div class="mt-1 text-sm leading-relaxed text-text">{error}</div>
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

						<ColorProfilePanel
							profile={colorProfile}
							loading={colorProfileLoading}
							removing={colorProfileRemoving}
							onReset={removeColorProfile}
						/>
					{/if}

					<CaptureModePanel {role} />
					<DriftDetection
						{role}
						onAction={() => {
							void loadDeviceSettings();
						}}
					/>

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
					<div class="text-sm text-text-muted">{status}</div>
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
