<script lang="ts">
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import {
		backendHealthy,
		getBackendHttpBase,
		machineHttpBaseUrlFromWsUrl,
		requestBackendRestart,
		waitForBackend
	} from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { machineDowntime } from '$lib/stores/machineDowntime.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Power from '@lucide/svelte/icons/power';
	import WifiOff from '@lucide/svelte/icons/wifi-off';
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

<Modal open={!healthy && !machineDowntime.deliberate} title="Backend Unavailable">
	<div class="flex flex-col gap-4">
		<div class="flex items-start gap-3">
			<div
				class="flex h-9 w-9 shrink-0 items-center justify-center border border-danger/25 bg-danger-soft text-[#B11618]"
			>
				<WifiOff size={18} />
			</div>
			<div class="min-w-0 flex-1">
				{#if restarting}
					<div class="text-sm text-ink">
						The backend is restarting. Waiting for it to come back online...
					</div>
					<div class="mt-3 flex items-center gap-2 text-xs text-ink-muted">
						<Spinner size={14} />
						Reconnecting...
					</div>
				{:else}
					<div class="text-sm text-ink">
						The sorter backend is not responding. This could mean the service has crashed, is still
						starting up, or the network connection was lost.
					</div>
					<div class="mt-2 text-sm text-ink-muted">
						Check that the machine is powered on and the backend service is running.
					</div>
				{/if}
			</div>
		</div>

		{#if !restarting}
			<div class="flex items-center justify-end gap-2 border-t border-line pt-3">
				<button
					type="button"
					onclick={() => void restartBackend()}
					class="inline-flex items-center gap-1.5 border border-line bg-well px-3 py-1.5 text-sm font-medium text-ink transition-colors hover:bg-surface"
				>
					<Power size={14} />
					Restart Backend
				</button>
				<button
					type="button"
					disabled={checking}
					onclick={() => void retryNow()}
					class="inline-flex items-center gap-1.5 border border-primary/30 bg-primary-soft px-3 py-1.5 text-sm font-medium text-ink transition-colors hover:bg-primary-soft disabled:opacity-50"
				>
					<RefreshCw size={14} class={checking ? 'animate-spin' : ''} />
					Check Connection
				</button>
			</div>
		{/if}
	</div>
</Modal>
