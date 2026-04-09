<script lang="ts">
	import { page } from '$app/state';
	import { backendHttpBaseUrl, backendWsBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { Home, Pause, Play, RotateCcw } from 'lucide-svelte';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	let machineState = $state('initializing');
	let hardwareState = $state<string>('standby');
	let homingStep = $state<string | null>(null);
	let hardwareError = $state<string | null>(null);

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

	async function fetchSystemStatus() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/status`);
			if (!res.ok) return;
			const data = await res.json();
			hardwareState = data.hardware_state ?? 'standby';
			homingStep = data.homing_step ?? null;
			hardwareError = data.hardware_error ?? null;
		} catch {
			// ignore
		}
	}

	async function homeSystem() {
		try {
			await fetch(`${currentBackendBaseUrl()}/api/system/home`, { method: 'POST' });
			await fetchSystemStatus();
		} catch {
			// ignore
		}
	}

	async function resetSystem() {
		try {
			await fetch(`${currentBackendBaseUrl()}/api/system/reset`, { method: 'POST' });
			await fetchSystemStatus();
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
		void fetchSystemStatus();
		const interval = setInterval(() => {
			void fetchState();
			void fetchSystemStatus();
		}, 1000);
		return () => clearInterval(interval);
	});
</script>

<nav class="border-b border-border bg-surface" style="--header-btn-h: 36px;">
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
					href="/setup"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname.startsWith('/setup') ? 'border-b-2 border-[#D01012] text-[#D01012]' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Setup
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

			{#if hardwareState === 'standby' || hardwareState === 'error'}
				<button
					onclick={homeSystem}
					class="flex items-center gap-1.5 border border-border bg-bg px-3 text-sm font-medium text-text transition-colors hover:bg-surface"
					style="height: var(--header-btn-h);"
					title="Initialize hardware and home all axes"
				>
					<Home size={14} />
					Home
				</button>
			{:else if hardwareState === 'homing'}
				<div class="flex items-center gap-2 px-3 text-sm text-text-muted" style="height: var(--header-btn-h);">
					<div class="h-3.5 w-3.5 animate-spin border-2 border-[#0055BF] border-t-transparent" style="border-radius: 50%;"></div>
					<span class="max-w-[200px] truncate">{homingStep ?? 'Homing...'}</span>
				</div>
			{:else if hardwareState === 'ready'}
				<button
					onclick={homeSystem}
					class="flex items-center gap-1.5 border border-border bg-bg px-3 text-sm font-medium text-text transition-colors hover:bg-surface"
					style="height: var(--header-btn-h);"
					title="Re-home all axes"
				>
					<Home size={14} />
					Re-Home
				</button>
				<button
					onclick={resetSystem}
					class="flex items-center justify-center border border-border bg-surface text-text-muted transition-colors hover:text-text hover:bg-bg"
					style="height: var(--header-btn-h); width: var(--header-btn-h);"
					title="Reset hardware to standby"
				>
					<RotateCcw size={14} />
				</button>
			{/if}

			{#if hardwareError}
				<span class="max-w-[200px] truncate text-xs text-[#D01012]" title={hardwareError}>{hardwareError}</span>
			{/if}

			{#if hardwareState === 'ready'}
				<button
					onclick={togglePauseResume}
					class="flex items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg"
					style="height: var(--header-btn-h); width: var(--header-btn-h);"
					title={machineState === 'paused' ? 'Resume' : 'Pause'}
				>
					{#if machineState === 'paused'}
						<Play size={20} />
					{:else}
						<Pause size={20} />
					{/if}
				</button>
			{/if}
		</div>
	</div>
</nav>
