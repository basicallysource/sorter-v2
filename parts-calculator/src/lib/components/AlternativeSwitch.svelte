<script lang="ts">
	// One button per way of building a slot the machine has two answers for (the
	// Orange Pi housing). The choice is read when the page loads, so picking one
	// reloads it. See $lib/alternatives.
	import { ALTERNATIVES, chooseAlternative, selectedAlternatives } from '$lib/alternatives';

	const selected = selectedAlternatives();
</script>

{#each ALTERNATIVES as alt (alt.id)}
	<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
		<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">{alt.label}</span>
		<div class="flex">
			{#each alt.options as o, i (o.id)}
				<button
					class="setup-button-secondary h-9 px-3 text-sm {i > 0 ? 'border-l-0' : ''} {selected[alt.id] === o.id ? 'setup-button-primary' : ''}"
					aria-pressed={selected[alt.id] === o.id}
					onclick={() => selected[alt.id] !== o.id && chooseAlternative(alt.id, o.id)}>{o.label}</button>
			{/each}
		</div>
		<span class="text-xs text-text-muted">which housing the list, totals and tree count</span>
	</div>
{/each}
