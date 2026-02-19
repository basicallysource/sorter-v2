<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachinesContext, getMachineContext } from '$lib/machines/context';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import SettingsModal from '$lib/components/SettingsModal.svelte';
	import RuntimeVariablesModal from '$lib/components/RuntimeVariablesModal.svelte';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import { Settings, Wrench, Pause, Play } from 'lucide-svelte';
	import type { components } from '$lib/api/rest';
	import { backendHttpBaseUrl, backendWsBaseUrl } from '$lib/backend';

	type StateResponse = components['schemas']['StateResponse'];

	const manager = getMachinesContext();
	const machine = getMachineContext();

	let settings_open = $state(false);
	let runtime_vars_open = $state(false);
	let machine_state = $state<string>('initializing');

	async function fetchState() {
		try {
			const res = await fetch(`${backendHttpBaseUrl}/state`);
			if (res.ok) {
				const data: StateResponse = await res.json();
				machine_state = data.state;
			}
		} catch {
			// ignore
		}
	}

	async function togglePauseResume() {
		const endpoint = machine_state === 'paused' ? '/resume' : '/pause';
		try {
			await fetch(`${backendHttpBaseUrl}${endpoint}`, { method: 'POST' });
			await fetchState();
		} catch {
			// ignore
		}
	}

	onMount(() => {
		manager.connect(`${backendWsBaseUrl}/ws`);
		fetchState();
		const interval = setInterval(fetchState, 1000);
		return () => clearInterval(interval);
	});
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<div class="mb-4 flex items-center justify-between">
		<h1 class="dark:text-text-dark text-2xl font-bold text-text">Sorter</h1>
		<div class="flex items-center gap-2">
			<MachineDropdown />
			<button
				onclick={togglePauseResume}
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title={machine_state === 'paused' ? 'Resume' : 'Pause'}
			>
				{#if machine_state === 'paused'}
					<Play size={24} />
				{:else}
					<Pause size={24} />
				{/if}
			</button>
			<button
				onclick={() => (runtime_vars_open = true)}
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title="Runtime Variables"
			>
				<Wrench size={24} />
			</button>
			<button
				onclick={() => (settings_open = true)}
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title="Settings"
			>
				<Settings size={24} />
			</button>
		</div>
	</div>

	{#if machine.machine}
		<div class="flex h-[60vh] gap-3">
			<div class="flex min-w-0 flex-1 gap-3">
				<div class="flex-1">
					<CameraFeed camera="feeder" />
				</div>
				<div class="flex flex-1 flex-col gap-3">
					<div class="flex-1">
						<CameraFeed camera="classification_top" />
					</div>
					<div class="flex-1">
						<CameraFeed camera="classification_bottom" />
					</div>
				</div>
			</div>
			<div class="w-64 flex-shrink-0">
				<RecentObjects />
			</div>
		</div>
	{:else}
		<div class="dark:text-text-muted-dark py-12 text-center text-text-muted">
			No machine selected. Connect to a machine in Settings.
		</div>
	{/if}
</div>

<SettingsModal bind:open={settings_open} />
<RuntimeVariablesModal bind:open={runtime_vars_open} />
