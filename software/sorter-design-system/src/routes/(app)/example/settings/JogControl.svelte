<!--
	Moving a stepper by hand, as one control: where it is, the three buttons
	that move it (joined in one track, Stop in the middle), how far each press
	goes and how fast. The arrow keys press the outer buttons when nothing
	that takes typing has focus.
-->
<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Square from '@lucide/svelte/icons/square';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Input from '$lib/components/Input.svelte';

	let { ratio = 10.83 }: { ratio?: number } = $props();

	let position = $state(0);
	let by = $state<'degrees' | 'seconds'>('degrees');
	let amount = $state<number | null>(5);
	let speed = $state(800);
	let moving = $state<'ccw' | 'cw' | null>(null);

	const presets = $derived(by === 'degrees' ? ['1', '5', '15', '90'] : ['0.5', '1', '2', '5']);
	const preset = $derived(presets.includes(String(amount)) ? String(amount) : '');
	const unit = $derived(by === 'degrees' ? '°' : 's');

	function jog(direction: 'ccw' | 'cw') {
		const step = by === 'degrees' ? (amount ?? 0) : (((amount ?? 0) * speed) / (200 * ratio)) * 1.8;
		position = Math.round((position + (direction === 'cw' ? step : -step)) * 10) / 10;
		moving = direction;
		setTimeout(() => (moving = null), 250);
	}

	function onkeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement;
		if (target.closest('input, textarea, [role="listbox"], [role="radiogroup"], [role="tablist"]'))
			return;
		if (event.key === 'ArrowLeft') jog('ccw');
		else if (event.key === 'ArrowRight') jog('cw');
	}

	function setBy(next: 'degrees' | 'seconds') {
		amount = next === 'degrees' ? 5 : 1;
	}
</script>

<svelte:window {onkeydown} />

<div class="flex flex-col gap-5">
	<div class="flex items-end justify-between gap-4">
		<div>
			<div class="label">Position</div>
			<div class="num mt-1 text-3xl leading-none font-medium text-ink">{position.toFixed(1)}°</div>
		</div>
		<div class="text-right text-sm text-ink-muted tabular-nums">
			{(position * ratio).toFixed(1)}° at the motor<br />gear ratio {ratio}:1
		</div>
	</div>

	<div
		role="group"
		aria-label="Jog"
		class="grid grid-cols-[1fr_auto_1fr] gap-1 rounded-button bg-track p-1"
	>
		{#each [{ dir: 'ccw', label: 'Counterclockwise', short: 'CCW' }, { dir: 'stop' }, { dir: 'cw', label: 'Clockwise', short: 'CW' }] as b (b.dir)}
			{#if b.dir === 'stop'}
				<button
					type="button"
					onclick={() => (moving = null)}
					class="flex h-(--size-control-lg) items-center justify-center gap-2 rounded-button-inner bg-thumb px-5 text-sm font-medium text-danger-ink transition-colors hover:bg-thumb/70"
				>
					<Square size={12} fill="currentColor" />Stop
				</button>
			{:else}
				<button
					type="button"
					aria-label={b.label}
					onclick={() => jog(b.dir as 'ccw' | 'cw')}
					class="flex h-(--size-control-lg) items-center justify-center gap-1.5 rounded-button-inner text-sm font-medium transition-colors
						{moving === b.dir ? 'bg-primary text-on-primary' : 'bg-thumb text-ink hover:bg-thumb/70'}"
				>
					{#if b.dir === 'ccw'}<ChevronLeft size={18} />{b.short}{:else}{b.short}<ChevronRight
							size={18}
						/>{/if}
				</button>
			{/if}
		{/each}
	</div>

	<div class="flex flex-col gap-2">
		<div class="flex items-center justify-between gap-3">
			<span class="text-sm font-medium text-ink">Each press moves</span>
			<SegmentedControl
				label="Move by"
				size="sm"
				bind:value={by}
				onchange={setBy}
				options={[
					{ value: 'degrees', label: 'Degrees' },
					{ value: 'seconds', label: 'Seconds' }
				]}
			/>
		</div>
		<div class="flex items-center gap-2">
			<div class="min-w-0 flex-1">
				<SegmentedControl
					label="Amount"
					full
					value={preset}
					onchange={(v) => (amount = Number(v))}
					options={presets.map((p) => ({ value: p, label: `${p}${unit}` }))}
				/>
			</div>
			<Input type="number" bind:value={amount} {unit} step="any" class="w-24 shrink-0" />
		</div>
	</div>

	<div class="flex items-center justify-between gap-3">
		<label for="jog-speed" class="text-sm font-medium text-ink">Speed</label>
		<Input id="jog-speed" type="number" bind:value={speed} unit="steps/s" class="w-36" />
	</div>
</div>
