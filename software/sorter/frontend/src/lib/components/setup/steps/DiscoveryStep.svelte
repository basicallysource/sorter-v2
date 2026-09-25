<script lang="ts">
	import { Cpu, RefreshCcw } from 'lucide-svelte';

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

	function usbCategoryBadge(category: UsbDeviceCategory): { label: string; className: string } {
		switch (category) {
			case 'controller':
				return {
					label: 'Controller',
					className: 'bg-success/10 text-success'
				};
			case 'servo_bus':
				return {
					label: 'Servo Bus',
					className: 'bg-success/10 text-success'
				};
			case 'unrecognised_controller':
				return {
					label: 'Unrecognised',
					className: 'bg-danger/10 text-danger'
				};
			default:
				return {
					label: 'Unknown',
					className: 'bg-border/60 text-text-muted'
				};
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

<div class="flex flex-col gap-4">
	<div class="flex flex-wrap items-center gap-3 text-sm">
		<div class="setup-panel inline-flex items-center gap-2 px-3 py-2 text-text">
			<Cpu size={14} />
			<span>{inUseCount} controller{inUseCount === 1 ? '' : 's'} in use</span>
		</div>
		<button
			onclick={onRescan}
			disabled={loadingWizard}
			class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
		>
			<RefreshCcw size={14} class={loadingWizard ? 'animate-spin' : ''} />
			Rescan
		</button>
	</div>

	{#if issues.length}
		<div class="border border-danger bg-danger/10 px-4 py-3 text-sm text-danger">
			{#each issues as issue}
				<div>{issue}</div>
			{/each}
		</div>
	{/if}

	{#if !boardsFound && !loadingWizard}
		<div class="setup-panel flex flex-col gap-2 px-4 py-3 text-sm text-text">
			{#if bootloaderBoard}
				<div class="font-medium">The control board is waiting for its firmware.</div>
				<div class="text-text-muted">
					It shows up as a drive called RPI-RP2, which is what a Pico does before it has ever been
					flashed. Open <a href="/settings/control-board" class="underline">Settings → Control board</a>,
					tick <strong>Recovery flash</strong>, pick the newest firmware release and flash it. Then
					come back here and rescan.
				</div>
			{:else}
				<div class="font-medium">No control board answered.</div>
				<div class="text-text-muted">
					On a new machine this usually means the Pico has no firmware yet. Unplug the Pico's USB
					cable, hold down the BOOTSEL button (the white button on top of the Pico), plug the cable back in and let go.
					Then open <a href="/settings/control-board" class="underline">Settings → Control board</a>,
					tick <strong>Recovery flash</strong>, pick the newest firmware release and flash it, and
					come back here to rescan. If the board has been flashed before, check its power and USB
					cable instead.
				</div>
			{/if}
		</div>
	{/if}

	{#if usbDevices.length}
		<div class="flex flex-col gap-2">
			{#each usbDevices as device}
				{@const badge = usbCategoryBadge(device.category)}
				{@const familyLabel = boardFamilyLabel(device.family)}
				<label
					class={`setup-panel flex items-start gap-3 px-4 py-3 transition-colors ${
						device.use_by_default ? 'border-success/40 bg-success/[0.08]' : ''
					}`}
				>
					<input
						type="checkbox"
						checked={device.use_by_default}
						disabled
						class="mt-1 h-4 w-4 accent-success"
					/>
					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<span class="text-sm font-medium text-text">
								{usbDeviceDisplayName(device)}
							</span>
							<span
								class={`px-2 py-0.5 text-xs font-semibold tracking-wide uppercase ${badge.className}`}
							>
								{badge.label}
							</span>
							{#if familyLabel}
								<span
									class="bg-border/40 px-2 py-0.5 text-xs font-semibold tracking-wide text-text-muted uppercase"
								>
									{familyLabel}
								</span>
							{/if}
						</div>
						<div class="mt-1 font-mono text-xs text-text-muted">
							{device.device}{device.vid_pid ? ` · ${device.vid_pid}` : ''}
						</div>
						{#if device.detail}
							<div class="mt-1 text-sm text-text-muted">{device.detail}</div>
						{/if}
					</div>
				</label>
			{/each}
		</div>
	{/if}
</div>
