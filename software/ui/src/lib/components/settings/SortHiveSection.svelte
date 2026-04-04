<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Cloud, Pencil, Plus, RefreshCw, Trash2, Upload } from 'lucide-svelte';

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

	type SortHiveTarget = {
		id: string;
		name: string;
		url: string;
		machine_id: string | null;
		api_token_masked: string | null;
		enabled: boolean;
		uploader: UploaderStatus;
	};

	type SortHiveConfig = {
		configured_count: number;
		enabled_count: number;
		targets: SortHiveTarget[];
	};

	type LegacySortHiveConfig = {
		configured?: boolean;
		url?: string;
		machine_id?: string | null;
		api_token_masked?: string | null;
		enabled?: boolean;
		uploader?: UploaderStatus | null;
	};

	let config = $state<SortHiveConfig | null>(null);
	let loading = $state(true);
	let statusMsg = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);
	let backfillResult = $state<string | null>(null);
	let backfillTargetId = $state<string | null>(null);

	let editingTargetId = $state<string | null>(null);
	let showRegisterForm = $state(false);
	let savingTarget = $state(false);
	let removingTargetId = $state<string | null>(null);
	let registering = $state(false);
	let backfillingTargetId = $state<string | null>(null);

	let targetName = $state('');
	let targetUrl = $state('');
	let targetToken = $state('');
	let targetEnabled = $state(true);

	let regTargetName = $state('');
	let regUrl = $state('');
	let regEmail = $state('');
	let regPassword = $state('');
	let regMachineName = $state('');
	let regMachineDescription = $state('');

	const targets = $derived(config?.targets ?? []);

	function emptyUploaderStatus(enabled: boolean): UploaderStatus {
		return {
			enabled,
			server_reachable: false,
			queue_size: 0,
			uploaded: 0,
			failed: 0,
			requeued: 0,
			last_error: null
		};
	}

	function normalizeConfig(raw: unknown): SortHiveConfig {
		if (!raw || typeof raw !== 'object') {
			return { configured_count: 0, enabled_count: 0, targets: [] };
		}

		const data = raw as Record<string, unknown>;
		if (Array.isArray(data.targets)) {
			const normalizedTargets = data.targets.flatMap((entry, index) => {
				if (!entry || typeof entry !== 'object') return [];
				const target = entry as Record<string, unknown>;
				const enabled = Boolean(target.enabled);
				const uploaderRaw =
					target.uploader && typeof target.uploader === 'object'
						? (target.uploader as Partial<UploaderStatus>)
						: null;
				return [
					{
						id:
							typeof target.id === 'string' && target.id.trim()
								? target.id
								: `target-${index + 1}`,
						name:
							typeof target.name === 'string' && target.name.trim()
								? target.name
								: typeof target.url === 'string'
									? target.url
									: `SortHive ${index + 1}`,
						url: typeof target.url === 'string' ? target.url : '',
						machine_id: typeof target.machine_id === 'string' ? target.machine_id : null,
						api_token_masked:
							typeof target.api_token_masked === 'string' ? target.api_token_masked : null,
						enabled,
						uploader: {
							...emptyUploaderStatus(enabled),
							...(uploaderRaw ?? {})
						}
					} satisfies SortHiveTarget
				];
			});

			return {
				configured_count: normalizedTargets.length,
				enabled_count: normalizedTargets.filter((target) => target.enabled).length,
				targets: normalizedTargets
			};
		}

		const legacy = data as LegacySortHiveConfig;
		const configured =
			Boolean(legacy.configured) ||
			(typeof legacy.url === 'string' && legacy.url.trim().length > 0);
		if (!configured || typeof legacy.url !== 'string' || !legacy.url.trim()) {
			return { configured_count: 0, enabled_count: 0, targets: [] };
		}

		const enabled = Boolean(legacy.enabled);
		return {
			configured_count: 1,
			enabled_count: enabled ? 1 : 0,
			targets: [
				{
					id: 'legacy-target',
					name: legacy.url,
					url: legacy.url,
					machine_id: typeof legacy.machine_id === 'string' ? legacy.machine_id : null,
					api_token_masked:
						typeof legacy.api_token_masked === 'string' ? legacy.api_token_masked : null,
					enabled,
					uploader: {
						...emptyUploaderStatus(enabled),
						...(legacy.uploader ?? {})
					}
				}
			]
		};
	}

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	function getTarget(targetId: string | null): SortHiveTarget | null {
		if (!targetId) return null;
		return targets.find((target) => target.id === targetId) ?? null;
	}

	function clearMessages() {
		statusMsg = null;
		errorMsg = null;
		backfillResult = null;
		backfillTargetId = null;
	}

	function resetTargetForm(target: SortHiveTarget | null = null) {
		targetName = target?.name ?? '';
		targetUrl = target?.url ?? '';
		targetToken = '';
		targetEnabled = target?.enabled ?? true;
	}

	function resetRegisterForm() {
		regTargetName = '';
		regUrl = '';
		regEmail = '';
		regPassword = '';
		regMachineName = '';
		regMachineDescription = '';
	}

	async function loadConfig() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive`);
			if (!res.ok) throw new Error(await res.text());
			config = normalizeConfig(await res.json());

			if (editingTargetId) {
				resetTargetForm(getTarget(editingTargetId));
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load SortHive config.';
		} finally {
			loading = false;
		}
	}

	function openTargetEditor(target: SortHiveTarget | null = null) {
		clearMessages();
		showRegisterForm = false;
		editingTargetId = target?.id ?? 'new';
		resetTargetForm(target);
	}

	function openRegisterForm() {
		clearMessages();
		editingTargetId = null;
		showRegisterForm = true;
		resetRegisterForm();
	}

	function closeForms() {
		editingTargetId = null;
		showRegisterForm = false;
		resetTargetForm();
		resetRegisterForm();
	}

	async function handleSaveTarget() {
		if (!targetUrl.trim()) return;
		const existing = editingTargetId && editingTargetId !== 'new' ? getTarget(editingTargetId) : null;
		if (!existing && !targetToken.trim()) return;

		savingTarget = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					id: existing?.id ?? null,
					name: targetName.trim(),
					url: targetUrl.trim(),
					api_token: targetToken.trim(),
					enabled: targetEnabled
				})
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = existing
				? targetToken.trim()
					? `Updated SortHive target "${targetName.trim() || existing.name}".`
					: `Updated SortHive target "${targetName.trim() || existing.name}" and kept the current token.`
				: `Added SortHive target "${targetName.trim() || targetUrl.trim()}".`;
			closeForms();
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save SortHive target.';
		} finally {
			savingTarget = false;
		}
	}

	async function handleRemoveTarget(target: SortHiveTarget) {
		if (!confirm(`Remove the SortHive target "${target.name}" from this sorter?`)) return;
		removingTargetId = target.id;
		clearMessages();
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/settings/sorthive?target_id=${encodeURIComponent(target.id)}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) throw new Error(await res.text());
			statusMsg = `Removed SortHive target "${target.name}".`;
			if (editingTargetId === target.id) {
				closeForms();
			}
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to remove SortHive target.';
		} finally {
			removingTargetId = null;
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
					target_name: regTargetName.trim(),
					url: regUrl.trim(),
					email: regEmail.trim(),
					password: regPassword.trim(),
					machine_name: regMachineName.trim(),
					machine_description: regMachineDescription.trim()
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			statusMsg = `Registered "${data.machine_name}" for target "${data.target_name}".`;
			showRegisterForm = false;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Registration failed.';
		} finally {
			registering = false;
		}
	}

	async function handleToggleEnabled(target: SortHiveTarget) {
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					id: target.id,
					name: target.name,
					url: target.url,
					api_token: '',
					enabled: !target.enabled
				})
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = !target.enabled
				? `Enabled uploads to "${target.name}".`
				: `Disabled uploads to "${target.name}".`;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to update uploader state.';
		}
	}

	async function handleBackfill(target: SortHiveTarget) {
		backfillingTargetId = target.id;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/sorthive/backfill`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_ids: [target.id]
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) throw new Error(data.error ?? 'Backfill failed.');
			backfillTargetId = target.id;
			backfillResult = `Queued ${data.queued} archived samples for "${target.name}" (${data.skipped} skipped${data.errors ? `, ${data.errors} errors` : ''}).`;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Backfill failed.';
		} finally {
			backfillingTargetId = null;
		}
	}

	function statusLabel(target: SortHiveTarget): string {
		if (!target.enabled) return 'Connected, uploads disabled';
		if (target.uploader.server_reachable) return 'Connected and ready';
		return 'Connected, waiting for server';
	}

	function statusToneClass(target: SortHiveTarget): string {
		if (!target.enabled) return 'text-amber-600 dark:text-amber-400';
		if (target.uploader.server_reachable) return 'text-[#00852B] dark:text-emerald-400';
		return 'text-amber-600 dark:text-amber-400';
	}

	onMount(() => {
		void loadConfig();
	});
</script>

<div class="grid gap-4">
	{#if loading}
		<div class="text-sm text-text-muted">Loading SortHive configuration...</div>
	{:else if config}
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="text-sm text-text-muted">
				{#if targets.length > 0}
					{config.enabled_count} of {config.configured_count} SortHive target{config.configured_count === 1 ? '' : 's'} enabled.
				{:else}
					No SortHive targets configured yet.
				{/if}
			</div>
			<div class="flex flex-wrap gap-2">
				<button
					type="button"
					onclick={openRegisterForm}
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
				>
					<Plus size={12} />
					Register Machine
				</button>
				<button
					type="button"
					onclick={() => openTargetEditor(null)}
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
				>
					<Cloud size={12} />
					Add Existing Token
				</button>
				<button
					type="button"
					onclick={() => void loadConfig()}
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
					title="Refresh targets"
				>
					<RefreshCw size={12} />
					Refresh
				</button>
			</div>
		</div>

		{#if targets.length === 0}
			<div class="border border-border bg-surface px-3 py-3">
				<div class="text-sm text-text-muted">
					Add one SortHive target for local testing, production, or both. Each target keeps its own token, status, and backfill queue.
				</div>
			</div>
		{:else}
			<div class="grid gap-4">
				{#each targets as target (target.id)}
					<div class="border border-border bg-surface px-3 py-3">
						<div class="flex flex-wrap items-start justify-between gap-3">
							<div class="min-w-0">
								<div class="flex items-center gap-2">
									<Cloud size={14} class="text-text-muted" />
									<span class="text-sm font-medium text-text">{target.name}</span>
								</div>
								<div class={`mt-1 text-xs ${statusToneClass(target)}`}>{statusLabel(target)}</div>
							</div>

							<div class="flex flex-wrap justify-end gap-2">
								<button
									type="button"
									onclick={() => openTargetEditor(target)}
									class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
								>
									<Pencil size={12} />
									Edit
								</button>
								<button
									type="button"
									onclick={() => void handleBackfill(target)}
									disabled={backfillingTargetId === target.id || !target.enabled}
									class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
								>
									<Upload size={12} />
									{backfillingTargetId === target.id ? 'Queueing...' : 'Queue Backfill'}
								</button>
								<button
									type="button"
									onclick={() => void handleToggleEnabled(target)}
									class="border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
								>
									{target.enabled ? 'Disable Upload' : 'Enable Upload'}
								</button>
								<button
									type="button"
									onclick={() => void handleRemoveTarget(target)}
									disabled={removingTargetId === target.id}
									class="inline-flex items-center gap-1.5 border border-[#D01012] bg-[#D01012] px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[#D01012]/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-[#D01012] dark:bg-[#D01012] dark:hover:bg-[#D01012]/80"
								>
									<Trash2 size={12} />
									{removingTargetId === target.id ? 'Removing...' : 'Remove'}
								</button>
							</div>
						</div>

						<div class="mt-3 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
							<span class="text-text-muted">Server</span>
							<span class="font-mono text-text">{target.url}</span>
							<span class="text-text-muted">Machine ID</span>
							<span class="font-mono text-text">{target.machine_id ?? '—'}</span>
							<span class="text-text-muted">Token</span>
							<span class="font-mono text-text">{target.api_token_masked ?? '—'}</span>
						</div>

						{#if backfillTargetId === target.id && backfillResult}
							<div class="mt-3 border border-[#00852B] bg-[#00852B]/10 px-3 py-2 text-sm font-medium text-[#00852B] dark:border-[#00852B] dark:bg-[#00852B]/10 dark:text-emerald-200">
								{backfillResult}
							</div>
						{/if}

						<div class="mt-4 border-t border-border pt-4">
							<div class="flex items-center gap-2">
								<Upload size={14} class="text-text-muted" />
								<span class="text-sm font-medium text-text">Status</span>
							</div>
							<div class="mt-3 grid grid-cols-4 gap-2 text-center text-xs">
								<div>
									<div class="text-lg font-semibold text-text">{target.uploader.uploaded}</div>
									<div class="text-text-muted">Uploaded</div>
								</div>
								<div>
									<div class="text-lg font-semibold text-text">{target.uploader.queue_size}</div>
									<div class="text-text-muted">Queued</div>
								</div>
								<div>
									<div class="text-lg font-semibold {target.uploader.requeued > 0 ? 'text-amber-500' : 'text-text'}">{target.uploader.requeued}</div>
									<div class="text-text-muted">Requeued</div>
								</div>
								<div>
									<div class="text-lg font-semibold {target.uploader.failed > 0 ? 'text-[#D01012]' : 'text-text'}">{target.uploader.failed}</div>
									<div class="text-text-muted">Failed</div>
								</div>
							</div>
							{#if target.uploader.last_error}
								<div class="mt-3 text-xs text-amber-600 dark:text-amber-400">{target.uploader.last_error}</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}

		{#if editingTargetId}
			<div class="grid gap-3 border border-border bg-surface px-3 py-3">
				<div class="text-sm font-medium text-text">
					{editingTargetId === 'new' ? 'Add SortHive Target' : `Edit ${getTarget(editingTargetId)?.name ?? 'SortHive Target'}`}
				</div>
				<input
					bind:value={targetName}
					type="text"
					placeholder="Target name (for example Local or Live)"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={targetUrl}
					type="url"
					placeholder="https://sorthive.example.com"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={targetToken}
					type="password"
					placeholder={editingTargetId === 'new' ? 'Machine API token' : 'Leave empty to keep current token'}
					class="border border-border bg-bg px-2 py-1.5 font-mono text-sm text-text"
				/>
				<label class="flex items-center gap-2 text-xs text-text-muted">
					<input bind:checked={targetEnabled} type="checkbox" class="h-4 w-4 rounded border-border" />
					Enable uploads for this target immediately
				</label>
				<div class="flex justify-end gap-2">
					<button
						type="button"
						onclick={closeForms}
						class="border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
					>
						Cancel
					</button>
					<button
						type="button"
						onclick={() => void handleSaveTarget()}
						disabled={savingTarget || !targetUrl.trim() || (editingTargetId === 'new' && !targetToken.trim())}
						class="border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{savingTarget ? 'Saving...' : 'Save'}
					</button>
				</div>
			</div>
		{/if}

		{#if showRegisterForm}
			<div class="grid gap-3 border border-border bg-surface px-3 py-3">
				<div class="text-sm font-medium text-text">Register a New SortHive Machine</div>
				<input
					bind:value={regTargetName}
					type="text"
					placeholder="Target name (for example Local or Live)"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regUrl}
					type="url"
					placeholder="https://sorthive.example.com"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regEmail}
					type="email"
					placeholder="Account email"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regPassword}
					type="password"
					placeholder="Account password"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regMachineName}
					type="text"
					placeholder="Machine name"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<input
					bind:value={regMachineDescription}
					type="text"
					placeholder="Machine description (optional)"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<div class="flex justify-end gap-2">
					<button
						type="button"
						onclick={closeForms}
						class="border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
					>
						Cancel
					</button>
					<button
						type="button"
						onclick={() => void handleRegister()}
						disabled={registering || !regUrl.trim() || !regEmail.trim() || !regPassword.trim() || !regMachineName.trim()}
						class="border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{registering ? 'Registering...' : 'Register'}
					</button>
				</div>
			</div>
		{/if}
	{/if}

	{#if errorMsg}
		<div class="border border-[#D01012] bg-[#D01012]/10 px-3 py-2 text-sm text-[#D01012] dark:border-[#D01012] dark:bg-[#D01012]/10 dark:text-red-400">
			{errorMsg}
		</div>
	{/if}
	{#if statusMsg}
		<div class="text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
