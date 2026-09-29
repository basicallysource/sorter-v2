<script lang="ts">
	import '../app.css';
	// The typefaces, each with its mono partner. Only the choice in use is
	// downloaded; the others are declared and wait (src/lib/site/choices.svelte.ts).
	import '@fontsource-variable/ibm-plex-sans';
	import '@fontsource/ibm-plex-mono/400.css';
	import '@fontsource/ibm-plex-mono/500.css';
	import '@fontsource-variable/inter';
	import '@fontsource-variable/jetbrains-mono';
	import '@fontsource-variable/geist';
	import '@fontsource-variable/geist-mono';
	import '@fontsource-variable/instrument-sans';
	import '@fontsource/dm-mono/400.css';
	import '@fontsource/dm-mono/500.css';
	import '@fontsource-variable/figtree';
	import '@fontsource-variable/public-sans';
	import '@fontsource-variable/roboto-mono';
	import '@fontsource-variable/schibsted-grotesk';
	// Applies the saved mode and primary color, and keeps them applied.
	import '$lib/theme.svelte';
	// Applies the choices still open.
	import '$lib/site/choices.svelte';

	let { children } = $props();
</script>

{@render children()}
