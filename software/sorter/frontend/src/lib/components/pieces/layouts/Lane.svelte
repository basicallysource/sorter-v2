<script lang="ts">
	import Slot from './Slot.svelte';
	import type { Shot } from './model';

	// Pictures in a grid of slots whose columns and rows are given, never
	// counted from the pictures: three pictures or thirty take the same place.
	// What does not fit is a number in the last slot.
	let {
		shots,
		size,
		cols,
		rows = 1,
		selected = null,
		onpick
	}: {
		shots: Shot[];
		// A slot's side, in rem.
		size: number;
		cols: number;
		rows?: number;
		// The chosen picture's key.
		selected?: string | null;
		onpick?: (shot: Shot) => void;
	} = $props();

	const places = $derived(cols * rows);
	// Room for the stroke is the lane's own (its padding), so nothing that
	// holds a lane can cut a stroke off.
	const side = $derived(`calc(${size}rem * var(--slot-scale, 1))`);
	const shown = $derived(shots.length > places ? shots.slice(0, places - 1) : shots);
	const more = $derived(shots.length - shown.length);
</script>

<div
	class="grid shrink-0 gap-1.5 p-0.5"
	style:grid-template-columns="repeat({cols}, {side})"
	style:grid-template-rows="repeat({rows}, {side})"
>
	{#each shown as shot (shot.key)}
		<Slot
			{shot}
			{size}
			selected={selected === shot.key}
			onpick={onpick ? () => onpick(shot) : undefined}
		/>
	{/each}
	{#if more > 0}
		<span
			class="num flex items-center justify-center rounded-item bg-well text-xs text-ink-muted"
			title="{more} more pictures, on the piece's page"
		>
			+{more}
		</span>
	{/if}
</div>
