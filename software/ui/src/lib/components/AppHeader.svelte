<script lang="ts">
	import { page } from '$app/state';
	import { backendHttpBaseUrl, backendWsBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { Home, Images, Pause, Play, Settings } from 'lucide-svelte';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	let machineState = $state('initializing');

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
	}

	async function fetchState() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/state`);
			if (!res.ok) return;
			const data = await res.json();
			machineState = data.state ?? 'initializing';
		} catch {
			// ignore
		}
	}

	async function togglePauseResume() {
		const endpoint = machineState === 'paused' ? '/resume' : '/pause';
		try {
			await fetch(`${currentBackendBaseUrl()}${endpoint}`, { method: 'POST' });
			await fetchState();
		} catch {
			// ignore
		}
	}

	onMount(() => {
		if (manager.machines.size === 0) {
			manager.connect(`${backendWsBaseUrl}/ws`);
		}
		void fetchState();
		const interval = setInterval(fetchState, 1000);
		return () => clearInterval(interval);
	});
</script>

<div class="mb-4 flex items-center justify-between">
	<a
		href="/"
		class="dark:text-text-dark flex items-center gap-2 text-text transition-colors"
		title="Dashboard"
	>
		<h1 class="text-2xl font-bold">Sorter</h1>
	</a>
	<div class="flex items-center gap-2">
		<MachineDropdown />
		<button
			onclick={togglePauseResume}
			class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
			title={machineState === 'paused' ? 'Resume' : 'Pause'}
		>
			{#if machineState === 'paused'}
				<Play size={24} />
			{:else}
				<Pause size={24} />
			{/if}
		</button>
		<a
			href="/"
			aria-current={page.url.pathname === '/' ? 'page' : undefined}
			class={`p-2 transition-colors ${
				page.url.pathname === '/'
					? 'dark:bg-surface-dark dark:text-text-dark bg-surface text-text'
					: 'dark:text-text-dark dark:hover:bg-surface-dark text-text hover:bg-surface'
			}`}
			title="Home"
		>
			<Home size={24} />
		</a>
		<a
			href="/settings"
			aria-current={page.url.pathname.startsWith('/settings') ? 'page' : undefined}
			class={`p-2 transition-colors ${
				page.url.pathname.startsWith('/settings')
					? 'dark:bg-surface-dark dark:text-text-dark bg-surface text-text'
					: 'dark:text-text-dark dark:hover:bg-surface-dark text-text hover:bg-surface'
			}`}
			title="Settings"
		>
			<Settings size={24} />
		</a>
		<a
			href="/classification-samples"
			aria-current={page.url.pathname.startsWith('/classification-samples') ? 'page' : undefined}
			class={`p-2 transition-colors ${
				page.url.pathname.startsWith('/classification-samples')
					? 'dark:bg-surface-dark dark:text-text-dark bg-surface text-text'
					: 'dark:text-text-dark dark:hover:bg-surface-dark text-text hover:bg-surface'
			}`}
				title="Samples"
			>
			<Images size={24} />
		</a>
	</div>
</div>
