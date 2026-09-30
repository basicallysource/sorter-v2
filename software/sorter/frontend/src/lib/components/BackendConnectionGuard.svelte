<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import {
		backendHealthy,
		getBackendHttpBase,
		machineHttpBaseUrlFromWsUrl,
		requestBackendRestart,
		waitForBackend
	} from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { machineDowntime } from '$lib/stores/machineDowntime.svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Power from '@lucide/svelte/icons/power';
	import { onMount } from 'svelte';

	// Says so when the backend has been unreachable for a while. Reconnecting
	// the websocket is the MachineManager's job; recovering touches nothing.
	const manager = getMachinesContext();

	const HEALTH_INTERVAL_MS = 3000;
	const OUTAGE_GRACE_MS = 6000;
	const RECOVERY_POLL_MS = 1500;

	let healthy = $state(true);
	let checking = $state(false);
	let restarting = $state(false);
	let firstFailureAt: number | null = null;

	function baseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase();
	}

	async function poll() {
		// A live websocket proves the backend is up without another request.
		if (manager.isLive(manager.selectedMachine) || (await backendHealthy(baseUrl()))) {
			firstFailureAt = null;
			healthy = true;
			restarting = false;
			return;
		}
		firstFailureAt ??= Date.now();
		if (Date.now() - firstFailureAt >= OUTAGE_GRACE_MS) healthy = false;
	}

	async function retryNow() {
		checking = true;
		await poll();
		checking = false;
	}

	async function restartBackend() {
		restarting = true;
		const url = baseUrl();
		if (
			(await requestBackendRestart(url)) &&
			(await waitForBackend(url, { initialDelayMs: RECOVERY_POLL_MS, intervalMs: RECOVERY_POLL_MS }))
		) {
			healthy = true;
			firstFailureAt = null;
		}
		restarting = false;
	}

	onMount(() => {
		void poll();
		const interval = setInterval(() => void poll(), HEALTH_INTERVAL_MS);
		return () => clearInterval(interval);
	});
</script>

<Modal
	open={!healthy && !machineDowntime.deliberate}
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
			the network connection may have been lost.
		</p>
		<p class="mt-2 text-ink-muted">
			Check that the machine is powered on and the backend service is running.
		</p>
	{/if}
	{#snippet footer()}
		{#if !restarting}
			<Button icon={Power} onclick={() => void restartBackend()}>Restart the backend</Button>
			<Button variant="primary" icon={RefreshCw} loading={checking} onclick={() => void retryNow()}>
				Check the connection
			</Button>
		{/if}
	{/snippet}
</Modal>
