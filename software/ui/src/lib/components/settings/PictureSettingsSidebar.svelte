<script lang="ts">
	import { backendHttpBaseUrl } from '$lib/backend';
	import {
		androidCameraBaseUrl,
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

	type NumericSettingKey = 'brightness' | 'contrast' | 'saturation' | 'gamma';
	type BooleanSettingKey = 'flip_horizontal' | 'flip_vertical';
	type SettingsMode = 'local' | 'android';

	let loading = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let status = $state('');
	let loadedKey = $state('');
	let settingsMode = $state<SettingsMode>('local');
	let androidBase = $state<string | null>(null);
	let savedSettings = $state<PictureSettings>({ ...DEFAULT_PICTURE_SETTINGS });
	let draftSettings = $state<PictureSettings>({ ...DEFAULT_PICTURE_SETTINGS });
	let savedAndroidSettings = $state<AndroidCameraSettings>({ ...DEFAULT_ANDROID_CAMERA_SETTINGS });
	let draftAndroidSettings = $state<AndroidCameraSettings>({ ...DEFAULT_ANDROID_CAMERA_SETTINGS });
	let androidCapabilities = $state<AndroidCameraCapabilities>({
		...DEFAULT_ANDROID_CAMERA_CAPABILITIES
	});
	let androidPreviewRequest = 0;

	function emitPreview(roleName: CameraRole, saved: PictureSettings, draft: PictureSettings) {
		onPreviewChange?.(roleName, clonePictureSettings(saved), clonePictureSettings(draft));
	}

	function currentLoadKey() {
		return `${role}::${typeof source === 'string' ? source : source === null ? 'none' : source}`;
	}

	function updateNumericSetting(key: NumericSettingKey, value: number) {
		const nextDraftSettings = {
			...draftSettings,
			[key]: key === 'brightness' ? Math.round(value) : Number(value.toFixed(2))
		};
		draftSettings = nextDraftSettings;
		status = '';
		error = null;
		emitPreview(role, savedSettings, nextDraftSettings);
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
		const next = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, exposure_compensation: Math.round(value) },
			androidCapabilities
		);
		draftAndroidSettings = next;
		status = '';
		error = null;
		void sendAndroidPreview(next);
	}

	function updateAndroidBoolean(key: 'ae_lock' | 'awb_lock', value: boolean) {
		const next = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, [key]: value },
			androidCapabilities
		);
		draftAndroidSettings = next;
		status = '';
		error = null;
		void sendAndroidPreview(next);
	}

	function updateAndroidProcessingMode(value: string) {
		const next = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, processing_mode: value as AndroidProcessingMode },
			androidCapabilities
		);
		draftAndroidSettings = next;
		status = '';
		error = null;
		void sendAndroidPreview(next);
	}

	function updateAndroidWhiteBalance(value: string) {
		const next = normalizeAndroidCameraSettings(
			{ ...draftAndroidSettings, white_balance_mode: value },
			androidCapabilities
		);
		draftAndroidSettings = next;
		status = '';
		error = null;
		void sendAndroidPreview(next);
	}

	function revertChanges() {
		draftSettings = clonePictureSettings(savedSettings);
		if (settingsMode === 'android') {
			draftAndroidSettings = cloneAndroidCameraSettings(savedAndroidSettings);
			void sendAndroidPreview(savedAndroidSettings);
		}
		status = 'Reverted changes.';
		error = null;
		emitPreview(role, savedSettings, savedSettings);
	}

	function resetToDefaults() {
		const nextDraftSettings = clonePictureSettings(DEFAULT_PICTURE_SETTINGS);
		draftSettings = nextDraftSettings;
		emitPreview(role, savedSettings, nextDraftSettings);

		if (settingsMode === 'android') {
			const nextAndroidDefaults = normalizeAndroidCameraSettings(
				DEFAULT_ANDROID_CAMERA_SETTINGS,
				androidCapabilities
			);
			draftAndroidSettings = nextAndroidDefaults;
			void sendAndroidPreview(nextAndroidDefaults);
		}

		status = 'Reset to defaults. Save to apply.';
		error = null;
	}

	function closeSidebar() {
		draftSettings = clonePictureSettings(savedSettings);
		if (settingsMode === 'android') {
			draftAndroidSettings = cloneAndroidCameraSettings(savedAndroidSettings);
			void sendAndroidPreview(savedAndroidSettings);
		}
		status = '';
		error = null;
		emitPreview(role, savedSettings, savedSettings);
		onClose?.();
	}

	async function loadLocalSettings() {
		const res = await fetch(`${backendHttpBaseUrl}/api/cameras/picture-settings/${role}`);
		if (!res.ok) throw new Error(await res.text());
		const data = await res.json();
		const normalized = normalizePictureSettings(data.settings ?? DEFAULT_PICTURE_SETTINGS);
		savedSettings = normalized;
		draftSettings = clonePictureSettings(normalized);
	}

	async function tryLoadAndroidSettings() {
		const base = androidCameraBaseUrl(source);
		if (!base) {
			settingsMode = 'local';
			androidBase = null;
			savedAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
			draftAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
			androidCapabilities = { ...DEFAULT_ANDROID_CAMERA_CAPABILITIES };
			return;
		}

		const res = await fetch(`${base}/camera-settings`);
		if (!res.ok) throw new Error(await res.text());
		const data = await res.json();
		if (data.provider !== 'android-camera-app') {
			throw new Error('Not an Android camera app source');
		}

		settingsMode = 'android';
		androidBase = base;
		androidCapabilities = normalizeAndroidCameraCapabilities(data.capabilities);
		const normalized = normalizeAndroidCameraSettings(data.settings, androidCapabilities);
		savedAndroidSettings = normalized;
		draftAndroidSettings = cloneAndroidCameraSettings(normalized);
	}

	async function loadSettings() {
		loading = true;
		error = null;
		status = '';
		try {
			await loadLocalSettings();
			try {
				await tryLoadAndroidSettings();
			} catch {
				settingsMode = 'local';
				androidBase = null;
				savedAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
				draftAndroidSettings = { ...DEFAULT_ANDROID_CAMERA_SETTINGS };
				androidCapabilities = { ...DEFAULT_ANDROID_CAMERA_CAPABILITIES };
			}
			emitPreview(role, savedSettings, savedSettings);
		} catch (e: any) {
			error = e.message ?? 'Failed to load picture settings';
		} finally {
			loading = false;
		}
	}

	async function sendAndroidPreview(settings: AndroidCameraSettings) {
		if (settingsMode !== 'android' || !androidBase) return;
		const requestId = ++androidPreviewRequest;
		try {
			const res = await fetch(`${androidBase}/camera-settings/preview`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(settings)
			});
			if (!res.ok) throw new Error(await res.text());
		} catch (e: any) {
			if (requestId === androidPreviewRequest) {
				error = e.message ?? 'Failed to preview Android camera settings';
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

	async function saveSettings() {
		saving = true;
		error = null;
		status = '';
		try {
			if (settingsMode === 'android' && androidBase) {
				const androidPayload = normalizeAndroidCameraSettings(
					draftAndroidSettings,
					androidCapabilities
				);
				const androidRes = await fetch(`${androidBase}/camera-settings`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(androidPayload)
				});
				if (!androidRes.ok) throw new Error(await androidRes.text());
				const androidData = await androidRes.json();
				const normalizedAndroid = normalizeAndroidCameraSettings(
					androidData.settings ?? androidPayload,
					androidCapabilities
				);
				savedAndroidSettings = normalizedAndroid;
				draftAndroidSettings = cloneAndroidCameraSettings(normalizedAndroid);
			}

			const localPayload = normalizePictureSettings(draftSettings);
			const normalizedLocal = await saveLocalSettingsPayload(localPayload);
			savedSettings = normalizedLocal;
			draftSettings = clonePictureSettings(normalizedLocal);
			status =
				settingsMode === 'android'
					? 'Android camera settings saved.'
					: 'Picture settings saved.';
			emitPreview(role, normalizedLocal, normalizedLocal);
			onSaved?.();
		} catch (e: any) {
			error = e.message ?? 'Failed to save picture settings';
		} finally {
			saving = false;
		}
	}

	function formatValue(key: keyof PictureSettings, value: number): string {
		if (key === 'brightness') return String(Math.round(value));
		return value.toFixed(2);
	}

	function hasUnsavedChanges(): boolean {
		const localChanged = !pictureSettingsEqual(draftSettings, savedSettings);
		if (settingsMode !== 'android') return localChanged;
		return localChanged || !androidCameraSettingsEqual(draftAndroidSettings, savedAndroidSettings);
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
						{#if settingsMode === 'android'}
							Adjust {label} directly on the Android camera device. Rotation and flips remain sorter-side.
						{:else}
							Adjust {label} image tuning. These settings are persisted per camera role and applied to
							the live feed after you save.
						{/if}
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
				{#if settingsMode === 'android'}
					<div
						class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
					>
						These controls are applied directly on the Android phone camera and update the live feed in
						place.
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
							<span class="dark:text-text-dark font-medium text-text">Brightness / Exposure</span>
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
							oninput={(event) =>
								updateAndroidExposure(Number(event.currentTarget.value))}
						/>
						<div class="dark:text-text-muted-dark text-xs text-text-muted">
							Uses the phone camera's real exposure compensation. Range:
							{androidCapabilities.exposure_compensation_min} to
							{androidCapabilities.exposure_compensation_max}.
						</div>
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

					{#if !androidCapabilities.processing_modes.includes('hdr')}
						<div
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
						>
							HDR is not exposed by this Android device's camera path, so there is no live HDR
							toggle for this source right now.
						</div>
					{:else}
						<div
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
						>
							{#if androidCapabilities.supports_hdr_extension}
								HDR is available through the phone's vendor camera extension path.
							{:else if androidCapabilities.supports_hdr_scene_mode}
								HDR is available through the phone's Camera2 scene mode path.
							{:else}
								HDR is available through the phone camera, but the exact implementation path is unspecified.
							{/if}
						</div>
					{/if}

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
				{:else}
					<label class="flex flex-col gap-2">
						<div class="flex items-center justify-between gap-3 text-sm">
							<span class="dark:text-text-dark font-medium text-text">Brightness</span>
							<span class="dark:text-text-muted-dark font-mono text-xs text-text-muted">
								{formatValue('brightness', draftSettings.brightness)}
							</span>
						</div>
						<input
							type="range"
							min="-100"
							max="100"
							step="1"
							value={draftSettings.brightness}
							oninput={(event) =>
								updateNumericSetting('brightness', Number(event.currentTarget.value))}
						/>
					</label>

					<label class="flex flex-col gap-2">
						<div class="flex items-center justify-between gap-3 text-sm">
							<span class="dark:text-text-dark font-medium text-text">Contrast</span>
							<span class="dark:text-text-muted-dark font-mono text-xs text-text-muted">
								{formatValue('contrast', draftSettings.contrast)}
							</span>
						</div>
						<input
							type="range"
							min="0.5"
							max="2"
							step="0.05"
							value={draftSettings.contrast}
							oninput={(event) =>
								updateNumericSetting('contrast', Number(event.currentTarget.value))}
						/>
					</label>

					<label class="flex flex-col gap-2">
						<div class="flex items-center justify-between gap-3 text-sm">
							<span class="dark:text-text-dark font-medium text-text">Saturation</span>
							<span class="dark:text-text-muted-dark font-mono text-xs text-text-muted">
								{formatValue('saturation', draftSettings.saturation)}
							</span>
						</div>
						<input
							type="range"
							min="0"
							max="2"
							step="0.05"
							value={draftSettings.saturation}
							oninput={(event) =>
								updateNumericSetting('saturation', Number(event.currentTarget.value))}
						/>
					</label>

					<label class="flex flex-col gap-2">
						<div class="flex items-center justify-between gap-3 text-sm">
							<span class="dark:text-text-dark font-medium text-text">Gamma</span>
							<span class="dark:text-text-muted-dark font-mono text-xs text-text-muted">
								{formatValue('gamma', draftSettings.gamma)}
							</span>
						</div>
						<input
							type="range"
							min="0.5"
							max="2"
							step="0.05"
							value={draftSettings.gamma}
							oninput={(event) =>
								updateNumericSetting('gamma', Number(event.currentTarget.value))}
						/>
					</label>

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
				{/if}
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
