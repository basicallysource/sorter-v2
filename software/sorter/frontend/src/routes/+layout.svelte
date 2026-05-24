<script lang="ts">
	import './layout.css';
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

	function reportClientError(payload: Record<string, unknown>) {
		const base = `${window.location.protocol}//${window.location.hostname}:8000`;
		fetch(`${base}/api/system/client-error`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		}).catch(() => {});
	}

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

		window.addEventListener('error', (e) => {
			reportClientError({
				type: 'uncaught',
				message: e.message,
				source: e.filename,
				lineno: e.lineno,
				colno: e.colno,
				stack: e.error?.stack
			});
		});

		window.addEventListener('unhandledrejection', (e) => {
			const reason = e.reason;
			reportClientError({
				type: 'unhandledrejection',
				message: reason instanceof Error ? reason.message : String(reason),
				stack: reason instanceof Error ? reason.stack : undefined
			});
		});
	});
</script>

<svelte:head><link rel="icon" type="image/x-icon" href="/favicon.ico" /></svelte:head>

<MachinesProvider>
	<MachineProvider>
		<BackendConnectionGuard />
		{@render children()}
	</MachineProvider>
</MachinesProvider>
