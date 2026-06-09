<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Alert } from '$lib/components/primitives';
	import { Cable } from 'lucide-svelte';

	const machine = getMachineContext();

	type EthernetState = {
		device: string;
		state: string;
		connection: string | null;
		ip?: string | null;
	};
	type NetworkStatus = {
		available: boolean;
		ethernet?: EthernetState[];
	};

	let status = $state<NetworkStatus | null>(null);
	let loadError = $state<string | null>(null);

	function httpBase(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	async function loadStatus() {
		loadError = null;
		try {
			const res = await fetch(`${httpBase()}/api/network/wifi/status`);
			if (!res.ok) throw new Error(await res.text());
			status = await res.json();
		} catch (e: any) {
			loadError = e.message ?? 'Failed to load network status';
		}
	}

	onMount(() => {
		void loadStatus();
	});
</script>

<div class="flex flex-col gap-2">
	{#if status === null}
		<div class="text-sm text-text-muted">Loading...</div>
	{:else if !status.available}
		<Alert variant="info">NetworkManager is not available on this machine.</Alert>
	{:else if (status.ethernet ?? []).length === 0}
		<div class="flex items-center gap-2 text-sm text-text-muted">
			<Cable size={14} />
			<span>No wired network adapter detected.</span>
		</div>
	{:else}
		<div class="flex flex-col border border-border">
			{#each status.ethernet ?? [] as eth (eth.device)}
				<div class="flex items-center gap-2 border-b border-border bg-surface px-3 py-2 last:border-b-0">
					<Cable size={14} class={eth.state.startsWith('connected') ? 'text-success' : 'text-text-muted'} />
					<span class="font-mono text-sm text-text">{eth.device}</span>
					<span class="text-sm text-text-muted">
						{eth.state.startsWith('connected') ? (eth.connection ?? 'connected') : eth.state}
					</span>
					{#if eth.ip}
						<span class="ml-auto font-mono text-sm text-text">{eth.ip}</span>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
	{#if loadError}
		<Alert variant="warning">{loadError}</Alert>
	{/if}
</div>
