<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { onDestroy } from 'svelte';
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
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Save from '@lucide/svelte/icons/save';
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import X from '@lucide/svelte/icons/x';
	import Alert from '$lib/components/ui/Alert.svelte';
	import CaptureModePanel from './picture/CaptureModePanel.svelte';
	import DriftDetection from './picture/DriftDetection.svelte';
	import DeviceControlsPanel from './picture/DeviceControlsPanel.svelte';
	import OrientationPanel from './picture/OrientationPanel.svelte';

	let {
		role,
		label,
		source = null,
		hasCamera = true,
		showHeader = true,
		primaryActionLabel = 'Save',
		allowPrimaryActionWithoutChanges = false,
		onSaved,
		onClose,
		onPreviewChange
	}: {
		role: CameraRole;
		label: string;
		source?: number | string | null;
		hasCamera?: boolean;
		showHeader?: boolean;
		primaryActionLabel?: string;
		allowPrimaryActionWithoutChanges?: boolean;
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

	let devicePreviewRequest = 0;
	const DEVICE_PREVIEW_DEBOUNCE_MS = 180;

	function emitPreview(roleName: CameraRole, saved: PictureSettings, draft: PictureSettings) {
		onPreviewChange?.(roleName, clonePictureSettings(saved), clonePictureSettings(draft));
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

	function currentDevicePayload(): UsbCameraSettings | null {
		if (!deviceSupported || deviceProvider !== 'usb-opencv') return null;
		return cloneUsbCameraSettings(draftUsbSettings);
	}

	function savedDevicePayload(): UsbCameraSettings | null {
		if (!deviceSupported || deviceProvider !== 'usb-opencv') return null;
		return cloneUsbCameraSettings(savedUsbSettings);
	}

	function applyDeviceResponse(data: CameraDeviceSettingsResponse) {
		deviceProvider =
			data.provider === 'usb-opencv' || data.provider === 'none' ? data.provider : 'network-stream';
		deviceSupported = Boolean(data.supported);
		deviceMessage = data.message ?? '';

		if (deviceProvider === 'usb-opencv') {
			const controls = normalizeUsbCameraControls(data.controls);
			usbControls = controls;
			const normalized = normalizeUsbCameraSettings(data.settings, controls);
			savedUsbSettings = normalized;
			draftUsbSettings = cloneUsbCameraSettings(normalized);
			return;
		}

		usbControls = [];
		savedUsbSettings = {};
		draftUsbSettings = {};
	}

	async function loadLocalSettings() {
		const res = await fetch(`${getBackendHttpBase()}/api/cameras/picture-settings/${role}`);
		if (!res.ok) throw new Error(await res.text());
		const data = await res.json();
		const normalized = normalizePictureSettings(data.settings ?? DEFAULT_PICTURE_SETTINGS);
		savedSettings = normalized;
		draftSettings = clonePictureSettings(normalized);
	}

	async function loadDeviceSettings() {
		const res = await fetch(`${getBackendHttpBase()}/api/cameras/device-settings/${role}`);
		if (!res.ok) throw new Error(await res.text());
		const data = (await res.json()) as CameraDeviceSettingsResponse;
		applyDeviceResponse(data);
	}

	async function loadSettings() {
		invalidateDevicePreview();
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
		clearScheduledDevicePreview();
		const payload = currentDevicePayload();
		if (!payload) return;
		devicePreviewAbortController?.abort();
		const abortController = new AbortController();
		devicePreviewAbortController = abortController;
		const requestId = ++devicePreviewRequest;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/device-settings/${role}/preview`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
				signal: abortController.signal
			});
			if (!res.ok) throw new Error(await res.text());
			const data = (await res.json()) as CameraDeviceSettingsResponse;
			if (requestId !== devicePreviewRequest) return;

			if (deviceProvider === 'usb-opencv') {
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
		const res = await fetch(`${getBackendHttpBase()}/api/cameras/picture-settings/${role}`, {
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
		const res = await fetch(`${getBackendHttpBase()}/api/cameras/device-settings/${role}`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		});
		if (!res.ok) throw new Error(await res.text());
		const data = (await res.json()) as CameraDeviceSettingsResponse;

		if (deviceProvider === 'usb-opencv') {
			const normalized = normalizeUsbCameraSettings(data.settings, usbControls);
			savedUsbSettings = normalized;
			draftUsbSettings = cloneUsbCameraSettings(normalized);
		}
	}

	async function resetCameraToAutoDefaults() {
		if (!deviceSupported) return;
		saving = true;
		error = null;
		status = '';
		invalidateDevicePreview();
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/cameras/device-settings/${role}/reset-defaults`,
				{
					method: 'POST'
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const data = (await res.json()) as CameraDeviceSettingsResponse;
			applyDeviceResponse(data);
			status = data.message ?? 'Camera reset to automatic settings.';
		} catch (e: any) {
			error = e.message ?? 'Failed to reset camera settings';
		} finally {
			saving = false;
		}
	}

	async function saveSettings() {
		saving = true;
		error = null;
		const hadUnsavedChanges = hasUnsavedChanges();
		const isConfirmOnly = !hadUnsavedChanges && allowPrimaryActionWithoutChanges;
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
			} else if (isConfirmOnly) {
				status = 'Picture settings confirmed.';
			}

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
		if (deviceProvider === 'usb-opencv') {
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

		if (deviceProvider === 'usb-opencv') {
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
		if (deviceProvider === 'usb-opencv') {
			draftUsbSettings = cloneUsbCameraSettings(savedUsbSettings);
			queueDevicePreview({ immediate: true });
		}
		status = '';
		error = null;
		emitPreview(role, savedSettings, savedSettings);
		onClose?.();
	}

	function hasUnsavedChanges(): boolean {
		const localChanged = !pictureSettingsEqual(draftSettings, savedSettings);
		if (!deviceSupported) return localChanged;
		if (deviceProvider === 'usb-opencv') {
			return (
				localChanged || !usbCameraSettingsEqual(draftUsbSettings, savedUsbSettings, usbControls)
			);
		}
		return localChanged;
	}

	function canSave(): boolean {
		return hasUnsavedChanges() || allowPrimaryActionWithoutChanges;
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
	class="flex h-full min-w-0 flex-col overflow-hidden border border-line bg-white xl:min-h-[32rem]"
>
	{#if showHeader}
		<div class="border-b border-line bg-surface px-4 py-3">
			<div class="flex items-start justify-between gap-3">
				<div class="flex items-start gap-3">
					<div
						class="flex h-9 w-9 items-center justify-center rounded-full border border-line bg-white text-ink"
					>
						<SlidersHorizontal size={16} />
					</div>
					<div class="min-w-0">
						<div class="text-sm font-semibold text-ink">Picture Settings</div>
					</div>
				</div>
				{#if onClose}
					<button
						onclick={closeSidebar}
						class="inline-flex h-8 w-8 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-white hover:text-ink"
						aria-label="Close picture settings"
					>
						<X size={15} />
					</button>
				{/if}
			</div>
		</div>
	{/if}

	<div class="flex flex-1 flex-col gap-3 bg-white px-4 py-4">
		{#if !hasCamera}
			<div class="border border-dashed border-line bg-surface px-3 py-2 text-sm text-ink-muted">
				Assign a camera to preview these changes live.
			</div>
		{/if}

		{#if error}
			<Alert tone="danger">
				<div class="text-xs font-semibold text-danger-ink">
					Error
				</div>
				<div class="mt-1 text-sm leading-relaxed text-ink">{error}</div>
			</Alert>
		{/if}

		{#if loading}
			<div class="py-10 text-center text-sm text-ink-muted">Loading picture settings...</div>
		{:else}
			<div class="flex flex-col gap-3">
				<div class="flex flex-col gap-3">
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
						{usbControls}
						{draftUsbSettings}
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

				<div class="mt-auto flex flex-col gap-2 border-t border-line pt-3">
					{#if status}
						<div class="text-sm text-ink-muted">{status}</div>
					{/if}

					{#if deviceSupported}
						<button
							onclick={resetCameraToAutoDefaults}
							disabled={saving}
							class="inline-flex w-full cursor-pointer items-center justify-center gap-2 border border-line bg-well px-3 py-2 text-sm font-medium text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
						>
							<RotateCcw size={15} />
							<span>Reset Camera To Auto</span>
						</button>
					{/if}

					<div class="flex items-center gap-2">
					<button
						onclick={revertChanges}
						disabled={saving || !hasUnsavedChanges()}
						title="Revert changes"
						aria-label="Revert changes"
						class="inline-flex h-9 w-9 cursor-pointer items-center justify-center border border-line bg-well text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<Undo2 size={15} />
					</button>
					<button
						onclick={resetToDefaults}
						disabled={saving}
						title="Reset to defaults"
						aria-label="Reset to defaults"
						class="inline-flex h-9 w-9 cursor-pointer items-center justify-center border border-line bg-well text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<RotateCcw size={15} />
					</button>
					<button
						onclick={saveSettings}
						disabled={saving || !canSave()}
						class={`inline-flex flex-1 cursor-pointer items-center justify-center gap-2 border px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${
							canSave()
								? 'border-success bg-success text-white hover:bg-success/90'
								: 'border-line bg-surface text-ink-muted'
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
