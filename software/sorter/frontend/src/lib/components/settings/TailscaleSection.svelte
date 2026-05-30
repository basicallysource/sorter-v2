<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import { Wifi, WifiOff } from 'lucide-svelte';

	const machine = getMachineContext();

	type TailscaleStatus = {
		installed: boolean;
		connected: boolean;
		hostname?: string;
		ipv4?: string;
		tailnet?: string;
		error?: string;
	};

	let status = $state<TailscaleStatus | null>(null);
	let loadError = $state<string | null>(null);
	let authKeyDraft = $state('');
	let applying = $state(false);
	let applyError = $state<string | null>(null);
	let applySuccess = $state(false);

	function httpBase(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	async function loadStatus() {
		loadError = null;
		try {
			const res = await fetch(`${httpBase()}/api/tailscale/status`);
			if (!res.ok) throw new Error(await res.text());
			status = await res.json();
		} catch (e: any) {
			loadError = e.message ?? 'Failed to load Tailscale status';
		}
	}

	async function applyAuthKey() {
		const key = authKeyDraft.trim();
		if (!key) return;
		applying = true;
		applyError = null;
		applySuccess = false;
		try {
			const res = await fetch(`${httpBase()}/api/tailscale/up`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ auth_key: key })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) {
				applyError = data.error ?? 'Failed to apply auth key';
			} else {
				applySuccess = true;
				authKeyDraft = '';
				if (data.status) status = data.status;
			}
		} catch (e: any) {
			applyError = e.message ?? 'Failed to apply auth key';
		} finally {
			applying = false;
		}
	}

	onMount(() => {
		void loadStatus();
	});
</script>

<div class="flex flex-col gap-4">
	<!-- Status row -->
	<div class="border border-border bg-surface px-3 py-3">
		<div class="flex items-center gap-2">
			{#if status?.connected}
				<Wifi size={14} class="text-success" />
				<span class="text-sm font-medium text-text">Connected</span>
				<span class="ml-auto font-mono text-sm text-text-muted">{status.ipv4}</span>
			{:else if status !== null}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">
					{status.installed ? 'Not connected' : 'Tailscale not installed'}
				</span>
			{:else}
				<span class="text-sm text-text-muted">Loading...</span>
			{/if}
		</div>
		{#if status?.connected}
			<div class="mt-2 flex flex-col gap-0.5">
				<div class="text-sm text-text-muted">
					Hostname: <span class="font-mono text-text">{status.hostname}</span>
				</div>
				{#if status.tailnet}
					<div class="text-sm text-text-muted">
						Tailnet: <span class="font-mono text-text">{status.tailnet}</span>
					</div>
				{/if}
			</div>
		{/if}
		{#if status && !status.connected && status.error}
			<div class="mt-1 text-sm text-text-muted">{status.error}</div>
		{/if}
	</div>

	<!-- Auth key input -->
	<div>
		<div class="mb-2 text-sm font-medium text-text">Auth Key</div>
		<div class="flex gap-2">
			<Input
				type="password"
				placeholder="tskey-auth-..."
				bind:value={authKeyDraft}
				class="flex-1 font-mono"
			/>
			<Button
				variant="primary"
				size="sm"
				disabled={!authKeyDraft.trim() || applying}
				loading={applying}
				onclick={() => void applyAuthKey()}
			>
				{applying ? 'Applying...' : 'Apply'}
			</Button>
		</div>
		<div class="mt-1 text-sm text-text-muted">
			Generate an auth key at <span class="font-mono">tailscale.com/admin/settings/keys</span>. The
			machine will join (or switch to) that network immediately.
		</div>
	</div>

	{#if applyError}
		<Alert variant="danger">{applyError}</Alert>
	{/if}
	{#if applySuccess}
		<Alert variant="success">Auth key applied — machine is now connected.</Alert>
	{/if}
	{#if loadError}
		<Alert variant="warning">{loadError}</Alert>
	{/if}
</div>
