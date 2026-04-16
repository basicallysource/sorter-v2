<script lang="ts">
	import { ChevronDown } from 'lucide-svelte';
	import {
		processingModeLabel,
		whiteBalanceModeLabel,
		type AndroidCameraCapabilities,
		type AndroidCameraSettings
	} from '$lib/settings/android-camera-settings';
	import type {
		CameraDeviceProvider,
		UsbCameraControl,
		UsbCameraSettings
	} from '$lib/settings/camera-device-settings';

	let {
		deviceProvider,
		deviceSupported,
		deviceMessage,
		draftAndroidSettings,
		androidCapabilities,
		usbControls,
		draftUsbSettings,
		onUpdateAndroidExposure,
		onUpdateAndroidBoolean,
		onUpdateAndroidProcessingMode,
		onUpdateAndroidWhiteBalance,
		onUpdateUsbNumeric,
		onUpdateUsbBoolean
	}: {
		deviceProvider: CameraDeviceProvider;
		deviceSupported: boolean;
		deviceMessage: string;
		draftAndroidSettings: AndroidCameraSettings;
		androidCapabilities: AndroidCameraCapabilities;
		usbControls: UsbCameraControl[];
		draftUsbSettings: UsbCameraSettings;
		onUpdateAndroidExposure: (value: number) => void;
		onUpdateAndroidBoolean: (key: 'ae_lock' | 'awb_lock', value: boolean) => void;
		onUpdateAndroidProcessingMode: (value: string) => void;
		onUpdateAndroidWhiteBalance: (value: string) => void;
		onUpdateUsbNumeric: (control: UsbCameraControl, value: number) => void;
		onUpdateUsbBoolean: (control: UsbCameraControl, value: boolean) => void;
	} = $props();

	let manualSettingsOpen = $state(false);

	function formatUsbValue(control: UsbCameraControl): string {
		const raw = draftUsbSettings[control.key];
		if (typeof raw === 'boolean') return raw ? 'On' : 'Off';
		if (typeof raw !== 'number') return 'n/a';
		const step = typeof control.step === 'number' ? control.step : 1;
		return step >= 1 ? String(Math.round(raw)) : raw.toFixed(2);
	}
</script>

{#if deviceProvider === 'android-camera-app' && deviceSupported}
	<label class="flex flex-col gap-2">
		<div class="flex items-center justify-between gap-3 text-sm">
			<span class="font-medium text-text">Processing Mode</span>
		</div>
		<select
			class="border border-border bg-surface px-3 py-2 text-sm text-text"
			value={draftAndroidSettings.processing_mode}
			onchange={(event) => onUpdateAndroidProcessingMode(event.currentTarget.value)}
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
				This mode is exposed by the device, but the phone has not reported live image-analysis
				support for it yet.
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
				onclick={() =>
					onUpdateAndroidExposure(
						Math.max(
							androidCapabilities.exposure_compensation_min,
							draftAndroidSettings.exposure_compensation - 1
						)
					)}>&minus;</button
			>
			<input
				class="flex-1"
				type="range"
				min={androidCapabilities.exposure_compensation_min}
				max={androidCapabilities.exposure_compensation_max}
				step="1"
				value={draftAndroidSettings.exposure_compensation}
				oninput={(event) => onUpdateAndroidExposure(Number(event.currentTarget.value))}
			/>
			<button
				type="button"
				class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg"
				onclick={() =>
					onUpdateAndroidExposure(
						Math.min(
							androidCapabilities.exposure_compensation_max,
							draftAndroidSettings.exposure_compensation + 1
						)
					)}>&plus;</button
			>
		</div>
	</label>

	<label class="flex flex-col gap-2">
		<div class="flex items-center justify-between gap-3 text-sm">
			<span class="font-medium text-text">White Balance</span>
		</div>
		<select
			class="border border-border bg-surface px-3 py-2 text-sm text-text"
			value={draftAndroidSettings.white_balance_mode}
			onchange={(event) => onUpdateAndroidWhiteBalance(event.currentTarget.value)}
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
					onchange={(event) => onUpdateAndroidBoolean('ae_lock', event.currentTarget.checked)}
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
					onchange={(event) => onUpdateAndroidBoolean('awb_lock', event.currentTarget.checked)}
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
						onchange={(event) => onUpdateUsbBoolean(control, event.currentTarget.checked)}
					/>
					<span>{control.label}</span>
				</label>
			{:else}
				{@const usbVal =
					typeof draftUsbSettings[control.key] === 'number'
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
							onclick={() => onUpdateUsbNumeric(control, Math.max(usbMin, usbVal - usbStep))}
							>&minus;</button
						>
						<input
							class="flex-1"
							type="range"
							min={usbMin}
							max={usbMax}
							step={usbStep}
							value={usbVal}
							oninput={(event) =>
								onUpdateUsbNumeric(control, Number(event.currentTarget.value))}
						/>
						<button
							type="button"
							class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg"
							onclick={() => onUpdateUsbNumeric(control, Math.min(usbMax, usbVal + usbStep))}
							>&plus;</button
						>
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
	<div class="border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted">
		{deviceMessage || 'This source does not currently expose adjustable real camera controls.'}
	</div>
{/if}
