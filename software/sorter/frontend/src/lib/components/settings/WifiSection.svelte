<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import { Wifi, WifiOff, Lock, Cable, RefreshCcw } from 'lucide-svelte';

	const machine = getMachineContext();

	type WifiState = {
		present: boolean;
		connected: boolean;
		device?: string;
		ssid?: string | null;
		ip?: string | null;
	};
	type EthernetState = {
		device: string;
		state: string;
		connection: string | null;
		ip?: string | null;
	};
	type NetworkStatus = {
		available: boolean;
		radio_enabled?: boolean;
		wifi?: WifiState;
		ethernet?: EthernetState[];
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
	let forgetting = $state(false);

	function httpBase(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function selectedNeedsPassword(): boolean {
		const net = networks.find((n) => n.ssid === selectedSsid);
		return net ? net.security.trim().length > 0 : true;
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
				connectSuccess = ip ? `Connected to ${ssid} — WiFi IP ${ip}` : `Connected to ${ssid}`;
				selectedSsid = null;
				passwordDraft = '';
				hiddenSsidDraft = '';
				void scan();
			}
		} catch (e: any) {
			connectError = e.message ?? 'Failed to connect';
		} finally {
			connecting = false;
		}
	}

	async function forget(ssid: string) {
		forgetting = true;
		connectError = null;
		connectSuccess = null;
		try {
			const res = await fetch(`${httpBase()}/api/network/wifi/forget`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ ssid })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) {
				connectError = data.error ?? 'Failed to forget network';
			}
			if (data.status) status = data.status;
		} catch (e: any) {
			connectError = e.message ?? 'Failed to forget network';
		} finally {
			forgetting = false;
		}
	}

	function pickNetwork(ssid: string) {
		connectError = null;
		connectSuccess = null;
		passwordDraft = '';
		selectedSsid = selectedSsid === ssid ? null : ssid;
	}

	const connectedEthernet = $derived(
		(status?.ethernet ?? []).filter((e) => e.state.startsWith('connected'))
	);

	onMount(() => {
		void loadStatus();
	});
</script>

<div class="flex flex-col gap-4">
	<!-- Status row -->
	<div class="border border-border bg-surface px-3 py-3">
		<div class="flex items-center gap-2">
			{#if status === null}
				<span class="text-sm text-text-muted">Loading...</span>
			{:else if !status.available}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">NetworkManager is not available on this machine</span>
			{:else if status.wifi?.connected}
				<Wifi size={14} class="text-success" />
				<span class="text-sm font-medium text-text">{status.wifi.ssid}</span>
				<span class="ml-auto font-mono text-sm text-text-muted">{status.wifi.ip}</span>
			{:else if !status.radio_enabled}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">WiFi radio is off</span>
			{:else if !status.wifi?.present}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">No WiFi adapter detected</span>
			{:else}
				<WifiOff size={14} class="text-text-muted" />
				<span class="text-sm font-medium text-text">Not connected</span>
			{/if}
		</div>
		{#if status?.wifi?.connected}
			<div class="mt-2 flex items-center justify-end">
				<Button
					variant="danger"
					size="sm"
					loading={forgetting}
					onclick={() => status?.wifi?.ssid && void forget(status.wifi.ssid)}
				>
					{forgetting ? 'Forgetting...' : 'Forget network'}
				</Button>
			</div>
		{/if}
		{#each connectedEthernet as eth (eth.device)}
			<div class="mt-2 flex items-center gap-2 text-sm text-text-muted">
				<Cable size={14} />
				<span>Wired LAN connected ({eth.device}{eth.ip ? `, ${eth.ip}` : ''}) — stays up regardless of WiFi changes.</span>
			</div>
		{/each}
	</div>

	{#if status?.available}
		<!-- Scan -->
		<div>
			<div class="mb-2 flex items-center justify-between">
				<div class="text-sm font-medium text-text">Available networks</div>
				<Button variant="secondary" size="sm" loading={scanning} onclick={() => void scan()}>
					<RefreshCcw size={14} />
					{scanning ? 'Scanning...' : scanned ? 'Rescan' : 'Scan'}
				</Button>
			</div>

			{#if scanError}
				<Alert variant="danger">{scanError}</Alert>
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
								{#if net.in_use}
									<span class="text-xs font-semibold tracking-wider text-success uppercase">connected</span>
								{/if}
								<span class="ml-auto font-mono text-sm text-text-muted">{net.signal}%</span>
							</button>
							{#if selectedSsid === net.ssid && !net.in_use}
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
				<Input type="text" placeholder="SSID" bind:value={hiddenSsidDraft} class="flex-1" />
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
