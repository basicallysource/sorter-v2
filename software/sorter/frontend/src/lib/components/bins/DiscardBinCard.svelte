<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
</script>

<!-- The virtual passthrough "bin": pieces without a matching rule fall through
     every layer's doors into the discard bucket below the machine. It is shown
     so the operator knows the output exists; it is not interactive and has no
     physical slot. -->
<Panel title="Discard bin">
	{#snippet actions()}<Badge>Virtual</Badge>{/snippet}
	<p class="text-sm text-ink-muted">
		Pieces that match no sorting rule, or whose category has no assigned bin, fall through all layer
		doors into the discard bucket below the machine. Empty it by hand when it fills up.
	</p>
</Panel>
