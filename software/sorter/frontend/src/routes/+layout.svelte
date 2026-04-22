<script>
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import MachinesProvider from '$lib/components/MachinesProvider.svelte';
	import MachineProvider from '$lib/components/MachineProvider.svelte';
	import BackendConnectionGuard from '$lib/components/BackendConnectionGuard.svelte';
	import { settings } from '$lib/stores/settings';
	import { loadThemeColor } from '$lib/stores/themeColor.svelte';
	import { onMount } from 'svelte';

	let { children } = $props();

	let save_store = false;

	$effect(() => {
		const current = $settings;
		if (save_store) {
			try {
				window.localStorage.setItem('settings', JSON.stringify(current));
			} catch (e) {
				console.error(e);
			}
		}
	});

	$effect(() => {
		if (typeof document !== 'undefined') {
			document.documentElement.className = $settings.theme;
		}
	});

	onMount(() => {
		try {
			const stored = window.localStorage.getItem('settings');
			if (stored) {
				const parsed = JSON.parse(stored);
				settings.set(parsed);
			}
			save_store = true;
		} catch (e) {
			console.error(e);
		}
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
