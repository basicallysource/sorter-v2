<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import LasercutDetail from '$lib/components/LasercutDetail.svelte';
	import type { LaserCutPart } from '$lib/lasercut';

	// Thin modal wrapper around the shared LasercutDetail view, mirroring
	// PartDetailModal / HardwareDetailModal.
	let {
		open = $bindable(false),
		part
	}: {
		open?: boolean;
		part: LaserCutPart | null;
	} = $props();
</script>

<Modal bind:open title={part?.name} maxW="max-w-4xl">
	{#if part}
		<LasercutDetail {part} />
	{/if}
</Modal>
