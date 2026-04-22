<script lang="ts">
	import LegoColorPicker from '$lib/components/LegoColorPicker.svelte';
</script>

<div class="flex flex-col gap-4">
	<div class="text-sm text-text-muted">
		Pick the LEGO color you want to see across the UI. Buttons, focus rings, and active
		highlights will switch immediately — no reload needed.
	</div>
	<LegoColorPicker />
</div>
