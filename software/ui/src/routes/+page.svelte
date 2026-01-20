<script>
	import { onMount } from 'svelte';
	import { getMachinesContext, getMachineContext } from '$lib/machines/context';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import SettingsModal from '$lib/components/SettingsModal.svelte';
	import { Settings } from 'lucide-svelte';

	const manager = getMachinesContext();
	const machine = getMachineContext();

	let url = $state('ws://localhost:8000/ws');
	let settings_open = $state(false);

	onMount(() => {
		manager.connect(url);
	});

	function handleConnect() {
		manager.connect(url);
	}
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<div class="mb-4 flex items-center justify-between">
		<h1 class="dark:text-text-dark text-2xl font-bold text-text">Sorter UI</h1>
		<button
			onclick={() => (settings_open = true)}
			class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
			title="Settings"
		>
			<Settings size={24} />
		</button>
	</div>

	<section
		class="dark:border-border-dark dark:bg-surface-dark mb-5 border border-border bg-surface p-3"
	>
		<h2 class="dark:text-text-dark mb-2 text-lg font-semibold text-text">Connection</h2>
		<div class="mb-3 flex gap-2">
			<input
				type="text"
				bind:value={url}
				placeholder="ws://host:port/ws"
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark flex-1 border border-border bg-bg p-2 text-text"
			/>
			<button
				onclick={handleConnect}
				class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-4 py-2 text-text hover:bg-bg"
			>
				Connect
			</button>
		</div>

		<h3 class="dark:text-text-dark mb-2 text-base font-medium text-text">
			Connected Machines ({manager.machines.size})
		</h3>
		{#if manager.machines.size === 0}
			<p class="dark:text-text-muted-dark text-text-muted">No machines connected</p>
		{:else}
			<ul class="list-none p-0">
				{#each [...manager.machines.entries()] as [id, m]}
					<li class="mb-1 flex gap-2">
						<button
							onclick={() => manager.selectMachine(id)}
							class="cursor-pointer border px-2 py-1 {id === manager.selectedMachineId
								? 'border-blue-500 bg-blue-500/20 text-blue-500'
								: 'dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border-border bg-bg text-text hover:bg-surface'}"
						>
							{m.identity?.nickname ?? id.slice(0, 8)} ({m.status})
						</button>
						<button
							onclick={() => manager.disconnect(id)}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-2 py-1 text-text hover:bg-surface"
						>
							Disconnect
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	{#if machine.machine}
		<section
			class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-3"
		>
			<h2 class="dark:text-text-dark mb-2 text-lg font-semibold text-text">
				Machine: {machine.machine.identity?.machine_id.slice(0, 8) ?? 'Unknown'}
			</h2>
			<p class="dark:text-text-dark text-text">Status: {machine.machine.status}</p>
			{#if machine.machine.lastHeartbeat}
				<p class="dark:text-text-dark text-text">
					Last heartbeat: {new Date(machine.machine.lastHeartbeat * 1000).toLocaleTimeString()}
				</p>
			{/if}

			<h3 class="dark:text-text-dark mt-4 mb-2 text-base font-medium text-text">Camera Feeds</h3>
			<div class="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-3">
				<CameraFeed camera="feeder" />
				<CameraFeed camera="classification_bottom" />
				<CameraFeed camera="classification_top" />
			</div>
		</section>
	{:else}
		<p class="dark:text-text-muted-dark text-text-muted">No machine selected</p>
	{/if}
</div>

<SettingsModal bind:open={settings_open} />
