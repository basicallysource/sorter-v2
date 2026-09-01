<script lang="ts">
	import { Button } from '$lib/components/primitives';

	// The Save / Reset pair for a settings page. Rendered at both the top and the
	// bottom of long pages so the buttons are reachable without scrolling — one
	// component so the two copies can never drift apart.
	let {
		save,
		reset,
		saving = false,
		dirty = false,
		disabled = false
	}: {
		save: () => void;
		reset: () => void;
		saving?: boolean;
		dirty?: boolean;
		disabled?: boolean;
	} = $props();
</script>

<div class="flex flex-wrap items-center gap-3">
	<Button variant="primary" onclick={save} loading={saving} {disabled}>Save</Button>
	<Button variant="secondary" onclick={reset} disabled={saving || disabled}>Reset to saved</Button>
	{#if dirty}
		<span class="text-sm text-warning-dark">Unsaved changes</span>
	{/if}
</div>
