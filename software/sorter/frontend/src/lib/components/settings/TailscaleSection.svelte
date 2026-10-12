<script lang="ts">
	import { onMount } from 'svelte';
	import { machineHttpBaseUrlFromWsUrl, getBackendHttpBase } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { remember, remembered } from '$lib/settings/networkingCache';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import Wifi from '@lucide/svelte/icons/wifi';
	import WifiOff from '@lucide/svelte/icons/wifi-off';

	const REPAIR_MESSAGES = {
		restart: 'Tailscale service restarted.',
		install: 'Tailscale installation repair started.',
		logout: 'Previous sign-in cleared. Enter an auth key to connect again.'
	};
	const machine = getMachineContext();
	type RepairAction = keyof typeof REPAIR_MESSAGES;

	type TailscaleStatus = {
		installed: boolean;
		connected: boolean;
		state:
			| 'not_installed'
			| 'installing'
			| 'stopped'
			| 'logged_out'
			| 'needs_approval'
			| 'connected'
			| 'error';
		can_repair?: boolean;
		hostname?: string | null;
		ipv4?: string | null;
		/** The MagicDNS domain, e.g. tail1234ab.ts.net. */
		tailnet?: string | null;
		/** The network's own name, e.g. example.github. */
		network?: string | null;
		/** Tags the machine joined with; empty when it belongs to a person. */
		tags?: string[];
		owner?: string | null;
		warnings?: string[];
		error?: string;
		installing?: boolean;
		install_error?: string | null;
	};

	const HEADLINES: Record<TailscaleStatus['state'], string> = {
		not_installed: 'Tailscale is not installed',
		installing: 'Installing Tailscale',
		stopped: "The Tailscale service isn't running",
		logged_out: 'Not connected',
		needs_approval: 'Waiting for approval',
		connected: 'Connected',
		error: 'Not connected'
	};

	let status = $state<TailscaleStatus | null>(remembered<TailscaleStatus>(`${httpBase()}/tailscale`));
	let loadError = $state<string | null>(null);
	let authKeyDraft = $state('');
	let applying = $state(false);
	let applyError = $state<string | null>(null);
	let applySuccess = $state<string | null>(null);
	let repair_action = $state<RepairAction | null>(null);
	let repair_error = $state<string | null>(null);
	let repair_message = $state('');
	let clear_confirm_open = $state(false);
	const busy = $derived(applying || repair_action !== null || status?.installing === true);

	function httpBase(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function setStatus(next: TailscaleStatus) {
		status = remember(`${httpBase()}/tailscale`, next);
	}

	/** Which network the machine joined, and as what. */
	function joinedAs(s: TailscaleStatus): string {
		const network = s.network ?? s.tailnet ?? 'the network';
		if (s.tags?.length) return `Joined ${network} as ${s.tags.join(', ')}.`;
		if (s.owner) return `Joined ${network} as ${s.owner}.`;
		return `Joined ${network}.`;
	}

	async function loadStatus() {
		loadError = null;
		try {
			const res = await fetch(`${httpBase()}/api/tailscale/status`);
			if (!res.ok) throw new Error(await res.text());
			const was_installing = status?.installing;
			setStatus(await res.json());
			if (was_installing && !status?.installing) {
				repair_message = status?.install_error ? '' : 'Tailscale installation repair completed.';
			}
		} catch (e: any) {
			loadError = e.message ?? 'Failed to load Tailscale status';
		}
	}

	async function applyAuthKey() {
		const key = authKeyDraft.trim();
		if (!key || busy) return;
		applying = true;
		applyError = null;
		applySuccess = null;
		repair_error = null;
		repair_message = '';
		try {
			const res = await fetch(`${httpBase()}/api/tailscale/up`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ auth_key: key })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (data.status) setStatus(data.status);
			if (!data.ok) {
				applyError = data.error ?? 'Failed to apply auth key';
			} else {
				applySuccess = data.status ? joinedAs(data.status) : 'The machine joined the network.';
				authKeyDraft = '';
			}
		} catch (e: any) {
			applyError = e.message ?? 'Failed to apply auth key';
		} finally {
			applying = false;
		}
	}




	function requestClearSignIn() {
		clear_confirm_open = true;
	}

	async function runRepair(action: RepairAction) {
		if (busy) return;
		clear_confirm_open = false;
		repair_action = action;
		repair_error = null;
		repair_message = '';
		applyError = null;
		applySuccess = null;
		try {
			const res = await fetch(`${httpBase()}/api/tailscale/${action}`, { method: 'POST' });
			const data = await res.json();
			if (data.status) setStatus(data.status);
			if (!res.ok || !data.ok) {
				throw new Error(data.error ?? data.detail ?? 'Tailscale repair failed');
			}
			repair_message = data.message ?? REPAIR_MESSAGES[action];
		} catch (error: unknown) {
			repair_error =
				error instanceof TypeError && action === 'logout'
					? 'Connection lost while clearing sign-in. Reconnect locally to check the machine and join again.'
					: error instanceof Error
						? error.message
						: 'Tailscale repair failed';
		} finally {
			repair_action = null;
		}
	}

	onMount(() => {
		void loadStatus();
	});

	// The machine installs Tailscale on its own; watch until it's there.
	$effect(() => {
		if (!status || (status.installed && !status.installing)) return;
		const timer = setInterval(() => void loadStatus(), 5000);
		return () => clearInterval(timer);
	});

	const repairItems = $derived([
		{
			label: 'Restart the service',
			disabled: busy || !status?.installed || !status.can_repair,
			onselect: () => void runRepair('restart')
		},
		{
			label: 'Install or repair Tailscale',
			disabled: busy || !status?.can_repair,
			onselect: () => void runRepair('install')
		},
		'separator' as const,
		{
			label: 'Clear the previous sign-in',
			danger: true,
			disabled: busy || !status,
			onselect: requestClearSignIn
		}
	]);
</script>

<div class="flex flex-col gap-4">
	<div>
		<div class="flex items-center gap-2">
			{#if status?.connected}
				<Wifi size={16} class="text-success-ink" />
				<span class="text-sm font-medium text-ink">Connected</span>
				<span class="ml-auto font-mono text-sm text-ink-muted">{status.ipv4}</span>
			{:else if status !== null}
				<WifiOff size={16} class="text-ink-faint" />
				<span class="text-sm font-medium text-ink">{HEADLINES[status.state] ?? 'Not connected'}</span>
			{:else}
				<span class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading</span>
			{/if}
			<div class="{status?.connected ? '' : 'ml-auto'}">
				<Menu label="Repair Tailscale" items={repairItems} width="16rem">
					{#snippet trigger(props)}
						<Button {...props} variant="ghost" size="sm" icon={Ellipsis} label="Repair Tailscale" />
					{/snippet}
				</Menu>
			</div>
		</div>
		{#if status?.connected}
			<dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
				<dt class="text-ink-muted">Hostname</dt>
				<dd class="font-mono text-ink">{status.hostname}</dd>
				{#if status.network || status.tailnet}
					<dt class="text-ink-muted">Network</dt>
					<dd class="text-ink">
						<span class="font-mono">{status.network ?? status.tailnet}</span>
						{#if status.network && status.tailnet}
							<span class="ml-2 font-mono text-ink-muted">{status.tailnet}</span>
						{/if}
					</dd>
				{/if}
				{#if status.tags?.length || status.owner}
					<dt class="text-ink-muted">Joined as</dt>
					<dd class="font-mono text-ink">{status.tags?.length ? status.tags.join(', ') : status.owner}</dd>
				{/if}
			</dl>
			<p class="mt-2 text-sm text-ink-muted">
				{#if status.tags?.length}
					A tagged device: it belongs to the {status.network ?? 'Tailscale'} network rather than to a
					person, and its key doesn't expire. That network's admins can open this page and SSH into
					the machine.
				{:else if status.owner}
					Signed in as {status.owner}. Its key expires unless key expiry is turned off for this machine
					in Tailscale's admin console.
				{/if}
			</p>
			{#each status.warnings ?? [] as warning (warning)}
				<p class="mt-1 text-sm text-ink-muted">Tailscale reports: {warning}</p>
			{/each}
		{:else if status?.state === 'not_installed'}
			{#if status.can_repair}
				<div class="mt-2">
					<Button variant="secondary" size="sm" disabled={busy} onclick={() => void runRepair('install')}>
						Install Tailscale
					</Button>
				</div>
			{:else}
				<p class="mt-1 text-sm text-ink-muted">
					This machine can't install it from here. On the machine, run
					<code class="font-mono text-ink">curl -fsSL https://tailscale.com/install.sh | sh</code>, then
					reload this page.
				</p>
			{/if}
		{:else if status && status.error}
			<p class="mt-1 text-sm text-ink-muted">{status.error}</p>
			{#if status.state === 'stopped' && status.can_repair}
				<div class="mt-2">
					<Button variant="secondary" size="sm" disabled={busy} onclick={() => void runRepair('restart')}>
						Start the service
					</Button>
				</div>
			{/if}
		{/if}
		<p class="mt-2 text-sm text-ink-muted">
			Restarting or repairing Tailscale can briefly interrupt this connection.{status?.can_repair ===
			false
				? " Service repair isn't available on this machine."
				: ''}
		</p>
	</div>

	<Alert tone="warning">
		An auth key gives the owner of that Tailscale network SSH access to this machine and access to
		your local network. Only use a key you made yourself or got from someone you fully trust.
	</Alert>

	<Field
		label="Auth key"
		for="tailscale-auth-key"
		help="Make one at tailscale.com/admin/settings/keys. The machine joins (or switches to) that network at once."
	>
		<div class="flex gap-2">
			<Input
				id="tailscale-auth-key"
				type="password"
				placeholder="tskey-auth-..."
				bind:value={authKeyDraft}
				class="min-w-0 flex-1 font-mono"
			/>
			<Button
				variant="primary"
				disabled={!authKeyDraft.trim() || busy || (status !== null && !status.installed)}
				loading={applying}
				onclick={() => void applyAuthKey()}
			>
				Apply
			</Button>
		</div>
	</Field>

	{#if applyError}
		<Alert tone="danger">{applyError}</Alert>
	{/if}
	{#if applySuccess}
		<Alert tone="success">{applySuccess}</Alert>
	{/if}
	{#if repair_action || status?.installing}
		<Alert tone="info">
			{repair_action === 'restart'
				? 'Restarting the Tailscale service'
				: repair_action === 'install' || status?.installing
					? 'Repairing the Tailscale installation'
					: 'Clearing the previous sign-in'}
		</Alert>
	{/if}
	{#if repair_error}
		<Alert tone="danger">{repair_error}</Alert>
	{/if}
	{#if status?.install_error}
		<Alert tone="danger">
			The installation failed: {status.install_error}. "Install or repair Tailscale" in the menu
			tries again.
		</Alert>
	{/if}
	{#if repair_message && !status?.installing}
		<Alert tone="success">{repair_message}</Alert>
	{/if}
	{#if loadError}
		<Alert tone="warning">{loadError}</Alert>
	{/if}
</div>

<Modal bind:open={clear_confirm_open} title="Clear the previous Tailscale sign-in?" size="sm">
	<p>
		This disconnects the machine from its Tailscale network and removes any saved setup key. If you
		opened this page through Tailscale, it may stop answering. Open Settings on the machine's local
		network and enter a new auth key here to connect again.
	</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (clear_confirm_open = false)}>Cancel</Button>
		<Button variant="danger" disabled={busy} onclick={() => void runRepair('logout')}>
			Clear the sign-in
		</Button>
	{/snippet}
</Modal>
