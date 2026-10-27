<script lang="ts">
	import House from '@lucide/svelte/icons/house';
	import Button from '$lib/components/ui/Button.svelte';

	// Homing, as the buttons at the top of a motor's panel: find the endstop, or
	// cancel and stop every stepper if the wrong motor moves.
	let {
		loading,
		saving,
		homing,
		canceling,
		onHome,
		onCancel
	}: {
		loading: boolean;
		saving: boolean;
		homing: boolean;
		canceling: boolean;
		onHome: () => void;
		onCancel: () => void;
	} = $props();
</script>

<div class="flex flex-wrap items-center gap-2">
	<Button icon={House} loading={homing} disabled={loading || saving || canceling} onclick={onHome}>
		Home to the endstop
	</Button>
	<Button variant="danger" loading={canceling} disabled={!homing} onclick={onCancel}>Cancel</Button>
</div>
