<script lang="ts">
	import '../app.css';
	import '@fontsource-variable/geist';
	import '@fontsource-variable/geist-mono';
	// Applies the saved mode and primary color, and keeps them applied.
	import '$lib/theme.svelte';

	let { children } = $props();
</script>

{@render children()}
