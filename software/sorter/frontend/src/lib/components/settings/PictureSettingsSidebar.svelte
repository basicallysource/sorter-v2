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
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import X from '@lucide/svelte/icons/x';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
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

{#snippet closeAction()}
	<Button variant="ghost" size="sm" icon={X} label="Close the picture settings" onclick={closeSidebar} />
{/snippet}

{#snippet body()}
	<div class="divide-y divide-line">
		{#if !hasCamera}
			<p class="px-(--pad-panel) py-(--pad-row) text-sm text-ink-muted">
				Choose a camera to see these changes live.
			</p>
		{/if}
		{#if error}
			<div class="px-(--pad-panel) py-(--pad-row)"><Alert tone="danger">{error}</Alert></div>
		{/if}
		{#if loading}
			<p class="flex items-center justify-center gap-2 px-(--pad-panel) py-8 text-sm text-ink-muted">
				<Spinner size={16} />
				Loading the picture settings
			</p>
		{:else}
			<CaptureModePanel {role} />
			<DeviceControlsPanel
				{deviceProvider}
				{deviceSupported}
				{deviceMessage}
				{usbControls}
				{draftUsbSettings}
				onUpdateUsbNumeric={updateUsbNumeric}
				onUpdateUsbBoolean={updateUsbBoolean}
			/>
			<OrientationPanel
				{draftSettings}
				onUpdateRotation={updateRotation}
				onUpdateBoolean={updateBooleanSetting}
			/>
			{#if deviceSupported || status}
				<div class="flex flex-col items-start gap-2 px-(--pad-panel) py-(--pad-row)">
					{#if status}<p class="text-sm text-ink-muted">{status}</p>{/if}
					{#if deviceSupported}
						<Button variant="ghost" size="sm" icon={RotateCcw} disabled={saving} onclick={resetCameraToAutoDefaults}>
							Reset the camera to auto
						</Button>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
	{#if !loading}
		<DriftDetection
			{role}
			onAction={() => {
				void loadDeviceSettings();
			}}
		/>
	{/if}
{/snippet}

{#snippet foot()}
	<Button
		variant="ghost"
		icon={Undo2}
		label="Undo the changes"
		disabled={saving || !hasUnsavedChanges()}
		onclick={revertChanges}
	/>
	<Button variant="ghost" icon={RotateCcw} label="Back to the defaults" disabled={saving} onclick={resetToDefaults} />
	<Button variant="primary" class="ml-auto" loading={saving} disabled={!canSave()} onclick={saveSettings}>
		{primaryActionLabel}
	</Button>
{/snippet}

<!-- In a page, a panel of its own; in a dialog (no header), just its sections. -->
{#if showHeader}
	<Panel
		title="Picture"
		flush
		actions={onClose ? closeAction : undefined}
		footer={loading ? undefined : foot}
	>
		{@render body()}
	</Panel>
{:else}
	<div class="flex flex-col">
		{@render body()}
		{#if !loading}
			<div class="flex items-center gap-2 border-t border-line pt-3">{@render foot()}</div>
		{/if}
	</div>
{/if}
