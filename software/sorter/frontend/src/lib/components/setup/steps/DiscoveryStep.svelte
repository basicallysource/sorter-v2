<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';

	type UsbDeviceCategory = 'controller' | 'servo_bus' | 'unrecognised_controller' | 'unknown';

	type UsbDevice = {
		device: string;
		product: string;
		serial: string | null;
		vid_pid: string | null;
		category: UsbDeviceCategory;
		use_by_default: boolean;
		detail: string;
		family?: string | null;
		role?: string | null;
		device_name?: string | null;
		logical_steppers?: string[];
		servo_count?: number;
	};

	let {
		usbDevices,
		boardsFound,
		bootloaderBoard,
		issues,
		loadingWizard,
		onRescan
	}: {
		usbDevices: UsbDevice[];
		boardsFound: boolean;
		bootloaderBoard: boolean;
		issues: string[];
		loadingWizard: boolean;
		onRescan: () => void;
	} = $props();

	const inUseCount = $derived(usbDevices.filter((device) => device.use_by_default).length);

	function usbCategoryBadge(category: UsbDeviceCategory): {
		label: string;
		tone?: 'success' | 'danger';
	} {
		switch (category) {
			case 'controller':
				return { label: 'Controller', tone: 'success' };
			case 'servo_bus':
				return { label: 'Servo bus', tone: 'success' };
			case 'unrecognised_controller':
				return { label: 'Unrecognised', tone: 'danger' };
			default:
				return { label: 'Unknown' };
		}
	}

	function usbDeviceDisplayName(device: UsbDevice): string {
		if (device.category === 'controller') {
			const name = device.device_name || device.product || 'Control board';
			if (device.role) return `${name} · ${device.role}`;
			return name;
		}
		if (device.category === 'servo_bus') {
			const count = device.servo_count ?? 0;
			return `Waveshare servo bus · ${count} servo${count === 1 ? '' : 's'}`;
		}
		return device.product || 'Serial device';
	}

	function boardFamilyLabel(family: string | null | undefined): string | null {
		switch (family) {
			case 'skr_pico':
				return 'SKR Pico';
			case 'basically_rp2040':
				return 'Basically RP2040';
			case 'generic_sorter_interface':
				return 'Generic SorterInterface';
			default:
				return family ?? null;
		}
	}
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if issues.length}
		<Alert tone="danger">
			{#each issues as issue}<p>{issue}</p>{/each}
		</Alert>
	{/if}

	{#if !boardsFound && !loadingWizard}
		<Alert
			tone="warning"
			title={bootloaderBoard
				? 'The control board is waiting for its firmware.'
				: 'No control board answered.'}
		>
			{#if bootloaderBoard}
				It shows up as a drive called RPI-RP2, which is what a Pico does before it has ever been
				flashed. Open <a href="/settings/control-board" class="underline">Settings > Control board</a>,
				tick <strong>Recovery flash</strong>, pick the newest firmware release (the file for the kit's
				board is <strong>basically-v1-2-distribution</strong>) and flash it. Then come back and rescan.
			{:else}
				On a new machine this usually means the Pico has no firmware yet. Unplug the Pico's USB cable,
				hold down the BOOTSEL button (the white button on top of the Pico), plug the cable back in and
				let go. Then open <a href="/settings/control-board" class="underline">Settings > Control board</a>,
				tick <strong>Recovery flash</strong>, pick the newest firmware release (the file for the kit's
				board is <strong>basically-v1-2-distribution</strong>), flash it, and come back to rescan. If
				the board has been flashed before, check its power and USB cable instead.
			{/if}
		</Alert>
	{/if}

	<Panel
		title="USB devices"
		description="{inUseCount} {inUseCount === 1 ? 'controller' : 'controllers'} in use."
		flush
	>
		{#snippet actions()}
			<Button size="sm" icon={RefreshCcw} loading={loadingWizard} onclick={onRescan}>Rescan</Button>
		{/snippet}
		{#if usbDevices.length}
			<ul class="divide-y divide-line">
				{#each usbDevices as device}
					{@const badge = usbCategoryBadge(device.category)}
					{@const familyLabel = boardFamilyLabel(device.family)}
					<li
						class="flex items-start gap-3 px-(--pad-panel) py-(--pad-row) {device.use_by_default
							? 'bg-success-soft'
							: ''}"
					>
						<span
							class="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-check {device.use_by_default
								? 'bg-success text-on-success'
								: 'border border-line-strong'}"
							title={device.use_by_default ? 'In use' : 'Not used'}
						>
							{#if device.use_by_default}<Check size={12} strokeWidth={3} />{/if}
						</span>
						<div class="min-w-0 flex-1 text-sm">
							<div class="flex flex-wrap items-center gap-2">
								<span class="font-medium text-ink">{usbDeviceDisplayName(device)}</span>
								<Badge tone={badge.tone}>{badge.label}</Badge>
								{#if familyLabel}<Badge>{familyLabel}</Badge>{/if}
							</div>
							<div class="mt-0.5 font-mono text-xs text-ink-muted">
								{device.device}{device.vid_pid ? ` · ${device.vid_pid}` : ''}
							</div>
							{#if device.detail}<p class="mt-1 text-ink-muted">{device.detail}</p>{/if}
						</div>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">No USB devices found.</p>
		{/if}
	</Panel>
</div>
