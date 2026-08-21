<script lang="ts">
	// An amber "?" tag marking a part with an unresolved catalog conflict: the
	// docs and the parts calculator disagreed about a fact when their catalogs
	// were merged (2026-08-21) and it has not been settled against the machine
	// yet. Same footprint as AlternativeBadge; amber because it is a real open
	// question, not an error. Hover reads the disputed fact(s).
	import type { CatalogConflict } from '$lib/filament';
	let { conflicts, size = 18 }: { conflicts?: CatalogConflict[] | null; size?: number } = $props();
	const label = $derived((conflicts ?? []).map((c) => c.note ?? c.field).join(' '));
</script>

{#if conflicts?.length}
	<span
		class="inline-flex shrink-0 cursor-help items-center justify-center px-1 font-bold leading-none"
		style="background: var(--color-warning); color: var(--color-warning-dark); height: {size}px; min-width: {size}px; font-size: {(
			size * 0.04
		).toFixed(3)}rem"
		title={label}
		aria-label={label}
	>?</span>
{/if}
