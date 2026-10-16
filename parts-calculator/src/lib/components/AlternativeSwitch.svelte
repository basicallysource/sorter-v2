<script lang="ts">
	// One button per way of building a slot the machine has two answers for (the
	// Orange Pi housing). Picking one swaps them in place, no reload. See
	// $lib/alternatives.svelte.
	//
	// `assembly` narrows it to the alternative that assembly is one of, drawn
	// small, for the row in the parts list that stands for that slot.
	import { ALTERNATIVES, alternativeStore, chooseAlternative } from '$lib/alternatives.svelte';

	let { assembly }: { assembly?: string } = $props();

	const selected = $derived(alternativeStore.selected);
	const shown = $derived(
		assembly ? ALTERNATIVES.filter((a) => a.options.some((o) => o.assembly === assembly)) : ALTERNATIVES
	);
	const small = $derived(!!assembly);
</script>

{#each shown as alt (alt.id)}
	<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events (the row this sits in opens the assembly on click, so the click must stop here) -->
	<div class="flex flex-wrap items-center gap-x-3 gap-y-2" onclick={(e) => e.stopPropagation()}>
		{#if !small}<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">{alt.label}</span>{/if}
		<div class="flex">
			{#each alt.options as o, i (o.id)}
				<button
					class="setup-button-secondary {small ? 'h-7 px-2 text-xs' : 'h-9 px-3 text-sm'} {i > 0 ? 'border-l-0' : ''} {selected[alt.id] === o.id ? 'setup-button-primary' : ''}"
					aria-pressed={selected[alt.id] === o.id}
					onclick={() => selected[alt.id] !== o.id && chooseAlternative(alt.id, o.id)}>{o.label}</button>
			{/each}
		</div>
		{#if !small}<span class="text-xs text-text-muted">which housing the list, totals and tree count</span>{/if}
	</div>
{/each}
