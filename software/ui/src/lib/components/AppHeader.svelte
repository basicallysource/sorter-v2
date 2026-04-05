<script lang="ts">
	import { page } from '$app/state';
	import { backendHttpBaseUrl, backendWsBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { Pause, Play } from 'lucide-svelte';
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

<nav class="border-b border-border bg-surface">
	<div class="flex items-center justify-between px-4 py-3 sm:px-6">
		<div class="flex items-center gap-6">
			<a href="/" class="text-xl font-bold font-mono uppercase tracking-tight text-text">Sorter</a>
			<div class="flex gap-1">
				<a
					href="/"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname === '/' ? 'border-b-2 border-[#D01012] text-[#D01012]' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Dashboard
				</a>
				<a
					href="/bins"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname === '/bins' ? 'border-b-2 border-[#D01012] text-[#D01012]' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Bins
				</a>
				<a
					href="/profiles"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname === '/profiles' ? 'border-b-2 border-[#D01012] text-[#D01012]' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Profiles
				</a>
				<a
					href="/settings"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname.startsWith('/settings') ? 'border-b-2 border-[#D01012] text-[#D01012]' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Settings
				</a>
			</div>
		</div>
		<div class="flex items-center gap-2">
			<MachineDropdown />
			<ThemeToggle />
			<button
				onclick={togglePauseResume}
				class="p-2 text-text transition-colors hover:bg-bg"
				title={machineState === 'paused' ? 'Resume' : 'Pause'}
			>
				{#if machineState === 'paused'}
					<Play size={20} />
				{:else}
					<Pause size={20} />
				{/if}
			</button>
		</div>
	</div>
</nav>
