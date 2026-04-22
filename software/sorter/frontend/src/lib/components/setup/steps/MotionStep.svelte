<script lang="ts">
	import { Check, Loader2, RotateCcw } from 'lucide-svelte';

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

	const STEPPER_LOGICAL_TO_PHYSICAL: Record<string, string> = {
		c_channel_1: 'c_channel_1_rotor',
		c_channel_2: 'c_channel_2_rotor',
		c_channel_3: 'c_channel_3_rotor',
		carousel: 'carousel',
		chute: 'chute_stepper'
	};

	const STEPPER_BOARD_PORT_LABELS: Record<string, Record<string, string>> = {
		skr_pico: {
			c_channel_1: 'E0',
			c_channel_2: 'X',
			c_channel_3: 'Y',
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

<div class="flex flex-col gap-4">
	{#if hardwareError}
		<div
			class="flex flex-wrap items-center justify-between gap-3 border border-danger bg-danger/10 px-4 py-3 text-sm text-danger"
		>
			<span>{hardwareError}</span>
			<button
				onclick={onInitialize}
				disabled={steppersInitializing}
				class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
			>
				<RotateCcw size={14} />
				Retry
			</button>
		</div>
	{/if}

	{#if steppersInitializing}
		<div
			class="flex items-center gap-3 border border-warning bg-warning/10 px-4 py-3 text-sm text-warning-dark"
		>
			<Loader2 size={18} class="animate-spin" />
			<div class="flex flex-col">
				<span class="font-medium">Powering on steppers…</span>
				<span class="text-xs text-warning-dark/80">
					{homingStep ?? 'Discovering hardware'} — jog controls unlock once the boards are ready.
				</span>
			</div>
		</div>
	{/if}

	<div class="setup-panel px-4 py-3 text-sm text-text-muted">
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div class="min-w-0 flex-1">
				Use very short jogs on an empty machine to verify that each axis turns in the expected
				direction. Reverse any axis that runs the wrong way, then mark this step as done — the
				next step covers endstops and the real homing routine.
			</div>
			<button
				onclick={() => (showStepperWiringHelp = !showStepperWiringHelp)}
				class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text transition-colors"
			>
				{showStepperWiringHelp ? 'Hide wiring help' : 'Show wiring help'}
			</button>
		</div>
	</div>

	{#if showStepperWiringHelp}
		<div class="setup-panel px-4 py-4 text-sm text-text">
			<div class="text-sm font-semibold text-text">SKR Pico stepper wiring</div>
			<div class="mt-1 text-sm text-text-muted">
				Reference for the SKR Pico V1.0 stepper headers used by the feeder and distributor
				boards.
			</div>
			<div class="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
				<a
					href={SKR_PICO_WIRING_DIAGRAM_URL}
					target="_blank"
					rel="noopener noreferrer"
					class="block border border-border bg-white p-1"
				>
					<img
						src={SKR_PICO_WIRING_DIAGRAM_URL}
						alt="SKR Pico V1.0 wiring diagram"
						loading="lazy"
						class="block h-auto w-full"
					/>
				</a>
				<div class="flex flex-col gap-3 text-xs">
					<div>
						<div class="font-semibold tracking-wide text-text uppercase">Sorter mapping</div>
						<table class="mt-2 w-full border-collapse">
							<tbody>
								<tr class="border-b border-border">
									<td class="py-1 text-text">C-Channel 1</td>
									<td class="py-1 font-mono text-text-muted">SKR Feeder · E0</td>
								</tr>
								<tr class="border-b border-border">
									<td class="py-1 text-text">C-Channel 2</td>
									<td class="py-1 font-mono text-text-muted">SKR Feeder · X</td>
								</tr>
								<tr class="border-b border-border">
									<td class="py-1 text-text">C-Channel 3</td>
									<td class="py-1 font-mono text-text-muted">SKR Feeder · Y</td>
								</tr>
								<tr class="border-b border-border">
									<td class="py-1 text-text">Carousel</td>
									<td class="py-1 font-mono text-text-muted">SKR Feeder · Z1</td>
								</tr>
								<tr>
									<td class="py-1 text-text">Chute</td>
									<td class="py-1 font-mono text-text-muted">SKR Distributor · E0</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	{/if}

	<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
		{#each stepperEntries as entry}
			{@const isVerified = !!verifiedSteppers[entry.name]}
			<div
				class={`setup-panel relative p-4 transition-colors ${
					isVerified ? '!border-success !bg-success/10' : ''
				}`}
			>
				{#if isVerified}
					<div
						class="absolute top-2 right-2 inline-flex items-center gap-1 bg-success px-2 py-0.5 text-xs font-semibold tracking-wide text-white uppercase"
					>
						<Check size={12} />
						Verified
					</div>
				{/if}
				<div class="flex items-center justify-between gap-3 pr-20">
					<div class="min-w-0">
						<div class="text-sm font-medium text-text">{entry.label}</div>
						<div class="text-xs text-text-muted">
							{stepperLocationLabel(entry)}
						</div>
					</div>
					<div class={`text-xs ${entry.inverted ? 'text-danger' : 'text-success'}`}>
						{entry.inverted ? 'Inverted' : 'Normal'}
					</div>
				</div>

				<div class="mt-4 flex justify-center">
					<button
						onclick={() => onPulse(entry.name, 'cw')}
						disabled={!steppersLive || !!stepperBusy[`${entry.name}:cw`]}
						class="inline-flex items-center justify-center border border-primary bg-primary px-6 py-1.5 text-xs font-medium text-primary-contrast transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
					>
						Jog
					</button>
				</div>
				<div class="mt-3 text-center text-xs text-text-muted">Which way did it move?</div>
				<div class="mt-1 grid grid-cols-2 gap-2">
					<button
						onclick={() => onRecordObservedDirection(entry, 'cw')}
						disabled={!steppersLive || togglingStepper === entry.name}
						class="setup-button-secondary px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-50"
					>
						Clockwise
					</button>
					<button
						onclick={() => onRecordObservedDirection(entry, 'ccw')}
						disabled={!steppersLive || togglingStepper === entry.name}
						class="setup-button-secondary px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-50"
					>
						Counter-Clockwise
					</button>
				</div>
			</div>
		{/each}
	</div>

	{#if stepperActionError}
		<div class="text-sm text-danger">{stepperActionError}</div>
	{/if}
</div>
