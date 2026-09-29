<script lang="ts">
	import Panel from '$lib/components/ui/Panel.svelte';

	let {
		label,
		isArc = false,
		statusMessage = ''
	}: {
		label: string;
		isArc?: boolean;
		statusMessage?: string;
	} = $props();
</script>

<Panel
	title="Zone editing"
	description="Adjust the live detection zone for {label}. Nothing changes until you save."
>
	<div class="flex flex-col gap-3 text-sm text-ink-muted">
		{#if statusMessage}
			<p class={statusMessage.startsWith('Error:') ? 'text-danger-ink' : ''}>{statusMessage}</p>
		{/if}
		<h3 class="font-medium text-ink">How to edit</h3>
		{#if isArc}
			<p>
				Drag the Drop start, Drop end, Exit start, Exit end, Center, Inner and Outer handles to shape
				the ring and its zones.
			</p>
			<p>
				Drag the purple Precise start and Precise end handles to set the holding region: the band
				just before the exit where a piece waits while it is classified and the chute aims.
			</p>
			<p>Exit outer pulls only the exit edge inward, when the opening shows the next plate.</p>
			<p>Drag anywhere inside the ring to move the whole zone as one piece.</p>
			<p>The mouse wheel scales the radius finely, and Shift-click sets the section 0 reference.</p>
		{:else}
			<p>Drag the four corner handles to reshape the zone.</p>
			<p>Drag inside it to move the whole zone; the mouse wheel scales it.</p>
		{/if}
	</div>
	{#snippet footer()}
		<p class="mr-auto text-sm text-ink-muted">Save, cancel or reset from the bar above the picture.</p>
	{/snippet}
</Panel>
