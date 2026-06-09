<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import { Wifi, WifiOff, Lock, RefreshCcw } from 'lucide-svelte';

	const machine = getMachineContext();

	type WifiState = {
		present: boolean;
		connected: boolean;
		device?: string;
		ssid?: string | null;
		ip?: string | null;
		gateway?: string | null;
		dns?: string[];
	};
	type NetworkStatus = {
		available: boolean;
		radio_enabled?: boolean;
		wifi?: WifiState;
	};
	type ScanNetwork = {
		ssid: string;
		signal: number;
		security: string;
		in_use: boolean;
	};

	let status = $state<NetworkStatus | null>(null);
	let loadError = $state<string | null>(null);
	let networks = $state<ScanNetwork[]>([]);
	let scanning = $state(false);
	let scanError = $state<string | null>(null);
	let scanned = $state(false);

	let selectedSsid = $state<string | null>(null);
	let passwordDraft = $state('');
	let hiddenSsidDraft = $state('');
	let connecting = $state(false);
	let connectError = $state<string | null>(null);
	let connectSuccess = $state<string | null>(null);
	let disconnecting = $state(false);

	const wifiConnected = $derived(Boolean(status?.wifi?.connected));
	const canScan = $derived(
		Boolean(status?.available && status?.radio_enabled && status?.wifi?.present)
	);

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

	// The picker scans by itself: immediately when it becomes visible (no
	// active WiFi connection) and then every 20 s while it stays open. Only
	// the visibility condition is tracked — the busy flags are read untracked
	// so a finishing scan does not re-trigger the effect.
	$effect(() => {
		if (!canScan || wifiConnected) return;
		untrack(() => {
			if (!scanning) void scan();
		});
		const interval = setInterval(() => {
			if (!scanning && !connecting) void scan();
		}, 20_000);
		return () => clearInterval(interval);
	});

	async function scan() {
		scanning = true;
		scanError = null;
		try {
			const res = await fetch(`${httpBase()}/api/network/wifi/scan`, { method: 'POST' });
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (data.ok === false) {
				scanError = data.error ?? 'WiFi scan failed';
			} else {
				networks = data.networks ?? [];
				scanned = true;
			}
		} catch (e: any) {
			scanError = e.message ?? 'WiFi scan failed';
		} finally {
			scanning = false;
		}
	}

	async function connect(ssid: string, hidden: boolean) {
		connecting = true;
		connectError = null;
		connectSuccess = null;
		try {
			const res = await fetch(`${httpBase()}/api/network/wifi/connect`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ ssid, password: passwordDraft, hidden })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) {
				connectError = data.error ?? 'Failed to connect';
				if (data.status) status = data.status;
			} else {
				status = data.status ?? status;
				const ip = data.status?.wifi?.ip;
				connectSuccess = ip ? `Connected to ${ssid} — IP ${ip}` : `Connected to ${ssid}`;
				selectedSsid = null;
				passwordDraft = '';
				hiddenSsidDraft = '';
			}
		} catch (e: any) {
			connectError = e.message ?? 'Failed to connect';
		} finally {
			connecting = false;
		}
	}

	async function disconnect(ssid: string) {
		disconnecting = true;
		connectError = null;
		connectSuccess = null;
		try {
			const res = await fetch(`${httpBase()}/api/network/wifi/disconnect`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ ssid })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) {
				connectError = data.error ?? 'Failed to disconnect';
			}
			// The picker effect kicks in as soon as the status flips to
			// disconnected and scans automatically.
			if (data.status) status = data.status;
			scanned = false;
			void loadStatus();
		} catch (e: any) {
			connectError = e.message ?? 'Failed to disconnect';
		} finally {
			disconnecting = false;
		}
	}

	function pickNetwork(ssid: string) {
		connectError = null;
		connectSuccess = null;
		passwordDraft = '';
		selectedSsid = selectedSsid === ssid ? null : ssid;
	}

	onMount(() => {
		void loadStatus();
	});
</script>

<div class="flex flex-col gap-4">
	<!-- Status -->
	<div class="border border-border bg-surface px-3 py-3">
		<div class="flex items-center gap-2">
			{#if status === null}
				<span class="text-sm text-text-muted">Loading...</span>
			{:else if !status.available}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">Network management is not available on this machine</span>
			{:else if wifiConnected}
				<Wifi size={14} class="text-success" />
				<span class="text-sm font-medium text-text">{status.wifi?.ssid}</span>
				<span class="ml-auto font-mono text-sm text-text-muted">{status.wifi?.device}</span>
			{:else if !status.radio_enabled}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">WiFi is turned off</span>
			{:else if !status.wifi?.present}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">No WiFi adapter detected</span>
			{:else}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">Not connected</span>
			{/if}
		</div>
		{#if wifiConnected}
			<div class="mt-2 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
				<span class="text-sm text-text-muted">IP address</span>
				<span class="font-mono text-sm text-text">{status?.wifi?.ip ?? '—'}</span>
				<span class="text-sm text-text-muted">Router</span>
				<span class="font-mono text-sm text-text">{status?.wifi?.gateway ?? '—'}</span>
				<span class="text-sm text-text-muted">DNS</span>
				<span class="font-mono text-sm text-text">{(status?.wifi?.dns ?? []).join(', ') || '—'}</span>
			</div>
			<div class="mt-3 flex justify-end">
				<Button
					variant="secondary"
					size="sm"
					loading={disconnecting}
					onclick={() => status?.wifi?.ssid && void disconnect(status.wifi.ssid)}
				>
					{disconnecting ? 'Disconnecting...' : 'Disconnect'}
				</Button>
			</div>
		{/if}
	</div>

	<!-- Picker: only while not connected -->
	{#if status?.available && !wifiConnected && status.wifi?.present && status.radio_enabled}
		<div>
			<div class="mb-2 flex items-center justify-between">
				<div class="text-sm font-medium text-text">Available networks</div>
				<Button variant="secondary" size="sm" loading={scanning} onclick={() => void scan()}>
					<RefreshCcw size={14} />
					{scanning ? 'Scanning...' : 'Rescan'}
				</Button>
			</div>

			{#if scanError}
				<Alert variant="danger">{scanError}</Alert>
			{:else if scanning && !scanned}
				<div class="border border-border px-3 py-3 text-sm text-text-muted">Searching for networks...</div>
			{:else if scanned && networks.length === 0}
				<Alert variant="info">No networks found.</Alert>
			{:else if networks.length > 0}
				<div class="flex flex-col border border-border">
					{#each networks as net (net.ssid)}
						<div class="border-b border-border last:border-b-0">
							<button
								type="button"
								class="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-surface"
								onclick={() => pickNetwork(net.ssid)}
							>
								<Wifi size={14} class={net.signal > 50 ? 'text-text' : 'text-text-muted'} />
								<span class="text-sm text-text">{net.ssid}</span>
								{#if net.security}
									<Lock size={12} class="text-text-muted" />
								{/if}
								<span class="ml-auto font-mono text-sm text-text-muted">{net.signal}%</span>
							</button>
							{#if selectedSsid === net.ssid}
								<div class="flex gap-2 border-t border-border bg-surface px-3 py-2">
									{#if net.security}
										<Input
											type="password"
											placeholder="Password"
											bind:value={passwordDraft}
											class="flex-1"
										/>
									{:else}
										<span class="flex-1 self-center text-sm text-text-muted">Open network</span>
									{/if}
									<Button
										variant="primary"
										size="sm"
										disabled={connecting || (net.security !== '' && passwordDraft.length < 8)}
										loading={connecting}
										onclick={() => void connect(net.ssid, false)}
									>
										{connecting ? 'Connecting...' : 'Connect'}
									</Button>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Hidden network -->
		<div>
			<div class="mb-2 text-sm font-medium text-text">Hidden network</div>
			<div class="flex gap-2">
				<Input type="text" placeholder="Network name" bind:value={hiddenSsidDraft} class="flex-1" />
				<Input type="password" placeholder="Password" bind:value={passwordDraft} class="flex-1" />
				<Button
					variant="secondary"
					size="sm"
					disabled={!hiddenSsidDraft.trim() || connecting}
					loading={connecting}
					onclick={() => void connect(hiddenSsidDraft.trim(), true)}
				>
					Connect
				</Button>
			</div>
		</div>
	{/if}

	{#if connectError}
		<Alert variant="danger">{connectError}</Alert>
	{/if}
	{#if connectSuccess}
		<Alert variant="success">{connectSuccess}</Alert>
	{/if}
	{#if loadError}
		<Alert variant="warning">{loadError}</Alert>
	{/if}
</div>
