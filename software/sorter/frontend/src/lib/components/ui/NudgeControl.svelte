<!--
	docs/components.md#nudge. Turn or move something by a set amount, one press
	at a time, as one small control: a button on the left, the amount in the
	middle, a button on the right (`‹ 10° ›`). The amount is a button too, with
	a caret: it opens a popover with the presets and a number to type, so how
	far each press goes is set where the press is. Like a SegmentedControl it is
	one outline with a 1px line between its parts and no gap.

	`value` is the amount (bind it); `onnudge` gets the side that was pressed
	and does the moving. `busy` is the side whose move is running: it shows the
	Spinner at full strength, and the other side is disabled until it is done.
	`onchange` gets an amount the person chose, to save it.

	<NudgeControl
		bind:value={step}
		label="Turn the channel"
		leftLabel="Turn the channel 10° counterclockwise"
		rightLabel="Turn the channel 10° clockwise"
		onnudge={(side) => turn(side)}
	/>
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Popover from './Popover.svelte';
	import SegmentedControl from './SegmentedControl.svelte';
	import Input from './Input.svelte';
	import Tooltip from './Tooltip.svelte';
	import Spinner from './Spinner.svelte';

	type Side = 'left' | 'right';

	let {
		value = $bindable(),
		presets = [10, 180],
		unit = '°',
		max = 360,
		label,
		leftLabel,
		rightLabel,
		amountLabel = 'Each press moves',
		busy = null,
		disabled = false,
		onnudge,
		onchange
	}: {
		// How far each press goes, in `unit`.
		value: number;
		// The amounts offered in the popover, besides typing one.
		presets?: number[];
		unit?: string;
		// The largest amount that can be typed; any amount above 0 up to it.
		max?: number;
		// The accessible name of the whole control.
		label: string;
		// What each button does, in words: its name and its tooltip.
		leftLabel: string;
		rightLabel: string;
		// The popover's heading, and the amount button's name.
		amountLabel?: string;
		// The side whose move is running.
		busy?: Side | null;
		disabled?: boolean;
		onnudge: (side: Side) => void;
		// An amount the person chose (a preset or a typed number), once per choice.
		onchange?: (value: number) => void;
	} = $props();

	let open = $state(false);
	// What is in the number field. Only a good amount becomes `value`.
	let draft = $state<number | null>(untrack(() => value));

	const isGood = (n: number | null | undefined): n is number =>
		typeof n === 'number' && Number.isFinite(n) && n > 0 && n <= max;
	const invalid = $derived(!isGood(draft));

	// Each time the popover opens, the field starts at the current amount.
	$effect(() => {
		if (open) draft = untrack(() => value);
	});

	function choose(next: number) {
		if (next === value) return;
		value = next;
		onchange?.(next);
	}

	function typed(next: number) {
		if (isGood(next)) choose(next);
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && isGood(draft)) {
			event.preventDefault();
			open = false;
		}
	}

	const presetOptions = $derived(presets.map((p) => ({ value: String(p), label: `${p}${unit}` })));
</script>

{#snippet side(which: Side)}
	{@const text = which === 'left' ? leftLabel : rightLabel}
	{@const running = busy === which}
	<Tooltip {text} placement="bottom">
		{#snippet children(props)}
			<button
				{...props}
				type="button"
				aria-label={text}
				aria-busy={running || undefined}
				disabled={disabled || (busy !== null && !running)}
				onclick={() => !running && onnudge(which)}
				class="inline-flex w-(--size-control-sm) items-center justify-center text-ink transition-colors hover:bg-hover focus-visible:-outline-offset-2 active:bg-pressed disabled:pointer-events-none disabled:opacity-45
					{running ? 'pointer-events-none' : ''}"
			>
				{#if running}
					<Spinner size={14} />
				{:else if which === 'left'}
					<ChevronLeft size={16} />
				{:else}
					<ChevronRight size={16} />
				{/if}
			</button>
		{/snippet}
	</Tooltip>
{/snippet}

<div
	role="group"
	aria-label={label}
	class="inline-flex h-(--size-control-sm) shrink-0 items-stretch overflow-hidden rounded-button border border-line-strong bg-field"
>
	{@render side('left')}
	<Popover bind:open label={amountLabel} width="14rem" placement="bottom">
		{#snippet trigger(props)}
			<button
				{...props}
				type="button"
				aria-label="{amountLabel}: {value}{unit}. Change"
				class="group inline-flex items-center gap-1 border-x border-line-strong px-(--pad-control-sm) text-sm font-medium text-ink transition-colors hover:bg-hover focus-visible:-outline-offset-2 active:bg-pressed aria-expanded:bg-hover"
			>
				<span class="num">{value}{unit}</span>
				<ChevronDown
					size={12}
					class="shrink-0 text-ink-faint transition-colors group-hover:text-ink group-aria-expanded:text-ink"
				/>
			</button>
		{/snippet}
		<div class="flex flex-col gap-3">
			<div class="text-sm font-medium text-ink">{amountLabel}</div>
			<SegmentedControl
				label={amountLabel}
				size="sm"
				full
				value={String(value)}
				options={presetOptions}
				onchange={(next) => {
					choose(Number(next));
					draft = Number(next);
					open = false;
				}}
			/>
			<div class="flex flex-col gap-1.5">
				<Input
					type="number"
					size="sm"
					step="any"
					{unit}
					{invalid}
					aria-label="Another amount"
					bind:value={draft}
					oninput={(event) => typed(event.currentTarget.valueAsNumber)}
					{onkeydown}
				/>
				{#if invalid}
					<p class="text-sm text-danger-ink">Any amount above 0, up to {max}{unit}.</p>
				{/if}
			</div>
		</div>
	</Popover>
	{@render side('right')}
</div>
