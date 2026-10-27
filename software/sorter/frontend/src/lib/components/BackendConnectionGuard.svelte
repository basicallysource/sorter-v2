<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import {
		getBackendHttpBase,
		getBackendWsBase,
		machineHttpBaseUrlFromWsUrl,
		requestBackendRestart
	} from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { machineDowntime } from '$lib/stores/machineDowntime.svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Power from '@lucide/svelte/icons/power';

	// Says so when the machine's websocket has been down for a while. The
	// MachineManager reconnects on its own; nothing here polls.
	const manager = getMachinesContext();

	const OUTAGE_GRACE_MS = 6000;
	const RESTART_WAIT_MS = 90_000;

	const connected = $derived(manager.selectedMachine?.status === 'connected');
	let outage = $state(false);
	let restarting = $state(false);

	$effect(() => {
		if (connected) {
			outage = false;
			restarting = false;
			return;
		}
		const timer = setTimeout(() => (outage = true), OUTAGE_GRACE_MS);
		return () => clearTimeout(timer);
	});

	function wsUrl(): string {
		return manager.selectedMachine?.url ?? `${getBackendWsBase()}/ws`;
	}

	function retryNow() {
		manager.connect(wsUrl(), { force: true });
	}

	async function restartBackend() {
		restarting = true;
		const machine = manager.selectedMachine;
		const url = machineHttpBaseUrlFromWsUrl(machine?.url) ?? getBackendHttpBase();
		if (await requestBackendRestart(url)) await manager.waitForNewRun(machine, RESTART_WAIT_MS);
		restarting = false;
	}
</script>

<Modal
	open={outage && !machineDowntime.deliberate}
	title="The backend is not responding"
	size="sm"
	dismissible={!restarting}
	status={restarting ? 'Waiting for the backend to come back' : undefined}
>
	{#if restarting}
		<p>The backend is restarting. This closes by itself when it answers again.</p>
	{:else}
		<p>
			The sorter backend is not responding. The service may have crashed or still be starting up, or
			the network connection may have been lost. This closes by itself when it answers again.
		</p>
		<p class="mt-2 text-ink-muted">
			Check that the machine is powered on and the backend service is running.
		</p>
	{/if}
	{#snippet footer()}
		{#if !restarting}
			<Button icon={Power} onclick={() => void restartBackend()}>Restart the backend</Button>
			<Button variant="primary" icon={RefreshCw} onclick={retryNow}>Check the connection</Button>
		{/if}
	{/snippet}
</Modal>
