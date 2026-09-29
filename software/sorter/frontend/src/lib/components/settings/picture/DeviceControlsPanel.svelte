<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import type {
		CameraDeviceProvider,
		UsbCameraControl,
		UsbCameraSettings
	} from '$lib/settings/camera-device-settings';

	let {
		deviceProvider,
		deviceSupported,
		deviceMessage,
		usbControls,
		draftUsbSettings,
		onUpdateUsbNumeric,
		onUpdateUsbBoolean
	}: {
		deviceProvider: CameraDeviceProvider;
		deviceSupported: boolean;
		deviceMessage: string;
		usbControls: UsbCameraControl[];
		draftUsbSettings: UsbCameraSettings;
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

{#if deviceProvider === 'usb-opencv' && deviceSupported && usbControls.length > 0}
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
						<span class="font-mono text-sm text-text-muted">
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
						<div class="text-sm text-text-muted">
							{control.help}
						</div>
					{/if}
				</label>
			{/if}
		{/each}
	{/if}
{:else}
	<div class="border border-dashed border-border bg-surface px-3 py-2 text-sm text-text-muted">
		{deviceMessage || 'This source does not currently expose adjustable real camera controls.'}
	</div>
{/if}
