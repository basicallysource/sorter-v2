<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Square from '@lucide/svelte/icons/square';

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

<div class="flex flex-col gap-1">
	<div class="text-sm font-medium text-ink">Controls</div>
	{#if keyboardShortcuts}
		<div class="text-xs text-ink-muted">
			Arrow keys also jog this stepper.
		</div>
	{/if}
</div>

<div class="grid grid-cols-3 gap-2">
	<button
		onclick={() => onPulse('ccw')}
		disabled={Boolean(pulsing[`${stepperKey}:ccw`]) || homing || canceling}
		class="inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-line bg-well px-3 text-sm text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
	>
		<ChevronLeft size={16} />
		CCW
	</button>
	<button
		onclick={onStop}
		disabled={stopping || homing || canceling}
		class="inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-danger bg-danger-soft px-3 text-sm text-danger-ink transition-colors hover:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-50"
	>
		<Square size={14} />
		Stop
	</button>
	<button
		onclick={() => onPulse('cw')}
		disabled={Boolean(pulsing[`${stepperKey}:cw`]) || homing || canceling}
		class="inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 border border-line bg-well px-3 text-sm text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
	>
		CW
		<ChevronRight size={16} />
	</button>
</div>

<div class="flex gap-1">
	<button
		onclick={() => (pulseMode = 'duration')}
		class="flex-1 cursor-pointer border px-2 py-1 text-xs transition-colors {pulseMode === 'duration'
			? 'border-line bg-surface font-medium text-ink'
			: 'border-line bg-transparent text-ink-muted hover:bg-surface'}"
	>
		Duration
	</button>
	<button
		onclick={() => (pulseMode = 'degrees')}
		class="flex-1 cursor-pointer border px-2 py-1 text-xs transition-colors {pulseMode === 'degrees'
			? 'border-line bg-surface font-medium text-ink'
			: 'border-line bg-transparent text-ink-muted hover:bg-surface'}"
	>
		Degrees
	</button>
</div>

<div class="grid grid-cols-2 gap-3">
	{#if pulseMode === 'duration'}
		<label class="text-xs text-ink">
			Duration (s)
			<input
				type="number"
				min="0.05"
				max={MAX_PULSE_DURATION_S}
				step="0.05"
				bind:value={pulseDuration}
				class="mt-1 block w-full border border-line bg-well px-2 py-1.5 text-sm text-ink"
			/>
		</label>
	{:else}
		<label class="text-xs text-ink">
			Degrees (output)
			<input
				type="number"
				min="1"
				max="3600"
				step="1"
				bind:value={pulseDegrees}
				class="mt-1 block w-full border border-line bg-well px-2 py-1.5 text-sm text-ink"
			/>
		</label>
	{/if}
	<label class="text-xs text-ink">
		Speed
		<input
			type="number"
			min="1"
			step="50"
			bind:value={pulseSpeed}
			class="mt-1 block w-full border border-line bg-well px-2 py-1.5 text-sm text-ink"
		/>
	</label>
</div>
{#if pulseMode === 'degrees' && gearRatio !== 1}
	<div class="text-xs text-ink-muted">
		Ratio {gearRatio.toFixed(2)}:1 — {pulseDegrees}° output = {(pulseDegrees * gearRatio).toFixed(1)}° motor
	</div>
{/if}
