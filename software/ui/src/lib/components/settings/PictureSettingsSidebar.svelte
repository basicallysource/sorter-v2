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

	let {
		role,
		label,
		source = null,
		hasCamera = true,
		onSaved,
		onClose,
		onPreviewChange
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

	function emitPreview(roleName: CameraRole, saved: PictureSettings, draft: PictureSettings) {
		onPreviewChange?.(roleName, clonePictureSettings(saved), clonePictureSettings(draft));
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
		try {
			await Promise.all([loadLocalSettings(), loadDeviceSettings()]);
			emitPreview(role, savedSettings, savedSettings);
		} catch (e: any) {
			error = e.message ?? 'Failed to load picture settings';
		} finally {
			loading = false;
		}
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

	$effect(() => {
		const nextKey = currentLoadKey();
		if (loadedKey !== nextKey) {
			loadedKey = nextKey;
			void loadSettings();
		}
	});
</script>

<aside
	class="dark:border-border-dark dark:bg-bg-dark flex h-full min-w-0 flex-col border border-border bg-bg xl:min-h-[32rem]"
>
	<div
		class="dark:border-border-dark dark:bg-surface-dark border-b border-border bg-surface px-4 py-3"
	>
		<div class="flex items-start justify-between gap-3">
			<div class="flex items-start gap-3">
				<div
					class="dark:bg-bg-dark dark:text-text-dark flex h-9 w-9 items-center justify-center rounded-full bg-bg text-text"
				>
					<SlidersHorizontal size={16} />
				</div>
				<div class="min-w-0">
					<div class="dark:text-text-dark text-sm font-semibold text-text">Picture Settings</div>
					<p class="dark:text-text-muted-dark mt-1 text-xs leading-5 text-text-muted">
						Real camera controls live at the top when the source exposes them. Feed orientation
						stays available below.
					</p>
				</div>
			</div>
			{#if onClose}
				<button
					onclick={closeSidebar}
					class="dark:text-text-muted-dark dark:hover:bg-bg-dark dark:hover:text-text-dark inline-flex h-8 w-8 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-bg hover:text-text"
					aria-label="Close picture settings"
				>
					<X size={15} />
				</button>
			{/if}
		</div>
	</div>

	<div class="flex flex-1 flex-col gap-4 px-4 py-4">
		{#if !hasCamera}
			<div
				class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
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
			<div class="dark:text-text-muted-dark py-10 text-center text-sm text-text-muted">
				Loading picture settings...
			</div>
		{:else}
			<div class="flex flex-col gap-4">
				<div class="flex flex-col gap-4">
					<div class="dark:text-text-dark text-sm font-medium text-text">Device Controls</div>

					{#if deviceProvider === 'android-camera-app' && deviceSupported}
						<div
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
						>
							These controls are applied directly on the Android phone camera and update the live
							feed in place.
						</div>

						<label class="flex flex-col gap-2">
							<div class="flex items-center justify-between gap-3 text-sm">
								<span class="dark:text-text-dark font-medium text-text">Processing Mode</span>
							</div>
							<select
								class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark border border-border bg-surface px-3 py-2 text-sm text-text"
								value={draftAndroidSettings.processing_mode}
								onchange={(event) => updateAndroidProcessingMode(event.currentTarget.value)}
							>
								{#each androidCapabilities.processing_modes as mode}
									<option value={mode}>{processingModeLabel(mode)}</option>
								{/each}
							</select>
							<div class="dark:text-text-muted-dark text-xs text-text-muted">
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
								<span class="dark:text-text-dark font-medium text-text">Exposure Compensation</span>
								<span class="dark:text-text-muted-dark font-mono text-xs text-text-muted">
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
								<span class="dark:text-text-dark font-medium text-text">White Balance</span>
							</div>
							<select
								class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark border border-border bg-surface px-3 py-2 text-sm text-text"
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
									class="dark:border-border-dark dark:bg-surface-dark flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
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
									class="dark:border-border-dark dark:bg-surface-dark flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
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
						<div
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
						>
							These controls are applied directly to the USB camera hardware and preview live on
							the feed.
						</div>

						{#each usbControls as control (control.key)}
							{#if control.kind === 'boolean'}
								<label
									class="dark:border-border-dark dark:bg-surface-dark flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
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
										<span class="dark:text-text-dark font-medium text-text">{control.label}</span>
										<span class="dark:text-text-muted-dark font-mono text-xs text-text-muted">
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
										<div class="dark:text-text-muted-dark text-xs text-text-muted">
											{control.help}
										</div>
									{/if}
								</label>
							{/if}
						{/each}
					{:else}
						<div
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
						>
							{deviceMessage || 'This source does not currently expose adjustable real camera controls.'}
						</div>
					{/if}
				</div>

				<div class="dark:border-border-dark flex flex-col gap-4 border-t border-border pt-4">
					<div class="dark:text-text-dark text-sm font-medium text-text">Feed Orientation</div>

					<label class="flex flex-col gap-2">
						<div class="flex items-center justify-between gap-3 text-sm">
							<span class="dark:text-text-dark font-medium text-text">Rotation</span>
							<span class="dark:text-text-muted-dark font-mono text-xs text-text-muted">
								{draftSettings.rotation}deg
							</span>
						</div>
						<select
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark border border-border bg-surface px-3 py-2 text-sm text-text"
							value={String(draftSettings.rotation)}
							onchange={(event) => updateRotation(Number(event.currentTarget.value))}
						>
							<option value="0">0deg</option>
							<option value="90">90deg</option>
							<option value="180">180deg</option>
							<option value="270">270deg</option>
						</select>
					</label>

					<div class="grid gap-2 sm:grid-cols-2">
						<label
							class="dark:border-border-dark dark:bg-surface-dark flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
						>
							<input
								type="checkbox"
								checked={draftSettings.flip_horizontal}
								onchange={(event) =>
									updateBooleanSetting('flip_horizontal', event.currentTarget.checked)}
							/>
							<span>Flip Horizontal</span>
						</label>

						<label
							class="dark:border-border-dark dark:bg-surface-dark flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text"
						>
							<input
								type="checkbox"
								checked={draftSettings.flip_vertical}
								onchange={(event) =>
									updateBooleanSetting('flip_vertical', event.currentTarget.checked)}
							/>
							<span>Flip Vertical</span>
						</label>
					</div>
				</div>
			</div>

			<div class="dark:border-border-dark mt-auto flex flex-col gap-3 border-t border-border pt-4">
				{#if status}
					<div class="dark:text-text-muted-dark text-xs text-text-muted">{status}</div>
				{/if}

				<div class="grid grid-cols-1 gap-2 sm:grid-cols-3 xl:grid-cols-1">
					<button
						onclick={revertChanges}
						disabled={saving || !hasUnsavedChanges()}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex cursor-pointer items-center justify-center gap-2 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<Undo2 size={15} />
						<span>Revert</span>
					</button>
					<button
						onclick={resetToDefaults}
						disabled={saving}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex cursor-pointer items-center justify-center gap-2 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<RotateCcw size={15} />
						<span>Defaults</span>
					</button>
					<button
						onclick={saveSettings}
						disabled={saving || !hasUnsavedChanges()}
						class="inline-flex cursor-pointer items-center justify-center gap-2 border border-emerald-500 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-700 transition-colors hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-emerald-300"
					>
						<Save size={15} />
						<span>{saving ? 'Saving...' : 'Save Settings'}</span>
					</button>
				</div>
			</div>
		{/if}
	</div>
</aside>
