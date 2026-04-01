<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { AlertTriangle, Check, Cloud, Pencil, Plus, RefreshCw, Trash2, Upload } from 'lucide-svelte';

	const machine = getMachineContext();

	type UploaderStatus = {
		enabled: boolean;
		server_reachable: boolean;
		queue_size: number;
		uploaded: number;
		failed: number;
		requeued: number;
		last_error: string | null;
	};

	type SortHiveConfig = {
		configured: boolean;
		url: string;
		machine_id: string | null;
		api_token_masked: string | null;
		enabled: boolean;
		uploader: UploaderStatus | null;
	};

	let config = $state<SortHiveConfig | null>(null);
	let loading = $state(true);
	let statusMsg = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);

	let editingTarget = $state(false);
	let showRegisterForm = $state(false);
	let savingTarget = $state(false);
	let removingTarget = $state(false);
	let registering = $state(false);
	let backfilling = $state(false);

	let targetUrl = $state('');
	let targetToken = $state('');

	let regUrl = $state('');
	let regEmail = $state('');
	let regPassword = $state('');
	let regMachineName = $state('');
	let regMachineDescription = $state('');
	let backfillResult = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	function resetTargetForm(nextConfig = config) {
		targetUrl = nextConfig?.url ?? '';
		targetToken = '';
	}

	function resetRegisterForm(nextConfig = config) {
		regUrl = nextConfig?.url ?? '';
		regEmail = '';
		regPassword = '';
		regMachineName = '';
		regMachineDescription = '';
	}

	function clearMessages() {
		statusMsg = null;
		errorMsg = null;
		backfillResult = null;
	}

	async function loadConfig() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive`);
			if (!res.ok) throw new Error(await res.text());
			const data = (await res.json()) as SortHiveConfig;
			config = data;
			resetTargetForm(data);
			resetRegisterForm(data);
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load SortHive config.';
		} finally {
			loading = false;
		}
	}

	function openTargetEditor() {
		clearMessages();
		showRegisterForm = false;
		resetTargetForm();
		editingTarget = true;
	}

	function openRegisterForm() {
		clearMessages();
		editingTarget = false;
		resetRegisterForm();
		showRegisterForm = true;
	}

	function closeForms() {
		editingTarget = false;
		showRegisterForm = false;
		resetTargetForm();
		resetRegisterForm();
	}

	async function handleSaveTarget() {
		if (!targetUrl.trim()) return;
		if (!config?.configured && !targetToken.trim()) return;
		savingTarget = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					url: targetUrl.trim(),
					api_token: targetToken.trim(),
					enabled: config?.configured ? config.enabled : true
				})
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = targetToken.trim()
				? 'SortHive settings saved.'
				: 'SortHive settings updated. Existing token kept.';
			editingTarget = false;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save SortHive settings.';
		} finally {
			savingTarget = false;
		}
	}

	async function handleRemoveTarget() {
		if (!config?.configured) return;
		if (!confirm('Remove the current SortHive connection from this sorter?')) return;
		removingTarget = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive`, {
				method: 'DELETE'
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = 'SortHive connection removed.';
			closeForms();
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to remove SortHive connection.';
		} finally {
			removingTarget = false;
		}
	}

	async function handleRegister() {
		if (!regUrl.trim() || !regEmail.trim() || !regPassword.trim() || !regMachineName.trim()) return;
		registering = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive/register`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					url: regUrl.trim(),
					email: regEmail.trim(),
					password: regPassword.trim(),
					machine_name: regMachineName.trim(),
					machine_description: regMachineDescription.trim()
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			statusMsg = `Machine registered as "${data.machine_name}" (${data.token_prefix}...).`;
			showRegisterForm = false;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Registration failed.';
		} finally {
			registering = false;
		}
	}

	async function handleToggleEnabled() {
		if (!config?.configured) return;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					url: config.url,
					api_token: '',
					enabled: !config.enabled
				})
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = config.enabled ? 'SortHive upload disabled.' : 'SortHive upload enabled.';
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to update uploader state.';
		}
	}

	async function handleBackfill() {
		backfilling = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive/backfill`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (data.ok) {
				backfillResult = `Queued ${data.queued} archived samples (${data.skipped} skipped${data.errors ? `, ${data.errors} errors` : ''}).`;
				await loadConfig();
			} else {
				errorMsg = data.error ?? 'Backfill failed.';
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Backfill failed.';
		} finally {
			backfilling = false;
		}
	}

	function statusLabel(): string {
		if (!config?.configured) return 'SortHive not configured';
		if (!config.enabled) return 'Connected, uploads disabled';
		if (config.uploader?.server_reachable) return 'Connected and ready';
		return 'Connected, waiting for server';
	}

	function statusToneClass(): string {
		if (!config?.configured) return 'dark:text-text-muted-dark text-text-muted';
		if (!config.enabled) return 'text-amber-600 dark:text-amber-400';
		if (config.uploader?.server_reachable) return 'text-emerald-600 dark:text-emerald-400';
		return 'text-amber-600 dark:text-amber-400';
	}

	onMount(() => {
		void loadConfig();
	});
</script>

<div class="grid gap-4">
	{#if loading}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">Loading SortHive configuration...</div>
	{:else if config}
		<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface px-3 py-3">
			<div class="flex flex-wrap items-start justify-between gap-3">
				<div class="min-w-0">
					<div class="flex items-center gap-2">
						<Cloud size={14} class="dark:text-text-muted-dark text-text-muted" />
						<span class="dark:text-text-dark text-sm font-medium text-text">SortHive</span>
					</div>
					<div class={`mt-1 text-xs ${statusToneClass()}`}>{statusLabel()}</div>
				</div>

				<div class="flex flex-wrap justify-end gap-2">
					{#if config.configured}
						<button
							type="button"
							onclick={openTargetEditor}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
						>
							<Pencil size={12} />
							Edit
						</button>
						<button
							type="button"
							onclick={() => void handleBackfill()}
							disabled={backfilling || !config.enabled}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
						>
							<Upload size={12} />
							{backfilling ? 'Queueing...' : 'Queue Backfill'}
						</button>
						<button
							type="button"
							onclick={() => void handleToggleEnabled()}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
						>
							{config.enabled ? 'Disable Upload' : 'Enable Upload'}
						</button>
						<button
							type="button"
							onclick={() => void handleRemoveTarget()}
							disabled={removingTarget}
							class="border border-red-700 bg-red-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-500 dark:bg-red-600 dark:text-white dark:hover:bg-red-500"
						>
							{removingTarget ? 'Removing...' : 'Remove'}
						</button>
					{:else}
						<button
							type="button"
							onclick={openRegisterForm}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
						>
							<Plus size={12} />
							Register Machine
						</button>
						<button
							type="button"
							onclick={openTargetEditor}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
						>
							Use Existing Token
						</button>
					{/if}
				</div>
			</div>

			{#if config.configured}
				<div class="mt-3 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
					<span class="dark:text-text-muted-dark text-text-muted">Server</span>
					<span class="dark:text-text-dark font-mono text-text">{config.url}</span>
					<span class="dark:text-text-muted-dark text-text-muted">Machine ID</span>
					<span class="dark:text-text-dark font-mono text-text">{config.machine_id ?? '—'}</span>
					<span class="dark:text-text-muted-dark text-text-muted">Token</span>
					<span class="dark:text-text-dark font-mono text-text">{config.api_token_masked ?? '—'}</span>
				</div>
			{:else}
				<div class="dark:text-text-muted-dark mt-3 text-sm text-text-muted">
					SortHive is not configured yet. You can either register this machine with a SortHive account or enter an existing machine token manually.
				</div>
			{/if}

			{#if backfillResult}
				<div class="mt-3 rounded border border-emerald-600 bg-emerald-100 px-3 py-2 text-sm font-medium text-emerald-900 dark:border-emerald-500 dark:bg-emerald-950/50 dark:text-emerald-200">
					{backfillResult}
				</div>
			{/if}
			{#if config.configured}
				<div class="dark:border-border-dark mt-4 border-t border-border pt-4">
					<div class="flex items-center gap-2">
						<Upload size={14} class="dark:text-text-muted-dark text-text-muted" />
						<span class="dark:text-text-dark text-sm font-medium text-text">Status</span>
						<button type="button" onclick={() => void loadConfig()} class="ml-auto" title="Refresh">
							<RefreshCw size={12} class="dark:text-text-muted-dark text-text-muted" />
						</button>
					</div>
					{#if config.uploader}
						<div class="mt-3 grid grid-cols-4 gap-2 text-center text-xs">
							<div>
								<div class="dark:text-text-dark text-lg font-semibold text-text">{config.uploader.uploaded}</div>
								<div class="dark:text-text-muted-dark text-text-muted">Uploaded</div>
							</div>
							<div>
								<div class="dark:text-text-dark text-lg font-semibold text-text">{config.uploader.queue_size}</div>
								<div class="dark:text-text-muted-dark text-text-muted">Queued</div>
							</div>
							<div>
								<div class="text-lg font-semibold {config.uploader.requeued > 0 ? 'text-amber-500' : 'dark:text-text-dark text-text'}">{config.uploader.requeued}</div>
								<div class="dark:text-text-muted-dark text-text-muted">Requeued</div>
							</div>
							<div>
								<div class="text-lg font-semibold {config.uploader.failed > 0 ? 'text-red-500' : 'dark:text-text-dark text-text'}">{config.uploader.failed}</div>
								<div class="dark:text-text-muted-dark text-text-muted">Failed</div>
							</div>
						</div>
						{#if config.uploader.last_error}
							<div class="mt-3 text-xs text-amber-600 dark:text-amber-400">{config.uploader.last_error}</div>
						{/if}
					{/if}
				</div>
			{/if}
		</div>

		{#if editingTarget}
			<div class="dark:border-border-dark dark:bg-surface-dark grid gap-3 border border-border bg-surface px-3 py-3">
				<div class="dark:text-text-dark text-sm font-medium text-text">
					{config.configured ? 'Edit SortHive' : 'Connect SortHive'}
				</div>
				<input
					bind:value={targetUrl}
					type="url"
					placeholder="https://sorthive.example.com"
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={targetToken}
					type="password"
					placeholder={config.configured ? 'Leave empty to keep current token' : 'Machine API token'}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 font-mono text-sm text-text"
				/>
				<div class="dark:text-text-muted-dark text-xs text-text-muted">
					{#if config.configured}
						Leave the token empty if you only want to change the URL or keep the current credential.
					{:else}
						Use this if you already have a machine token from SortHive.
					{/if}
				</div>
				<div class="flex justify-end gap-2">
					<button
						type="button"
						onclick={closeForms}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
					>
						Cancel
					</button>
					<button
						type="button"
						onclick={() => void handleSaveTarget()}
						disabled={savingTarget || !targetUrl.trim() || (!config.configured && !targetToken.trim())}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{savingTarget ? 'Saving...' : 'Save'}
					</button>
				</div>
			</div>
		{/if}

		{#if showRegisterForm}
			<div class="dark:border-border-dark dark:bg-surface-dark grid gap-3 border border-border bg-surface px-3 py-3">
				<div class="dark:text-text-dark text-sm font-medium text-text">Register This Machine</div>
				<input
					bind:value={regUrl}
					type="url"
					placeholder="https://sorthive.example.com"
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regEmail}
					type="email"
					placeholder="Account email"
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regPassword}
					type="password"
					placeholder="Account password"
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regMachineName}
					type="text"
					placeholder="Machine name"
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regMachineDescription}
					type="text"
					placeholder="Machine description (optional)"
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<div class="flex justify-end gap-2">
					<button
						type="button"
						onclick={closeForms}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
					>
						Cancel
					</button>
					<button
						type="button"
						onclick={() => void handleRegister()}
						disabled={registering || !regUrl.trim() || !regEmail.trim() || !regPassword.trim() || !regMachineName.trim()}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{registering ? 'Registering...' : 'Register'}
					</button>
				</div>
			</div>
		{/if}
	{/if}

	{#if errorMsg}
		<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
			{errorMsg}
		</div>
	{/if}
	{#if statusMsg}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
