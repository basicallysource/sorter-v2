<script lang="ts">
	// The "Turn before printing" marking: a part whose STL is not exported the
	// way it prints. Sits in the same cluster as RequiredColorBadge, and like it
	// the tag is the trigger for the sentence that explains it, with a picture
	// of the part on the plate when the catalog has one. Renders nothing for a
	// part that prints as the file comes.
	import Badge from '$lib/components/Badge.svelte';
	import { Popover } from '$lib/popover';
	import { printOrientation, type Part } from '$lib/filament';

	let { part }: { part: Pick<Part, 'name' | 'attributes'> } = $props();
	const o = $derived(printOrientation(part));
</script>

{#if o}
	<Popover label="Print orientation" width="20rem">
		{#snippet trigger({ toggle, props })}
			<Badge
				as="button"
				variant="warning"
				class="cursor-help"
				{...props}
				aria-label="Turn before printing: {o.value}"
				onclick={(e: MouseEvent) => {
					e.preventDefault();
					e.stopPropagation();
					toggle();
				}}>Turn before printing</Badge>
		{/snippet}
		<p class="font-semibold text-text">Print it like this</p>
		<p class="mt-1">{o.value}</p>
		{#if o.image_url}
			<img class="mt-2 w-full border border-border" src={o.image_url} alt="{part.name} on the plate, the way it prints" loading="lazy" />
		{/if}
		<p class="mt-1">The file does not sit this way, so turn it on the plate before you slice.</p>
	</Popover>
{/if}
