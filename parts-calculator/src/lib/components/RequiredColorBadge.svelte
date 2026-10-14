<script lang="ts">
	// The "Required color" marking: a part whose color does a job (the lamp
	// reflector, the rotors and stators the cameras look at). Sits in the same
	// cluster as OptionalBadge, and like it the tag is the trigger for the
	// sentence that explains it. Renders nothing for a part whose color is the
	// builder's to choose.
	import Badge from '$lib/components/Badge.svelte';
	import { Popover } from '$lib/popover';
	import { getBambuColor } from '$lib/bambu-colors';
	import { requiredColor, type Part } from '$lib/filament';

	let { part, sectionId }: { part: Part; sectionId?: string } = $props();
	const req = $derived(requiredColor(part, sectionId));
	const name = $derived(req ? (getBambuColor(req.colorId)?.name ?? req.colorId) : '');
</script>

{#if req}
	<Popover label="Required color" width="16rem">
		{#snippet trigger({ toggle, props })}
			<Badge
				as="button"
				variant="info"
				class="cursor-help"
				{...props}
				aria-label="Required color: {name}"
				onclick={(e: MouseEvent) => {
					e.preventDefault();
					e.stopPropagation();
					toggle();
				}}>Must be {name}</Badge>
		{/snippet}
		<p class="font-semibold text-text">Print it in {name}</p>
		<p class="mt-1">{req.why}</p>
		<p class="mt-1">The color pickers don't change it.</p>
	</Popover>
{/if}
