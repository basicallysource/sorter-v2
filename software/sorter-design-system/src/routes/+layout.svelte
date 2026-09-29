<script lang="ts">
	import '../app.css';
	import '@fontsource-variable/ibm-plex-sans';
	import '@fontsource/ibm-plex-mono/400.css';
	import '@fontsource/ibm-plex-mono/500.css';
	// Applies the saved mode and primary color, and keeps them applied.
	import '$lib/theme.svelte';

	let { children } = $props();
</script>

{@render children()}
