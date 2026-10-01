<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Square from '@lucide/svelte/icons/square';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Input from '$lib/components/ui/Input.svelte';

	const MAX_PULSE_DURATION_S = 120;

	type PulseMode = 'duration' | 'degrees';

	let {
		stepperKey,
		keyboardShortcuts,
		pulsing,
		homing,
		canceling,
		stopping,
		pulseMode = $bindable(),
		pulseDuration = $bindable(),
		pulseSpeed = $bindable(),
		pulseDegrees = $bindable(),
		gearRatio,
		onPulse,
		onStop
	}: {
		stepperKey: string;
		keyboardShortcuts: boolean;
		pulsing: Record<string, boolean>;
		homing: boolean;
		canceling: boolean;
		stopping: boolean;
		pulseMode: PulseMode;
		pulseDuration: number;
		pulseSpeed: number;
		pulseDegrees: number;
		gearRatio: number;
		onPulse: (direction: 'cw' | 'ccw') => void;
		onStop: () => void;
	} = $props();
</script>

<!-- Moving a stepper by hand, as one control: the three buttons that move it in
     one outline with a line between them (Stop in the middle, the direction
     that is moving filled with the primary's tint), how far each press goes,
     and how fast. The arrow keys press the outer buttons when shortcuts are on. -->
<div class="flex flex-col gap-4">
	<div
		role="group"
		aria-label="Jog"
		class="grid h-(--size-control-lg) grid-cols-[1fr_auto_1fr] divide-x divide-line-strong overflow-hidden rounded-button border border-line-strong bg-field"
	>
		<button
			type="button"
			aria-label="Counterclockwise"
			onclick={() => onPulse('ccw')}
			disabled={Boolean(pulsing[`${stepperKey}:ccw`]) || homing || canceling}
			class="flex h-full items-center justify-center gap-1.5 text-sm font-medium transition-colors focus-visible:-outline-offset-2 disabled:pointer-events-none disabled:opacity-45
				{pulsing[`${stepperKey}:ccw`] ? 'bg-primary-soft text-primary-ink' : 'text-ink hover:bg-hover'}"
		>
			<ChevronLeft size={18} />CCW
		</button>
		<button
			type="button"
			onclick={onStop}
			disabled={stopping || homing || canceling}
			class="flex h-full items-center justify-center gap-2 px-5 text-sm font-medium text-danger-ink transition-colors hover:bg-danger-soft focus-visible:-outline-offset-2 disabled:pointer-events-none disabled:opacity-45"
		>
			<Square size={12} fill="currentColor" />Stop
		</button>
		<button
			type="button"
			aria-label="Clockwise"
			onclick={() => onPulse('cw')}
			disabled={Boolean(pulsing[`${stepperKey}:cw`]) || homing || canceling}
			class="flex h-full items-center justify-center gap-1.5 text-sm font-medium transition-colors focus-visible:-outline-offset-2 disabled:pointer-events-none disabled:opacity-45
				{pulsing[`${stepperKey}:cw`] ? 'bg-primary-soft text-primary-ink' : 'text-ink hover:bg-hover'}"
		>
			CW<ChevronRight size={18} />
		</button>
	</div>
	{#if keyboardShortcuts}
		<p class="-mt-2 text-sm text-ink-muted">The arrow keys jog it too.</p>
	{/if}

	<div class="flex items-center justify-between gap-3">
		<span class="text-sm font-medium text-ink">Each press moves</span>
		<SegmentedControl
			label="Move by"
			size="sm"
			bind:value={pulseMode}
			options={[
				{ value: 'degrees', label: 'Degrees' },
				{ value: 'duration', label: 'Time' }
			]}
		/>
	</div>
	<div class="grid grid-cols-2 gap-3">
		{#if pulseMode === 'duration'}
			<Input
				type="number"
				min={0.05}
				max={MAX_PULSE_DURATION_S}
				step={0.05}
				bind:value={pulseDuration}
				unit="s"
				aria-label="How long each press runs"
			/>
		{:else}
			<Input
				type="number"
				min={1}
				max={3600}
				step={1}
				bind:value={pulseDegrees}
				unit="°"
				aria-label="Degrees at the output for each press"
			/>
		{/if}
		<Input type="number" min={1} step={50} bind:value={pulseSpeed} unit="steps/s" aria-label="Speed" />
	</div>
	{#if pulseMode === 'degrees' && gearRatio !== 1}
		<p class="num -mt-2 text-sm text-ink-muted">
			Gear ratio {gearRatio.toFixed(2)}:1, so {pulseDegrees}° at the output is
			{(pulseDegrees * gearRatio).toFixed(1)}° at the motor.
		</p>
	{/if}
</div>
