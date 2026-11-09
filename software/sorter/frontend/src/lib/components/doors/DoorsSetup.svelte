<!--
	Setting up the layer doors' serial servos, whole: which servo is on which
	door, a number of its own for each new servo, and where each door is shut
	and open. Self-contained: it reads the machine it sits under and keeps
	itself current, quickly while a door is being measured and slowly
	otherwise, never while an action runs and never while the tab is hidden.

	`onchange` gets the doors when they are first read and whenever a door's
	servo, its set-up state or whether it answers changes. `notready` adds what
	the page can do when the hardware is not started; the reason is said here.
	`baseUrl` is the machine's address, when it is not the machine this page is
	under.
-->
<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Hand from '@lucide/svelte/icons/hand';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { releaseDoors, scanServos, type Doors, type DoorLayer } from '$lib/api/doors';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import DoorDetail from './DoorDetail.svelte';
	import { DoorsController, doorStatus, layerName, type DoorStatus } from './controller.svelte';

	let {
		onchange,
		notready,
		baseUrl
	}: {
		onchange?: (doors: Doors) => void;
		notready?: Snippet<[reason: string]>;
		baseUrl?: string;
	} = $props();

	// While a door is being measured its message changes every few seconds.
	const FAST_MS = 700;
	const SLOW_MS = 5000;

	const machine = getMachineContext();
	const controller = new DoorsController(
		() => baseUrl ?? machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase()
	);

	const doors = $derived(controller.doors);
	let selected = $state<number | null>(null);
	// Scanned once when the page opens, so what is plugged in shows without a click.
	let autoScanned = false;
	const scanned = $derived(doors?.scanned ?? false);

	const layer = $derived<DoorLayer | null>(
		selected == null ? null : (doors?.layers.find((l) => l.layer_index === selected) ?? null)
	);
	const servoLayers = $derived(doors?.layers.filter((l) => l.kind === 'servo') ?? []);
	const doneCount = $derived(servoLayers.filter((l) => l.calibrated && l.servo_id != null).length);
	const freeServos = $derived(
		(doors?.servos ?? []).filter((s) => s.state === 'ok' && s.layer_index == null)
	);

	function scan() {
		void controller.run('scan', 'scan', scanServos);
	}

	function releaseAll() {
		void controller.run('release', 'release', releaseDoors, () => ({
			tone: 'info',
			title: 'Every door is let go',
			text: 'They turn freely by hand until one is moved again.'
		}));
	}

	function rowStatus(l: DoorLayer): DoorStatus {
		const search = doors?.search;
		if (search?.layer_index === l.layer_index && search.state === 'running') {
			return { label: 'Measuring', tone: 'warning', line: 'Finding where its door stops.' };
		}
		if (search?.layer_index === l.layer_index && search.state === 'asking') {
			return { label: 'Has a question', tone: 'warning', line: search.message };
		}
		return doorStatus(l);
	}

	// The layer to open first: one being measured, else the first door not set up.
	$effect(() => {
		if (!doors) return;
		if (selected != null && selected < doors.layers.length) return;
		const search = doors.search;
		selected =
			search && (search.state === 'running' || search.state === 'asking')
				? search.layer_index
				: (doors.layers.find((l) => l.kind === 'servo' && !(l.calibrated && l.servo_id != null))
						?.layer_index ?? 0);
	});

	// Scan once the hardware is up, unless a door is being measured or watched.
	$effect(() => {
		if (!doors?.ready || autoScanned || controller.busy) return;
		if (doors.watching || doors.search?.state === 'running') return;
		autoScanned = true;
		scan();
	});

	let lastSignature: string | null = null;
	$effect(() => {
		if (!doors) return;
		const signature = JSON.stringify(
			doors.layers.map((l) => [l.servo_id, l.calibrated, l.available !== false])
		);
		if (signature === lastSignature) return;
		lastSignature = signature;
		onchange?.(doors);
	});

	onMount(() => {
		let gone = false;
		let timer: ReturnType<typeof setTimeout> | null = null;
		let last = 0;
		const tick = async () => {
			if (gone) return;
			const due = controller.searching ? FAST_MS : SLOW_MS;
			if (!document.hidden && Date.now() - last >= due - 50) {
				last = Date.now();
				await controller.refresh();
			}
			if (!gone) timer = setTimeout(tick, FAST_MS);
		};
		const shown = () => {
			if (!document.hidden) last = 0;
		};
		document.addEventListener('visibilitychange', shown);
		void tick();
		return () => {
			gone = true;
			if (timer) clearTimeout(timer);
			document.removeEventListener('visibilitychange', shown);
		};
	});
</script>

<div class="@container flex flex-col gap-(--gap-panels)">
	{#if !doors && !controller.loadError}
		<div class="flex items-center justify-center gap-2 py-10 text-sm text-ink-muted">
			<Spinner /> Reading the doors
		</div>
	{:else if !doors}
		<Alert tone="danger" title="Could not read the doors">
			{controller.loadError}
			{#snippet actions()}
				<Button size="sm" icon={RefreshCw} onclick={() => controller.refresh()}>Try again</Button>
			{/snippet}
		</Alert>
	{:else}
		{#if controller.loadError}
			<Alert tone="warning" title="The machine stopped answering">
				{controller.loadError} What is shown here may be out of date.
			</Alert>
		{/if}

		{#if !doors.ready}
			<Alert tone="warning" title="The doors cannot be set up yet">
				{doors.reason}
				{#if notready}{@render notready(doors.reason ?? '')}{/if}
			</Alert>
		{:else if doors.shared_ids.length}
			<Alert tone="info" title="Several servos answer as number {doors.shared_ids.join(' and ')}">
				New servos all come as number 1, so the machine cannot tell them apart yet. Unplug all but
				one and scan again. Once it has its door it gets a number of its own; then plug in the next.
				{#snippet actions()}
					<Button
						size="sm"
						icon={RefreshCw}
						loading={controller.busy === 'scan'}
						disabled={controller.held}
						onclick={scan}>Scan again</Button
					>
				{/snippet}
			</Alert>
		{:else if scanned && doors.servos.length === 0}
			<Alert tone="warning" title="No servo answers">
				Check the servo cable from the control board to the first servo, and that the servos have
				power, then scan again.
				{#snippet actions()}
					<Button
						size="sm"
						icon={RefreshCw}
						loading={controller.busy === 'scan'}
						disabled={controller.held}
						onclick={scan}>Scan again</Button
					>
				{/snippet}
			</Alert>
		{/if}

		<!-- Narrow, the chosen door comes right under the list of doors. -->
		<div
			class="grid items-start gap-(--gap-panels) @3xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] @3xl:grid-rows-[auto_1fr]"
		>
			<Panel
				title="Doors"
				description="Layer 1 is the top layer. {doneCount} of {servoLayers.length} {servoLayers.length ===
				1
					? 'door is'
					: 'doors are'} set up."
				flush
			>
				{#snippet actions()}
					<Button
						size="sm"
						icon={Hand}
						loading={controller.busy === 'release'}
						disabled={!doors.ready || controller.held}
						onclick={releaseAll}>Let all doors go</Button
					>
				{/snippet}
				{#if controller.errors.release}
					<div class="px-(--pad-panel) pb-3">
						<Alert tone="danger" title="The doors were not let go"
							>{controller.errors.release}</Alert
						>
					</div>
				{:else if controller.notes.release}
					<div class="px-(--pad-panel) pb-3">
						<Alert tone="info" title={controller.notes.release.title}
							>{controller.notes.release.text}</Alert
						>
					</div>
				{/if}
				<ul class="divide-y divide-line border-t border-line">
					{#each doors.layers as l (l.layer_index)}
						{@const status = rowStatus(l)}
						{@const isSelected = doors.ready && selected === l.layer_index}
						<li>
							<button
								type="button"
								disabled={!doors.ready}
								aria-current={isSelected ? 'true' : undefined}
								onclick={() => {
									// Watching for another door's servo ends with that door.
									if (controller.matching !== l.layer_index) controller.matching = null;
									selected = l.layer_index;
								}}
								class="flex w-full items-start gap-3 px-(--pad-panel) py-(--pad-row) text-left transition-colors focus-visible:-outline-offset-2 disabled:cursor-default {isSelected
									? 'bg-primary-soft'
									: 'enabled:hover:bg-hover enabled:active:bg-pressed'}"
							>
								<span class="min-w-0 flex-1">
									<span
										class="block text-sm font-medium {isSelected ? 'text-primary-ink' : 'text-ink'}"
										>{layerName(l.layer_index)}</span
									>
									<span class="block text-sm text-ink-muted">{status.line}</span>
								</span>
								<Badge tone={status.tone}>{status.label}</Badge>
							</button>
						</li>
					{/each}
				</ul>
			</Panel>

			{#if layer && doors.ready}
				<div class="min-w-0 @3xl:col-start-2 @3xl:row-span-2 @3xl:row-start-1">
					<DoorDetail {controller} {layer} />
				</div>
			{/if}

			<Panel
				class="@3xl:col-start-1"
				title="Servos plugged in"
				description={!doors.ready
					? 'Shown once the hardware is started.'
					: freeServos.length
						? `${freeServos.length} ${freeServos.length === 1 ? 'servo has' : 'servos have'} no door yet. Choose a layer and find its servo.`
						: 'Scan after plugging a servo in.'}
				flush
			>
				{#snippet actions()}
					<Button
						size="sm"
						icon={RefreshCw}
						loading={controller.busy === 'scan'}
						disabled={!doors.ready || controller.held}
						onclick={scan}>Scan</Button
					>
				{/snippet}
				{#if controller.errors.scan}
					<div class="px-(--pad-panel) pb-3">
						<Alert tone="danger" title="The scan did not work">{controller.errors.scan}</Alert>
					</div>
				{/if}
				{#if doors.servos.length}
					<ul class="divide-y divide-line border-t border-line">
						{#each doors.servos as servo (servo.servo_id)}
							<li class="flex items-start gap-3 px-(--pad-panel) py-(--pad-row)">
								<span class="min-w-0 flex-1">
									<span class="block text-sm font-medium text-ink">Servo {servo.servo_id}</span>
									<span class="block text-sm text-ink-muted">
										{#if servo.state === 'shared'}
											Several servos answer as this number.
										{:else if servo.state === 'unknown'}
											A kind of servo this machine does not know.
										{:else if servo.layer_index != null}
											Turns {layerName(servo.layer_index).toLowerCase()}'s door
										{:else}
											No door yet
										{/if}
									</span>
								</span>
								{#if servo.state === 'shared'}
									<Badge tone="info">Several</Badge>
								{:else if servo.state === 'unknown'}
									<Badge tone="warning">Unknown kind</Badge>
								{:else if servo.factory_id}
									<Badge tone="primary">New</Badge>
								{:else if servo.model}
									<Badge>{servo.model}</Badge>
								{/if}
							</li>
						{/each}
					</ul>
				{:else if controller.busy === 'scan'}
					<p
						class="flex items-center gap-2 border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted"
					>
						<Spinner size={14} /> Scanning
					</p>
				{:else if doors.ready}
					<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
						{scanned ? 'None answers.' : 'Not scanned yet.'}
					</p>
				{/if}
			</Panel>
		</div>
	{/if}
</div>
