<!--
	A wrong way and the right way, side by side. `on` is the plane the
	examples sit on: the page itself (canvas), or a panel (surface) for
	components that live inside one.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';

	let {
		wrong,
		right,
		wrongNote,
		rightNote,
		on = 'canvas'
	}: {
		wrong: Snippet;
		right: Snippet;
		wrongNote: string;
		rightNote: string;
		on?: 'canvas' | 'surface';
	} = $props();
</script>

<div class="grid gap-x-6 gap-y-8 md:grid-cols-2">
	{#each [{ good: false, body: wrong, note: wrongNote }, { good: true, body: right, note: rightNote }] as side (side.good)}
		<figure class="flex flex-col gap-3">
			<div class="flex-1 {on === 'surface' ? 'rounded-panel bg-surface p-5' : ''}">
				{@render side.body()}
			</div>
			<figcaption class="flex items-start gap-2 text-sm">
				{#if side.good}
					<Check size={16} class="mt-0.5 shrink-0 text-success-ink" />
					<span><span class="font-semibold text-success-ink">Do.</span> {side.note}</span>
				{:else}
					<X size={16} class="mt-0.5 shrink-0 text-danger-ink" />
					<span><span class="font-semibold text-danger-ink">Don't.</span> {side.note}</span>
				{/if}
			</figcaption>
		</figure>
	{/each}
</div>
