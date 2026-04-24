<script>
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import MachinesProvider from '$lib/components/MachinesProvider.svelte';
	import MachineProvider from '$lib/components/MachineProvider.svelte';
	import BackendConnectionGuard from '$lib/components/BackendConnectionGuard.svelte';
	import { settings } from '$lib/stores/settings';
	import { loadThemeColor } from '$lib/stores/themeColor.svelte';
	import { persistStoredSettings, restoreStoredSettings } from '$lib/preferences/settings-storage';
	import { onMount } from 'svelte';

	let { children } = $props();

	let save_store = false;

	$effect(() => {
		const current = $settings;
		if (save_store) {
			persistStoredSettings(current);
		}
	});

	$effect(() => {
		if (typeof document !== 'undefined') {
			document.documentElement.className = $settings.theme;
		}
	});

	onMount(() => {
		restoreStoredSettings(settings);
		save_store = true;
		void loadThemeColor();
	});
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<MachinesProvider>
	<MachineProvider>
		<BackendConnectionGuard />
		{@render children()}
	</MachineProvider>
</MachinesProvider>
