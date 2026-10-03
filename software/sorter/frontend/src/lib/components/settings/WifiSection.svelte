<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Wifi from '@lucide/svelte/icons/wifi';
	import Lock from '@lucide/svelte/icons/lock';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Check from '@lucide/svelte/icons/check';

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
		<Alert tone="danger">{loadError}</Alert>
	{/if}

	{#if status && !status.available}
		<Alert tone="warning">
			NetworkManager (nmcli) isn't available on this machine, so its Wi-Fi can't be managed here.
		</Alert>
	{:else if status}
		<div>
			<div class="label">Adapters</div>
			{#if status.adapters.length === 0}
				<p class="mt-1 text-sm text-ink-muted">No Wi-Fi adapters found.</p>
			{:else}
				<ul class="mt-1 divide-y divide-line">
					{#each status.adapters as a (a.device)}
						<li class="flex items-center gap-2 py-2 text-sm">
							<Wifi size={16} class={a.connected ? 'text-success-ink' : 'text-ink-faint'} />
							<span class="font-mono text-ink">{a.device}</span>
							<span class="text-ink-muted">
								{a.connected ? `Connected to ${a.active_ssid}` : a.state}
							</span>
							{#if a.ip}
								<span class="ml-auto font-mono text-ink-muted">{a.ip}</span>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
			{#if status.adapters.length > 1}
				<div class="mt-3 flex items-center gap-3">
					<label for="wifi-adapter" class="text-sm text-ink-muted">Connect using</label>
					<Select
						id="wifi-adapter"
						size="sm"
						bind:value={selectedDevice}
						options={status.adapters.map((a) => ({ value: a.device, label: a.device }))}
						class="w-40"
					/>
				</div>
			{/if}
		</div>

		{#if connectError}
			<Alert tone="danger">{connectError}</Alert>
		{/if}
		{#if connectSuccess}
			<Alert tone="success">{connectSuccess}</Alert>
		{/if}

		<div>
			<div class="flex items-center justify-between gap-3">
				<div class="label">Networks</div>
				<Button variant="ghost" size="sm" icon={RefreshCw} loading={scanning} onclick={rescan}>
					Scan
				</Button>
			</div>
			{#if status.networks.length === 0}
				<p class="mt-1 text-sm text-ink-muted">No networks found. Try scanning.</p>
			{:else}
				<ul class="mt-1 divide-y divide-line">
					{#each status.networks as net (net.ssid)}
						<li>
							<button
								type="button"
								class="flex w-full items-center gap-3 rounded-item px-2 py-2 text-left text-sm transition-colors hover:bg-hover"
								aria-expanded={expandedSsid === net.ssid}
								onclick={() => toggleExpand(net)}
							>
								<span class="num w-10 font-mono text-ink-muted">{signalBars(net.signal)}</span>
								<span class="flex-1 truncate font-medium text-ink">{net.ssid}</span>
								{#if net.active}
									<span class="inline-flex items-center gap-1 text-success-ink">
										<Check size={16} /> Connected
									</span>
								{/if}
								{#if net.secured}
									<Lock size={16} class="text-ink-muted" />
								{/if}
								<span class="num w-10 text-right text-ink-muted">{net.signal}%</span>
							</button>
							{#if expandedSsid === net.ssid}
								<div class="mb-2 flex flex-col gap-3 rounded-control bg-well p-3">
									{#if net.secured}
										<Input
											type="password"
											bind:value={passwordDraft}
											placeholder="Password for {net.ssid}"
										/>
									{:else}
										<p class="text-sm text-ink-muted">An open network: no password.</p>
									{/if}
									<div>
										<Button
											variant="primary"
											loading={connecting}
											disabled={net.secured && passwordDraft.length === 0}
											onclick={() => connect(net)}
										>
											Connect{selectedDevice ? ` with ${selectedDevice}` : ''}
										</Button>
									</div>
								</div>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<p class="text-sm text-ink-muted">
			Switching the network an adapter uses can drop any page reaching this machine through that
			adapter. Over Ethernet or Tailscale, you stay connected.
		</p>
	{:else}
		<div class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading Wi-Fi</div>
	{/if}
</div>
