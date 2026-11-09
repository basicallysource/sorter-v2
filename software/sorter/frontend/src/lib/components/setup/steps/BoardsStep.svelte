<!--
	The control boards that answered: each one, the motors it drives, and
	whether together they drive every motor. One board that carries every
	motor is a complete answer. Firmware help names a file only for a board
	whose file is known.
-->
<script lang="ts">
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import type { FoundBoard } from '$lib/api/setup';
	import { boardName, firmwareFile, needsNewerFirmware, socketLabel } from '$lib/setup/boards';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	const discovery = $derived(flow.summary!.discovery);
	const boards = $derived(discovery.boards);
	const missing = $derived(discovery.missing_required_steppers);
	const variants = $derived(flow.summary!.config.chute.variants);
	// What the summary says in sentences of its own; the two this page puts
	// in its own words are left out.
	const issues = $derived(
		discovery.issues.filter(
			(issue) => !issue.startsWith('Missing required steppers') && !issue.startsWith('No control board')
		)
	);
	// A USB servo adapter, or a board that did not answer: what else might be part of the machine.
	const otherDevices = $derived(
		discovery.usb_devices.filter(
			(device) => device.category === 'servo_bus' || device.category === 'unrecognised_controller'
		)
	);

	function variantLabel(key: string | null): string | null {
		return variants.find((variant) => variant.key === key)?.label ?? null;
	}

	const SOCKET_ORDER = ['c_channel_1_rotor', 'c_channel_2_rotor', 'c_channel_3_rotor', 'carousel', 'chute_stepper'];

	function motorsOf(board: FoundBoard): string {
		const motors = board.logical_steppers
			.filter((name) => !name.startsWith('distribution_aux'))
			.sort((a, b) => SOCKET_ORDER.indexOf(a) - SOCKET_ORDER.indexOf(b));
		return motors.length ? motors.map(socketLabel).join(', ') : 'No motors';
	}

	function deviceName(category: string, product: string, servos: number | undefined): string {
		if (category === 'servo_bus') {
			const count = servos ?? 0;
			return `USB servo adapter, ${count} ${count === 1 ? 'servo' : 'servos'}`;
		}
		if (category === 'unrecognised_controller') return `${product}: a board that did not answer`;
		return product || 'USB device';
	}
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if issues.length}
		<Alert tone="warning">
			{#each issues as issue (issue)}<p>{issue}</p>{/each}
		</Alert>
	{/if}

	{#if !boards.length && !flow.loading}
		<Alert
			tone="warning"
			title={discovery.bootloader_board ? 'A control board is waiting for its firmware' : 'No control board answered'}
		>
			{#if discovery.bootloader_board}
				It shows up as a drive called RPI-RP2, as a board does before it has firmware. Open
				<a href="/settings/control-board" class="underline">Settings › Control board</a>, tick Recovery
				flash, pick the newest release and the file made for your board, and flash it. Then look again.
			{:else}
				Check the board's power and its cable. A board that has never been flashed shows up as a drive
				called RPI-RP2 instead: open
				<a href="/settings/control-board" class="underline">Settings › Control board</a> to flash it,
				then look again.
			{/if}
		</Alert>
	{/if}

	<Panel
		title="Found"
		description={boards.length
			? `${boards.length} ${boards.length === 1 ? 'board' : 'boards'} answered.`
			: 'Nothing has answered yet.'}
		flush
	>
		{#snippet actions()}
			<Button size="sm" icon={RefreshCcw} loading={flow.loading} onclick={() => void flow.reload()}>
				Look again
			</Button>
		{/snippet}
		{#if boards.length}
			<ul class="divide-y divide-line">
				{#each boards as board (board.port + board.address)}
					{@const madeFor = variantLabel(board.chute_variant)}
					{@const file = firmwareFile(board)}
					<li class="flex flex-col gap-1 px-(--pad-panel) py-(--pad-row) text-sm">
						<div class="flex flex-wrap items-center gap-2">
							<span class="font-medium text-ink">{boardName(board)}</span>
							{#if board.servo_bus}<Badge>Serial servo bus</Badge>{/if}
							{#if madeFor}<Badge tone="primary">Made for the {madeFor}</Badge>{/if}
						</div>
						<p class="text-ink-muted">Drives {motorsOf(board)}</p>
						<p class="font-mono text-xs text-ink-muted">{board.port}</p>
						{#if needsNewerFirmware(board)}
							<Alert tone="warning" class="mt-2">
								Its firmware is too old to move the door servos. Flash the newest firmware{#if file}
									(the file starting <span class="font-mono">{file}</span>){/if} from
								<a href="/settings/control-board" class="underline">Settings › Control board</a>.
							</Alert>
						{/if}
					</li>
				{/each}
			</ul>
		{:else}
			<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">
				{flow.loading ? 'Looking for boards…' : 'No board has answered.'}
			</p>
		{/if}
	</Panel>

	{#if boards.length}
		{#if missing.length === 0}
			<Alert tone="success">
				{boards.length === 1
					? 'This board drives every motor, so nothing else is needed.'
					: 'Between them, these boards drive every motor.'}
			</Alert>
		{:else}
			<Alert tone="warning" title="Some motors are on no board">
				Nothing found drives {missing.map(socketLabel).join(', ')}. Check that the board for
				{missing.length === 1 ? 'it' : 'them'} is plugged in and powered, then look again.
			</Alert>
		{/if}
	{/if}

	{#if otherDevices.length}
		<Panel title="Other USB devices" flush>
			<ul class="divide-y divide-line">
				{#each otherDevices as device (device.device)}
					<li class="flex flex-col gap-1 px-(--pad-panel) py-(--pad-row) text-sm">
						<span class="text-ink">{deviceName(device.category, device.product, device.servo_count)}</span>
						<span class="font-mono text-xs text-ink-muted">{device.device}</span>
					</li>
				{/each}
			</ul>
		</Panel>
	{/if}
</div>
