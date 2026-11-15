<script lang="ts">
	// The "No version id" marking: a part too small to carry the engraved id
	// (catalog/engrave.py found no face the four characters fit on), so its
	// download is the plain file either way. Same cluster and same pattern as
	// PrintOrientationBadge. Renders nothing for a part that can be stamped.
	import Badge from '$lib/components/Badge.svelte';
	import { Popover } from '$lib/popover';
	import type { Part } from '$lib/filament';

	let { part }: { part: Pick<Part, 'stl' | 'stamped'> } = $props();
</script>

{#if part.stl && !part.stamped?.length}
	<Popover label="No version id" width="16rem">
		{#snippet trigger({ toggle, props })}
			<Badge
				as="button"
				variant="info"
				class="cursor-help"
				{...props}
				aria-label="No version id: too small to engrave"
				onclick={(e: MouseEvent) => {
					e.preventDefault();
					e.stopPropagation();
					toggle();
				}}>No version id</Badge>
		{/snippet}
		<p class="font-semibold text-text">No version id</p>
		<p class="mt-1">Too small to engrave the 4-character id on. The download is the plain file, and the print can't be looked up by id later.</p>
	</Popover>
{/if}
