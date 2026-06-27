<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import { Wifi, Lock, RefreshCw, Check } from 'lucide-svelte';

	const machine = getMachineContext();

	type Adapter = {
		device: string;
		state: string;
		connected: boolean;
		active_ssid: string | null;
		ip: string | null;
	};
	type Network = {
		ssid: string;
		signal: number;
		security: string;
		secured: boolean;
		active: boolean;
	};
	type WifiStatus = {
		available: boolean;
		adapters: Adapter[];
		networks: Network[];
		error?: string;
	};

	let status = $state<WifiStatus | null>(null);
	let loadError = $state<string | null>(null);
	let scanning = $state(false);

	// Which adapter to connect with. Defaults to a connected radio, else the first.
	let selectedDevice = $state<string>('');
	// Which network's inline password/connect row is open.
	let expandedSsid = $state<string | null>(null);
	let passwordDraft = $state('');
	let connecting = $state(false);
	let connectError = $state<string | null>(null);
	let connectSuccess = $state<string | null>(null);

	function httpBase(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function applyStatus(s: WifiStatus) {
		status = s;
		if (!selectedDevice && s.adapters.length > 0) {
			selectedDevice = (s.adapters.find((a) => a.connected) ?? s.adapters[0]).device;
		}
	}

	async function loadStatus() {
		loadError = null;
		try {
			const res = await fetch(`${httpBase()}/api/wifi/status`);
			if (!res.ok) throw new Error(await res.text());
			applyStatus(await res.json());
		} catch (e: any) {
			loadError = e.message ?? 'Failed to load WiFi status';
		}
	}

	async function rescan() {
		scanning = true;
		loadError = null;
		try {
			const res = await fetch(`${httpBase()}/api/wifi/scan`, { method: 'POST' });
			if (!res.ok) throw new Error(await res.text());
			applyStatus(await res.json());
		} catch (e: any) {
			loadError = e.message ?? 'Scan failed';
		} finally {
			scanning = false;
		}
	}

	function toggleExpand(net: Network) {
		if (expandedSsid === net.ssid) {
			expandedSsid = null;
			return;
		}
		expandedSsid = net.ssid;
		passwordDraft = '';
		connectError = null;
		connectSuccess = null;
	}

	async function connect(net: Network) {
		connecting = true;
		connectError = null;
		connectSuccess = null;
		try {
			const res = await fetch(`${httpBase()}/api/wifi/connect`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					ssid: net.ssid,
					password: net.secured ? passwordDraft : null,
					device: selectedDevice || null
				})
			});
			const data = await res.json();
			if (!data.ok) {
				connectError = data.error ?? 'Failed to connect';
			} else {
				connectSuccess = data.message ?? `Connected to ${net.ssid}`;
				expandedSsid = null;
				passwordDraft = '';
				await loadStatus();
			}
		} catch (e: any) {
			connectError = e.message ?? 'Failed to connect';
		} finally {
			connecting = false;
		}
	}

	function signalBars(signal: number): string {
		// 0–4 filled blocks, rendered as a tiny ASCII meter.
		const filled = Math.max(0, Math.min(4, Math.round((signal / 100) * 4)));
		return '▂▄▆█'.slice(0, filled).padEnd(4, '·');
	}

	onMount(loadStatus);
</script>

<div class="flex flex-col gap-4">
	{#if loadError}
		<Alert variant="danger">{loadError}</Alert>
	{/if}

	{#if status && !status.available}
		<Alert variant="warning">
			NetworkManager (nmcli) isn't available on this machine, so WiFi can't be managed here.
		</Alert>
	{:else if status}
		<!-- Adapters -->
		<div class="border border-border bg-bg px-4 py-3">
			<div class="text-sm font-semibold text-text">Adapters</div>
			<div class="mt-2 flex flex-col gap-1.5">
				{#each status.adapters as a (a.device)}
					<div class="flex items-center gap-2 text-sm">
						<Wifi class="h-4 w-4 {a.connected ? 'text-success' : 'text-text-muted'}" />
						<span class="font-mono text-text">{a.device}</span>
						<span class="text-text-muted">
							{a.connected ? `connected · ${a.active_ssid}` : a.state}
						</span>
						{#if a.ip}
							<span class="ml-auto font-mono text-text-muted">{a.ip}</span>
						{/if}
					</div>
				{/each}
				{#if status.adapters.length === 0}
					<div class="text-sm text-text-muted">No WiFi adapters detected.</div>
				{/if}
			</div>

			{#if status.adapters.length > 1}
				<label class="mt-3 flex items-center gap-2 text-sm text-text-muted">
					Connect using
					<select
						bind:value={selectedDevice}
						class="setup-control border border-border bg-surface px-2 py-1 text-sm text-text"
					>
						{#each status.adapters as a (a.device)}
							<option value={a.device}>{a.device}</option>
						{/each}
					</select>
				</label>
			{/if}
		</div>

		{#if connectError}
			<Alert variant="danger">{connectError}</Alert>
		{/if}
		{#if connectSuccess}
			<Alert variant="success">{connectSuccess}</Alert>
		{/if}

		<!-- Networks -->
		<div class="flex items-center justify-between">
			<div class="text-sm font-semibold text-text">Networks</div>
			<Button variant="secondary" size="sm" loading={scanning} onclick={rescan}>
				<RefreshCw class="mr-1 h-4 w-4" /> Scan
			</Button>
		</div>

		<div class="flex flex-col border border-border">
			{#each status.networks as net (net.ssid)}
				<div class="border-b border-border last:border-b-0">
					<button
						type="button"
						class="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-surface"
						onclick={() => toggleExpand(net)}
					>
						<span class="w-10 font-mono text-sm tabular-nums text-text-muted">{signalBars(net.signal)}</span>
						<span class="flex-1 truncate text-sm font-medium text-text">{net.ssid}</span>
						{#if net.active}
							<span class="inline-flex items-center gap-1 text-sm text-success">
								<Check class="h-4 w-4" /> Connected
							</span>
						{/if}
						{#if net.secured}
							<Lock class="h-4 w-4 text-text-muted" />
						{/if}
						<span class="w-10 text-right text-sm tabular-nums text-text-muted">{net.signal}%</span>
					</button>

					{#if expandedSsid === net.ssid}
						<div class="flex flex-col gap-2 border-t border-border bg-bg px-3 py-3">
							{#if net.secured}
								<Input
									type="password"
									bind:value={passwordDraft}
									placeholder="Password for {net.ssid}"
								/>
							{:else}
								<div class="text-sm text-text-muted">Open network — no password required.</div>
							{/if}
							<div>
								<Button
									variant="primary"
									size="sm"
									loading={connecting}
									disabled={net.secured && passwordDraft.length === 0}
									onclick={() => connect(net)}
								>
									Connect{selectedDevice ? ` (${selectedDevice})` : ''}
								</Button>
							</div>
						</div>
					{/if}
				</div>
			{/each}
			{#if status.networks.length === 0}
				<div class="px-3 py-3 text-sm text-text-muted">No networks found. Try scanning.</div>
			{/if}
		</div>

		<div class="text-sm text-text-muted">
			Switching the network an adapter is using can drop any UI session reaching this machine
			over that adapter. If you're connected over Ethernet or Tailscale, you'll stay connected.
		</div>
	{:else}
		<div class="text-sm text-text-muted">Loading WiFi…</div>
	{/if}
</div>
