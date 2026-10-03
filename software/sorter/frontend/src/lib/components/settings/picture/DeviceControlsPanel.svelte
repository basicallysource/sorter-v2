<script lang="ts">
	import Minus from '@lucide/svelte/icons/minus';
	import Plus from '@lucide/svelte/icons/plus';
	import Button from '$lib/components/ui/Button.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Disclosure from '$lib/components/ui/Disclosure.svelte';
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
	<Disclosure title="Manual settings" bind:open={manualSettingsOpen}>
		<div class="flex flex-col gap-4 py-2 pr-(--pad-panel) pl-[calc(var(--pad-panel)+1.5rem)]">
			{#each usbControls as control (control.key)}
				{#if control.kind === 'boolean'}
					<Checkbox
						checked={Boolean(draftUsbSettings[control.key])}
						onchange={(event) => onUpdateUsbBoolean(control, (event.currentTarget as HTMLInputElement).checked)}
					>
						{control.label}
					</Checkbox>
				{:else}
					{@const usbVal =
						typeof draftUsbSettings[control.key] === 'number'
							? Number(draftUsbSettings[control.key])
							: Number(control.value ?? control.min ?? 0)}
					{@const usbMin = Number(control.min ?? 0)}
					{@const usbMax = Number(control.max ?? 100)}
					{@const usbStep = Number(control.step ?? 1)}
					<div class="flex flex-col gap-1.5">
						<div class="flex items-center justify-between gap-3 text-sm">
							<label for="usb-{control.key}" class="font-medium text-ink">{control.label}</label>
							<span class="num text-ink-muted">{formatUsbValue(control)}</span>
						</div>
						<div class="flex items-center gap-1">
							<Button
								variant="ghost"
								size="sm"
								icon={Minus}
								label="Less {control.label}"
								onclick={() => onUpdateUsbNumeric(control, Math.max(usbMin, usbVal - usbStep))}
							/>
							<input
								id="usb-{control.key}"
								class="min-w-0 flex-1 accent-primary"
								type="range"
								min={usbMin}
								max={usbMax}
								step={usbStep}
								value={usbVal}
								oninput={(event) => onUpdateUsbNumeric(control, Number(event.currentTarget.value))}
							/>
							<Button
								variant="ghost"
								size="sm"
								icon={Plus}
								label="More {control.label}"
								onclick={() => onUpdateUsbNumeric(control, Math.min(usbMax, usbVal + usbStep))}
							/>
						</div>
						{#if control.help}<p class="text-sm text-ink-muted">{control.help}</p>{/if}
					</div>
				{/if}
			{/each}
		</div>
	</Disclosure>
{:else}
	<p class="px-(--pad-panel) py-(--pad-row) text-sm text-ink-muted">
		{deviceMessage || 'This source offers no camera controls to adjust.'}
	</p>
{/if}
