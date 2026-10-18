<script lang="ts">
	import Checkbox from '$lib/components/ui/Checkbox.svelte';

	// The endstop's polarity. The parent places the Save button.
	let {
		busy,
		endstopActiveHigh = $bindable()
	}: {
		// Loading, saving, homing or canceling: nothing here changes meanwhile.
		busy: boolean;
		endstopActiveHigh: boolean;
	} = $props();
</script>

<div class="px-(--pad-panel) py-(--pad-row)">
	<Checkbox bind:checked={endstopActiveHigh} disabled={busy}>The endstop is active high</Checkbox>
	<p class="mt-0.5 ml-6.5 text-sm text-ink-muted">Flip it if the endstop reads backwards.</p>
</div>
