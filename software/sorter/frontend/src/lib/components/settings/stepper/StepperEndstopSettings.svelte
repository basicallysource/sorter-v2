<script lang="ts">
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Button from '$lib/components/ui/Button.svelte';

	let {
		loading,
		saving,
		homing,
		canceling,
		endstopActiveHigh = $bindable(),
		onSave
	}: {
		loading: boolean;
		saving: boolean;
		homing: boolean;
		canceling: boolean;
		endstopActiveHigh: boolean;
		onSave: () => void;
	} = $props();
</script>

<div class="flex flex-wrap items-center justify-between gap-3 px-(--pad-panel) py-(--pad-row)">
	<div>
		<Checkbox bind:checked={endstopActiveHigh} disabled={loading || saving || homing || canceling}>
			The endstop is active high
		</Checkbox>
		<p class="mt-0.5 ml-6.5 text-sm text-ink-muted">Flip it if the endstop reads backwards.</p>
	</div>
	<Button loading={saving} disabled={loading || homing || canceling} onclick={onSave}>Save</Button>
</div>
