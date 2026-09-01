<script lang="ts">
	// Amber triangle marking an unresolved catalog conflict: the docs and the
	// parts calculator disagreed about a fact when their catalogs were merged
	// and it has not been settled against the machine yet. Hover (or tap) pops
	// the specifics instantly: which merge recorded it, what is disputed, and
	// what each catalog claims.
	import Popover from '$lib/components/Popover.svelte';
	import { MERGES, type CatalogConflict } from '$lib/filament';
	import { TriangleAlert } from 'lucide-svelte';
	let { conflicts, size = 18 }: { conflicts?: CatalogConflict[] | null; size?: number } = $props();

	const mergeFor = (id: string) => MERGES.find((m) => m.id === id);

	function fmt(value: unknown): string {
		if (value == null) return 'none';
		if (Array.isArray(value)) {
			if (!value.length) return 'none';
			return value
				.map((v) =>
					v && typeof v === 'object' && 'part' in v
						? `${(v as { qty?: number }).qty ?? 1}× ${(v as { part: string }).part}`
						: String(v)
				)
				.join(' + ');
		}
		return String(value);
	}
</script>

{#if conflicts?.length}
	<Popover label="Unresolved catalog conflict" width="w-72">
		{#snippet trigger({ toggle })}
			<button
				type="button"
				class="inline-flex shrink-0 cursor-help items-center justify-center"
				style="background: var(--color-warning); color: var(--color-warning-dark); height: {size}px; min-width: {size}px"
				aria-label="Unresolved catalog conflict"
				onclick={(e) => {
					e.preventDefault();
					e.stopPropagation();
					toggle();
				}}
			>
				<TriangleAlert size={size - 6} />
			</button>
		{/snippet}
		{#each conflicts as c, i (c.field)}
			{@const merge = mergeFor(c.merge)}
			<div class={i > 0 ? 'mt-2 border-t border-border pt-2' : ''}>
				<p class="font-semibold text-text">
					Conflict · {c.merge}{merge ? ` (${merge.date})` : ''}
				</p>
				{#if c.note}<p class="mt-1">{c.note}</p>{/if}
				<p class="mt-1">
					{#each c.claims as claim, j (claim.source)}{j > 0
							? ' · '
							: ''}<strong>{claim.source}:</strong> {fmt(claim.value)}{/each}
				</p>
			</div>
		{/each}
	</Popover>
{/if}
