<!--
	docs/color.md#the-primary. The operator's primary color: the LEGO colors
	as a grid of squares, the chosen one ringed in ink, its name under them.
	Each square is a radio, so the arrow keys move through them.
-->
<script lang="ts">
	import { LEGO_COLORS } from '$lib/lego-colors';

	let {
		value = $bindable(),
		// The most columns; fewer when the space is narrower.
		columns = 16,
		onchange
	}: { value: string; columns?: number; onchange?: (id: string) => void } = $props();

	const chosen = $derived(LEGO_COLORS.find((c) => c.id === value));

	function choose(id: string) {
		value = id;
		onchange?.(id);
	}

	function onkeydown(event: KeyboardEvent) {
		// The grid wraps to the space it has, so up and down move by the
		// number of columns actually drawn.
		const grid = event.currentTarget as HTMLElement;
		const drawn = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
		const steps: Record<string, number> = {
			ArrowRight: 1,
			ArrowLeft: -1,
			ArrowDown: drawn,
			ArrowUp: -drawn
		};
		const step = steps[event.key];
		if (!step) return;
		event.preventDefault();
		const index = LEGO_COLORS.findIndex((c) => c.id === value);
		const next = LEGO_COLORS[Math.max(0, Math.min(LEGO_COLORS.length - 1, index + step))];
		choose(next.id);
		grid.querySelector<HTMLElement>(`[data-id="${next.id}"]`)?.focus();
	}
</script>

<div>
	<div
		role="radiogroup"
		aria-label="Primary color"
		tabindex="-1"
		{onkeydown}
		class="grid gap-1"
		style:grid-template-columns="repeat(auto-fill, 1.25rem)"
		style:max-width="calc({columns} * 1.25rem + {columns - 1} * 0.25rem)"
	>
		{#each LEGO_COLORS as color (color.id)}
			{@const on = color.id === value}
			<button
				type="button"
				role="radio"
				aria-checked={on}
				aria-label={color.name}
				title={color.name}
				tabindex={on ? 0 : -1}
				data-id={color.id}
				onclick={() => choose(color.id)}
				class="size-5 rounded-check border border-line {on
					? 'outline-2 outline-offset-1 outline-ink'
					: 'hover:outline-1 hover:outline-offset-1 hover:outline-ink-faint'}"
				style:background-color={color.hex}
			></button>
		{/each}
	</div>
	<p class="mt-3 text-sm text-ink-muted">
		Chosen: <span class="font-medium text-ink">{chosen?.name ?? value}</span>
	</p>
</div>
