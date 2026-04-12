<script lang="ts">
	import {
		backendHttpBaseUrl,
		machineHttpBaseUrlFromWsUrl,
		probeBackendConnection,
		requestBackendRestart,
		waitForBackend
	} from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import Modal from '$lib/components/Modal.svelte';
	import { AlertTriangle, RefreshCw, Power, WifiOff } from 'lucide-svelte';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	const HEALTH_INTERVAL_MS = 3000;
	const RECOVERY_POLL_MS = 1500;
	const FAILURE_THRESHOLD = 3;
	const TRANSIENT_OUTAGE_GRACE_MS = 12000;
	const HARD_OUTAGE_GRACE_MS = 6000;
	const HEARTBEAT_STALE_MS = 15000;

	let healthy = $state(true);
	let checking = $state(false);
	let restarting = $state(false);
	let consecutiveFailures = $state(0);
	let firstFailureAt = $state<number | null>(null);

	type HealthCheckResult = {
		backendOk: boolean;
		showUnavailable: boolean;
	};

	function baseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
	}

	function selectedMachineLooksAlive(): boolean {
		const machine = manager.selectedMachine;
		if (!machine || machine.status !== 'connected') return false;
		if (machine.connection.readyState !== WebSocket.OPEN) return false;
		if (machine.lastHeartbeat === null) return true;
		return Date.now() - machine.lastHeartbeat * 1000 < HEARTBEAT_STALE_MS;
	}

	async function checkHealth(): Promise<HealthCheckResult> {
		const status = await probeBackendConnection(baseUrl());
		if (status.backendOk || selectedMachineLooksAlive()) {
			firstFailureAt = null;
			restarting = false;
			return { backendOk: true, showUnavailable: false };
		}

		consecutiveFailures++;
		if (firstFailureAt === null) {
			firstFailureAt = Date.now();
		}

		const outageMs = Date.now() - firstFailureAt;
		const supervisorRecovering =
			status.supervisorOk &&
			(status.restartRequested ||
				status.supervisorState === 'restarting' ||
				!status.backendRunning);

		restarting =
			status.restartRequested ||
			status.supervisorState === 'restarting' ||
			(status.supervisorOk && !status.backendRunning && outageMs >= HARD_OUTAGE_GRACE_MS);

		const graceMs = supervisorRecovering ? TRANSIENT_OUTAGE_GRACE_MS : HARD_OUTAGE_GRACE_MS;
		return {
			backendOk: false,
			showUnavailable: outageMs >= graceMs && consecutiveFailures >= FAILURE_THRESHOLD
		};
	}

	async function poll() {
		const result = await checkHealth();
		if (result.backendOk) {
			consecutiveFailures = 0;
			if (!healthy) {
				healthy = true;
				restarting = false;
			}
		} else if (result.showUnavailable) {
			healthy = false;
		}
	}

	async function retryNow() {
		checking = true;
		const result = await checkHealth();
		checking = false;
		if (result.backendOk) {
			healthy = true;
			consecutiveFailures = 0;
			firstFailureAt = null;
			restarting = false;
		}
	}

	async function restartBackend() {
		restarting = true;
		const currentBaseUrl = baseUrl();
		const restart = await requestBackendRestart(currentBaseUrl);
		if (!restart.ok) {
			restarting = false;
			return;
		}

		const recovered = await waitForBackend(currentBaseUrl, {
			initialDelayMs: RECOVERY_POLL_MS,
			intervalMs: RECOVERY_POLL_MS
		});
		if (recovered) {
			healthy = true;
			consecutiveFailures = 0;
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

<Modal open={!healthy} title="Backend Unavailable">
	<div class="flex flex-col gap-4">
		<div class="flex items-start gap-3">
			<div
				class="flex h-9 w-9 shrink-0 items-center justify-center border border-[#D01012]/25 bg-[#D01012]/[0.08] text-[#B11618]"
			>
				<WifiOff size={18} />
			</div>
			<div>
				{#if restarting}
					<div class="text-sm text-text">
						The backend is restarting. Waiting for it to come back online...
					</div>
					<div class="mt-3 flex items-center gap-2 text-xs text-text-muted">
						<div
							class="h-3.5 w-3.5 animate-spin border-2 border-current border-t-transparent"
							style="border-radius: 50%;"
						></div>
						Reconnecting...
					</div>
				{:else}
					<div class="text-sm text-text">
						The sorter backend is not responding. This could mean the service has
						crashed, is still starting up, or the network connection was lost.
					</div>
					<div class="mt-2 text-sm text-text-muted">
						Check that the machine is powered on and the backend service is running.
					</div>
				{/if}
			</div>
		</div>

		{#if !restarting}
			<div class="flex items-center justify-end gap-2 border-t border-border pt-3">
				<button
					type="button"
					onclick={() => void restartBackend()}
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-surface"
				>
					<Power size={14} />
					Hard Restart Backend
				</button>
				<button
					type="button"
					disabled={checking}
					onclick={() => void retryNow()}
					class="inline-flex items-center gap-1.5 border border-primary/30 bg-primary/[0.06] px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-primary/[0.12] disabled:opacity-50"
				>
					<RefreshCw size={14} class={checking ? 'animate-spin' : ''} />
					Check Connection
				</button>
			</div>
		{/if}
	</div>
</Modal>
