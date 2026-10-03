<script lang="ts">
	import Cable from '@lucide/svelte/icons/cable';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';

	type StepperDirectionEntry = {
		name: string;
		label: string;
		inverted: boolean;
		live_inverted: boolean | null;
		available: boolean;
	};

	type DiscoveredBoard = {
		family: string;
		role: string;
		logical_steppers: string[];
	};

	let {
		hardwareState,
		hardwareError,
		homingStep,
		homingSystem,
		stepperEntries,
		stepperBusy,
		togglingStepper,
		verifiedSteppers,
		stepperActionError,
		boards,
		showStepperWiringHelp = $bindable(),
		onInitialize,
		onPulse,
		onRecordObservedDirection
	}: {
		hardwareState: string;
		hardwareError: string | null;
		homingStep: string | null;
		homingSystem: boolean;
		stepperEntries: StepperDirectionEntry[];
		stepperBusy: Record<string, boolean>;
		togglingStepper: string | null;
		verifiedSteppers: Record<string, boolean>;
		stepperActionError: string | null;
		boards: DiscoveredBoard[];
		showStepperWiringHelp: boolean;
		onInitialize: () => void;
		onPulse: (stepperName: string, direction: 'cw' | 'ccw') => void;
		onRecordObservedDirection: (entry: StepperDirectionEntry, observed: 'cw' | 'ccw') => void;
	} = $props();

	const SKR_PICO_WIRING_DIAGRAM_URL = '/setup/skr-pico-v1.0-headers.png';

	// Each axis from above with an arrow for clockwise, rendered from the CAD
	// (the direction is checked by projecting the arrow, not drawn by eye).
	const DIRECTION_PICTURES: Record<string, string> = {
		c_channel_1_rotor: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-1-w1024-6755b34839a9.jpg',
		c_channel_2_rotor: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-2-w1024-46dedaff70f3.jpg',
		c_channel_3_rotor: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-3-w1024-05be25b17475.jpg',
		carousel: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-4-w1024-b2a8701ff15a.jpg',
		chute_stepper: 'https://assets.basically.website/sorter-docs/setup-motion-chute-w1024-944ab7fcd1a7.jpg',
	};

	const STEPPER_LOGICAL_TO_PHYSICAL: Record<string, string> = {
		c_channel_1: 'c_channel_1_rotor',
		c_channel_2: 'c_channel_2_rotor',
		c_channel_3: 'c_channel_3_rotor',
		c_channel_4: 'carousel',
		carousel: 'carousel',
		chute: 'chute_stepper'
	};

	const STEPPER_BOARD_PORT_LABELS: Record<string, Record<string, string>> = {
		skr_pico: {
			c_channel_1: 'E0',
			c_channel_2: 'X',
			c_channel_3: 'Y',
			c_channel_4: 'Z1',
			carousel: 'Z1',
			chute: 'E0'
		}
	};

	function boardShortLabel(family: string, role: string): string {
		const familyShort =
			family === 'skr_pico'
				? 'SKR'
				: family === 'basically_rp2040'
					? 'Basically'
					: family === 'generic_sorter_interface'
						? 'Generic'
						: family;
		const roleShort = role === 'feeder' ? 'Feeder' : role === 'distribution' ? 'Distributor' : role;
		return `${familyShort} ${roleShort}`;
	}

	function stepperBoardForEntry(entry: StepperDirectionEntry): DiscoveredBoard | null {
		const physical = STEPPER_LOGICAL_TO_PHYSICAL[entry.name];
		if (!physical) return null;
		return boards.find((board) => board.logical_steppers.includes(physical)) ?? null;
	}

	function stepperLocationLabel(entry: StepperDirectionEntry): string {
		const board = stepperBoardForEntry(entry);
		if (!board) {
			return entry.available ? 'Live stepper available' : 'Not connected';
		}
		const boardLabel = boardShortLabel(board.family, board.role);
		const port = STEPPER_BOARD_PORT_LABELS[board.family]?.[entry.name];
		return port ? `${boardLabel} · ${port}` : boardLabel;
	}

	const steppersLive = $derived(hardwareState === 'initialized' || hardwareState === 'ready');
	const steppersInitializing = $derived(
		homingSystem || hardwareState === 'initializing' || hardwareState === 'homing'
	);
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if hardwareError}
		<Alert tone="danger">
			{hardwareError}
			{#snippet actions()}
				<Button size="sm" icon={RotateCcw} disabled={steppersInitializing} onclick={onInitialize}>Retry</Button>
			{/snippet}
		</Alert>
	{/if}
	{#if hardwareState === 'standby' && !hardwareError && !steppersInitializing}
		<Alert tone="info" title="The steppers are off.">
			{#snippet actions()}
				<Button size="sm" onclick={onInitialize}>Power on the steppers</Button>
			{/snippet}
		</Alert>
	{/if}
	{#if steppersInitializing}
		<Alert tone="warning" title="Powering on the steppers…">
			{homingStep ?? 'Finding the hardware'}. The jog buttons unlock once the boards are ready.
		</Alert>
	{/if}

	<Panel
		title="Each axis"
		description="Use very short jogs on an empty machine to check that each axis turns the expected way. Reverse any that runs the wrong way, then mark this step done; the next step covers endstops and homing."
	>
		{#snippet actions()}
			<Button size="sm" variant="ghost" icon={Cable} onclick={() => (showStepperWiringHelp = !showStepperWiringHelp)}>
				<span class="max-sm:sr-only">{showStepperWiringHelp ? 'Hide the wiring' : 'Show the wiring'}</span>
			</Button>
		{/snippet}
		{#if showStepperWiringHelp}
			<div class="mb-4 grid grid-cols-1 gap-4 rounded-control bg-well p-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
				<a href={SKR_PICO_WIRING_DIAGRAM_URL} target="_blank" rel="noopener noreferrer" class="block">
					<img
						src={SKR_PICO_WIRING_DIAGRAM_URL}
						alt="SKR Pico V1.0 wiring diagram"
						loading="lazy"
						class="block h-auto w-full rounded-control"
					/>
				</a>
				<div class="flex flex-col gap-2 text-sm">
					<h3 class="font-medium text-ink">SKR Pico stepper wiring</h3>
					<p class="text-ink-muted">
						The SKR Pico V1.0 stepper headers the feeder and distributor boards use.
					</p>
					<table class="data-table">
						<tbody>
							{#each [['C-channel 1', 'SKR feeder · E0'], ['C-channel 2', 'SKR feeder · X'], ['C-channel 3', 'SKR feeder · Y'], ['Carousel', 'SKR feeder · Z1'], ['Chute', 'SKR distributor · E0']] as [axis, port] (axis)}
								<tr><td>{axis}</td><td class="font-mono text-ink-muted">{port}</td></tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
			{#each stepperEntries as entry}
				{@const isVerified = !!verifiedSteppers[entry.name]}
				{@const picture = DIRECTION_PICTURES[STEPPER_LOGICAL_TO_PHYSICAL[entry.name] ?? entry.name]}
				<section
					class="flex flex-col gap-3 rounded-control p-3 transition-colors {isVerified
						? 'bg-success-soft'
						: 'bg-well'}"
				>
					<div class="flex items-start justify-between gap-3">
						<div class="min-w-0 text-sm">
							<h3 class="font-medium text-ink">{entry.label}</h3>
							<p class="text-ink-muted">{stepperLocationLabel(entry)}</p>
						</div>
						<div class="flex shrink-0 flex-wrap justify-end gap-1.5">
							{#if isVerified}<Badge tone="success">Checked</Badge>{/if}
							<Badge tone={entry.inverted ? 'warning' : undefined}>
								{entry.inverted ? 'Inverted' : 'Normal'}
							</Badge>
						</div>
					</div>
					{#if picture}
						<img
							src={picture}
							alt={`${entry.label} seen from above, with an arrow showing clockwise`}
							loading="lazy"
							class="aspect-4/3 w-full rounded-control object-cover"
						/>
					{/if}
					<Button
						variant="primary"
						class="self-center"
						disabled={!steppersLive || !!stepperBusy[`${entry.name}:cw`]}
						onclick={() => onPulse(entry.name, 'cw')}
					>
						Jog
					</Button>
					<p class="text-center text-sm text-ink-muted">Which way did it turn, seen from above?</p>
					<div class="grid grid-cols-2 gap-2">
						<Button
							disabled={!steppersLive || togglingStepper === entry.name}
							onclick={() => onRecordObservedDirection(entry, 'cw')}
						>
							Clockwise
						</Button>
						<Button
							disabled={!steppersLive || togglingStepper === entry.name}
							onclick={() => onRecordObservedDirection(entry, 'ccw')}
						>
							Counterclockwise
						</Button>
					</div>
				</section>
			{/each}
		</div>
		{#if stepperActionError}<p class="mt-3 text-sm text-danger-ink">{stepperActionError}</p>{/if}
	</Panel>
</div>
