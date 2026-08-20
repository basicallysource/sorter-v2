<script lang="ts">
	import { PLATES, type Plate } from '$lib/filament';
	import { Download } from 'lucide-svelte';

	let { highlightPartId = null }: { highlightPartId?: string | null } = $props();

	function hits(plate: Plate): boolean {
		return !!highlightPartId && plate.parts.some((pp) => pp.part_id === highlightPartId);
	}
</script>

{#if PLATES.length === 0}
	<p class="text-sm text-text-muted">No build plates yet. Drop pre-arranged .3mf files in <code class="font-mono">slicer/plates/</code>.</p>
{:else}
	<div class="grid gap-4 sm:grid-cols-2">
		{#each PLATES as plate (plate.id)}
			<div class="setup-card-shell border p-3 {hits(plate) ? 'ring-2 ring-primary' : ''}">
				<div class="mb-2 flex flex-wrap gap-2">
					{#each plate.thumbs as t}
						<img src={t} alt="plate preview" class="h-24 w-24 border border-border bg-[var(--color-bg)] object-contain" />
					{/each}
				</div>
				<div class="mb-2 flex flex-wrap gap-1.5">
					{#each plate.parts as pp}
						<span class="border px-1.5 py-0.5 text-xs {pp.part_id && pp.part_id === highlightPartId ? 'border-primary bg-primary/10 text-primary' : 'border-border text-text-muted'}">
							{pp.count}× {pp.name}
						</span>
					{/each}
				</div>
				<a class="setup-button-secondary inline-flex h-9 items-center gap-2 px-3 text-sm font-semibold" href={plate.download} download>
					<Download size={14} /> Download plate (.3mf)
				</a>
			</div>
		{/each}
	</div>
{/if}
