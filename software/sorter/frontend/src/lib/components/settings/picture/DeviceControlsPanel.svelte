<script lang="ts">
	import { Tooltip } from '$lib/components/primitives';
	import { Info } from 'lucide-svelte';
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
		onUpdateUsbMenu,
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
		onUpdateUsbMenu: (control: UsbCameraControl, value: number) => void;
		onUpdateUsbBoolean: (control: UsbCameraControl, value: boolean) => void;
	} = $props();

	const usbManualGateByControl: Record<string, string> = {
		exposure: 'auto_exposure',
		white_balance_temperature: 'auto_white_balance',
		focus: 'autofocus'
	};

	function usbAutoGateEnabled(key: string, value: number | boolean | undefined): boolean {
		if (typeof value === 'boolean') return value;
		if (typeof value !== 'number') return false;
		if (key === 'auto_exposure') {
			return [0, 2, 3].includes(Math.round(value));
		}
		return value !== 0;
	}

	function usbControlDisabled(control: UsbCameraControl): boolean {
		if (control.kind === 'button' || control.readonly) return true;
		if (control.inactive) {
			const gateKey = usbManualGateByControl[control.key];
			if (gateKey && !usbAutoGateEnabled(gateKey, draftUsbSettings[gateKey])) return false;
			return true;
		}
		return Boolean(control.disabled);
	}

	function usbNumericValue(control: UsbCameraControl): number {
		const raw = draftUsbSettings[control.key];
		if (typeof raw === 'number') return raw;
		if (typeof control.value === 'number') return control.value;
		if (typeof control.default === 'number') return control.default;
		if (typeof control.options?.[0]?.value === 'number') return control.options[0].value;
		return Number(control.min ?? 0);
	}

	function formatUsbValue(control: UsbCameraControl): string {
		const raw = draftUsbSettings[control.key];
		if (typeof raw === 'boolean') return raw ? 'On' : 'Off';
		if (typeof raw !== 'number') return 'n/a';
		if (control.kind === 'menu') {
			const option = control.options?.find((item) => item.value === raw);
			return option?.label ?? String(raw);
		}
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
		<div class="text-sm text-text-muted">
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
			<span class="font-mono text-sm text-text-muted">
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
	{#each usbControls.filter((c) => c.key !== 'power_line_frequency') as control (control.key)}
		{@const disabled = usbControlDisabled(control)}
		{#if control.kind === 'boolean'}
			<label
				class="flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text {disabled
					? 'opacity-60'
					: ''}"
			>
				<input
					type="checkbox"
					{disabled}
					checked={Boolean(draftUsbSettings[control.key])}
					onchange={(event) => onUpdateUsbBoolean(control, event.currentTarget.checked)}
				/>
				<span class="min-w-0 flex-1">{control.label}</span>
				{#if control.category}
					<span class="truncate text-xs text-text-muted">{control.category}</span>
				{/if}
			</label>
		{:else if control.kind === 'menu' && control.options && control.options.length > 0}
			<label class="flex flex-col gap-2 {disabled ? 'opacity-60' : ''}">
				<div class="flex items-center justify-between gap-3 text-sm">
					<span class="flex items-center gap-1.5 font-medium text-text">
						{control.label}
						{#if control.help}
							<Tooltip text={control.help}>
								<Info size={13} class="text-text-muted" />
							</Tooltip>
						{/if}
					</span>
					<span class="truncate text-sm text-text-muted">
						{formatUsbValue(control)}
					</span>
				</div>
				<select
					class="border border-border bg-surface px-3 py-2 text-sm text-text disabled:cursor-not-allowed"
					{disabled}
					value={String(usbNumericValue(control))}
					onchange={(event) => onUpdateUsbMenu(control, Number(event.currentTarget.value))}
				>
					{#each control.options as option}
						<option value={String(option.value)} disabled={option.disabled}>{option.label}</option>
					{/each}
				</select>
			</label>
		{:else if control.kind === 'button'}
			<label
				class="flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text opacity-60"
			>
				<button
					type="button"
					disabled
					class="inline-flex h-7 cursor-not-allowed items-center border border-border bg-bg px-2 text-xs font-medium text-text-muted"
				>
					{control.label}
				</button>
				{#if control.category}
					<span class="truncate text-xs text-text-muted">{control.category}</span>
				{/if}
			</label>
		{:else}
			{@const usbVal = usbNumericValue(control)}
			{@const usbMin = Number(control.min ?? 0)}
			{@const usbMax = Number(control.max ?? 100)}
			{@const usbStep = Number(control.step ?? 1)}
			<label class="flex flex-col gap-2 {disabled ? 'opacity-60' : ''}">
				<div class="flex items-center justify-between gap-3 text-sm">
					<span class="flex items-center gap-1.5 font-medium text-text">
						{control.label}
						{#if control.help}
							<Tooltip text={control.help}>
								<Info size={13} class="text-text-muted" />
							</Tooltip>
						{/if}
					</span>
					<span class="font-mono text-sm text-text-muted">
						{formatUsbValue(control)}
					</span>
				</div>
				<div class="flex items-center gap-2">
					<button
						type="button"
						{disabled}
						class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
						onclick={() => onUpdateUsbNumeric(control, Math.max(usbMin, usbVal - usbStep))}
						>&minus;</button
					>
					<input
						class="flex-1"
						type="range"
						{disabled}
						min={usbMin}
						max={usbMax}
						step={usbStep}
						value={usbVal}
						oninput={(event) => onUpdateUsbNumeric(control, Number(event.currentTarget.value))}
					/>
					<button
						type="button"
						{disabled}
						class="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border border-border bg-surface text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
						onclick={() => onUpdateUsbNumeric(control, Math.min(usbMax, usbVal + usbStep))}
						>&plus;</button
					>
				</div>
			</label>
		{/if}
	{/each}
{:else}
	<div class="border border-dashed border-border bg-surface px-3 py-2 text-sm text-text-muted">
		{deviceMessage || 'This source does not currently expose adjustable real camera controls.'}
	</div>
{/if}
