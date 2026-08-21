<script lang="ts">
	// The detail-view panel behind the amber "?" badge: what each catalog
	// claimed for the disputed field. Resolving one = fixing the field in
	// slicer/parts.json and deleting the conflict entry there.
	import type { CatalogConflict } from '$lib/filament';
	let { conflicts }: { conflicts?: CatalogConflict[] | null } = $props();

	function fmt(value: unknown): string {
		if (value == null) return 'none';
		if (Array.isArray(value)) {
			if (!value.length) return 'none';
			return value
				.map((v) =>
					v && typeof v === 'object' && 'part' in v
						? `${(v as { qty?: number }).qty ?? 1}\u00d7 ${(v as { part: string }).part}`
						: String(v)
				)
				.join(' + ');
		}
		return String(value);
	}
</script>

{#if conflicts?.length}
	<div
		class="border p-3 text-xs"
		style="border-color: var(--color-warning); background: color-mix(in srgb, var(--color-warning) 12%, transparent)"
	>
		<p class="font-semibold" style="color: var(--color-warning-dark)">
			Unresolved catalog conflict — the docs and the parts calculator disagreed when their
			catalogs were merged (2026-08-21):
		</p>
		<ul class="mt-1.5 space-y-1.5">
			{#each conflicts as c (c.field)}
				<li>
					{#if c.note}<p>{c.note}</p>{/if}
					<p class="mt-0.5 text-text-muted">
						{#each c.claims as claim, i (claim.source)}{i > 0
								? ' \u00b7 '
								: ''}<strong>{claim.source}:</strong> {fmt(claim.value)}{/each}
					</p>
				</li>
			{/each}
		</ul>
	</div>
{/if}
