<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import Modal from '$lib/components/Modal.svelte';
	import { AlertTriangle, RefreshCw, Power, WifiOff } from 'lucide-svelte';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	const HEALTH_INTERVAL_MS = 3000;
	const RECOVERY_POLL_MS = 1500;

	let healthy = $state(true);
	let checking = $state(false);
	let restarting = $state(false);
	let consecutiveFailures = $state(0);

	function baseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
	}

	async function checkHealth(): Promise<boolean> {
		try {
			const res = await fetch(`${baseUrl()}/health`, { signal: AbortSignal.timeout(4000) });
			return res.ok;
		} catch {
			return false;
		}
	}

	async function poll() {
		const ok = await checkHealth();
		if (ok) {
			consecutiveFailures = 0;
			if (!healthy) {
				healthy = true;
				restarting = false;
			}
		} else {
			consecutiveFailures++;
			if (consecutiveFailures >= 2) {
				healthy = false;
			}
		}
	}

	async function retryNow() {
		checking = true;
		const ok = await checkHealth();
		checking = false;
		if (ok) {
			healthy = true;
			consecutiveFailures = 0;
			restarting = false;
		}
	}

	async function restartBackend() {
		restarting = true;
		try {
			await fetch(`${baseUrl()}/api/system/restart`, {
				method: 'POST',
				signal: AbortSignal.timeout(4000)
			});
		} catch {
			// Expected — the backend may already be shutting down
		}

		// Poll until it comes back
		const maxAttempts = 30;
		let attempt = 0;
		const pollRestart = async () => {
			while (attempt < maxAttempts) {
				attempt++;
				await new Promise((r) => setTimeout(r, RECOVERY_POLL_MS));
				const ok = await checkHealth();
				if (ok) {
					healthy = true;
					consecutiveFailures = 0;
					restarting = false;
					return;
				}
			}
			restarting = false;
		};
		void pollRestart();
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
					Restart Backend
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
