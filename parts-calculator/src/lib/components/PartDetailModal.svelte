<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import PartDetail from '$lib/components/PartDetail.svelte';
	import type { Part, PartVersion } from '$lib/filament';

	// Thin modal wrapper around the shared PartDetail view, used by the parts
	// dashboard and the assembly tab. The standalone /part/<id> page renders the
	// very same PartDetail with variant="page". `colorId` (preview colour) and
	// `version` are controlled by the opener, which seeds them when it sets `part`.
	let {
		open = $bindable(false),
		part,
		colorId = $bindable('ash-gray'),
		version = $bindable<PartVersion | null>(null)
	}: {
		open?: boolean;
		part: Part | null;
		colorId?: string;
		version?: PartVersion | null;
	} = $props();
</script>

<Modal bind:open title={part?.name} bodyScroll={false}>
	{#if part}
		<PartDetail {part} bind:colorId bind:version variant="modal" />
	{/if}
</Modal>
