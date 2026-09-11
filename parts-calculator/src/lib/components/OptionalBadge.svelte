<script lang="ts">
	// The "Optional" marking, one component so a printed part and a bought one
	// carry the same tag and the same explanation. Sits in the same cluster as
	// the ChangeStatus priority chip and AlternativeBadge, and like them the tag
	// is the trigger for the sentence that explains it.
	import Badge from '$lib/components/Badge.svelte';
	import Popover from '$lib/components/Popover.svelte';

	// `value` so a caller can pass the flag straight through and render nothing
	// when it is false, the way AlternativeBadge takes its own field.
	let { value, detail = null }: { value?: boolean | null; detail?: string | null } = $props();
</script>

{#if value}
	<Popover label="Optional item" width="w-64">
		{#snippet trigger({ toggle, open })}
			<Badge
				as="button"
				variant="warning"
				class="cursor-help"
				aria-expanded={open}
				aria-label="Optional item"
				onclick={(e: MouseEvent) => {
					e.preventDefault();
					e.stopPropagation();
					toggle();
				}}>Optional</Badge>
		{/snippet}
		<p class="font-semibold text-text">Optional</p>
		<!-- The flag marks the item, it does not remove it from anything: the
		     quantities, the weights and the costs all still include it. -->
		<p class="mt-1">
			{detail ?? 'The build works without this one. It is still counted in the quantities and the totals, so take it off your own order if you are skipping it.'}
		</p>
	</Popover>
{/if}
