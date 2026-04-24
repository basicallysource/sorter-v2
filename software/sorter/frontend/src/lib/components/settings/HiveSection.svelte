<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import Modal from '$lib/components/Modal.svelte';
	import { getMachineContext } from '$lib/machines/context';
	import {
		beginHiveLink,
		completeReturnedHiveLink,
		DEFAULT_HIVE_URL,
		defaultHiveTargetName,
		normalizeHiveBaseUrl
	} from '$lib/hive/link-flow';
	import {
		Cloud,
		ExternalLink,
		ListChecks,
		Pencil,
		Plus,
		RefreshCw,
		Trash2,
		Upload
	} from 'lucide-svelte';

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

	type HiveTarget = {
		id: string;
		name: string;
		url: string;
		machine_id: string | null;
		api_token_masked: string | null;
		enabled: boolean;
		uploader: UploaderStatus;
	};

	type HiveConfig = {
		configured_count: number;
		enabled_count: number;
		targets: HiveTarget[];
	};

	type LegacyHiveConfig = {
		configured?: boolean;
		url?: string;
		machine_id?: string | null;
		api_token_masked?: string | null;
		enabled?: boolean;
		uploader?: UploaderStatus | null;
	};

	let config = $state<HiveConfig | null>(null);
	let loading = $state(true);
	let statusMsg = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);
	let backfillResult = $state<string | null>(null);
	let backfillTargetId = $state<string | null>(null);
	let purgeResult = $state<string | null>(null);
	let purgeTargetId = $state<string | null>(null);

	let editingTargetId = $state<string | null>(null);
	let savingTarget = $state(false);
	let removingTargetId = $state<string | null>(null);
	let backfillingTargetId = $state<string | null>(null);
	let purgingTargetId = $state<string | null>(null);
	let linkingHive = $state(false);
	let linkModalOpen = $state(false);

	let targetName = $state('');
	let targetUrl = $state('');
	let targetEnabled = $state(true);
	let linkHiveUrl = $state(DEFAULT_HIVE_URL);

	const targets = $derived(config?.targets ?? []);
	const linkTargetPreview = $derived(defaultHiveTargetName(linkHiveUrl || DEFAULT_HIVE_URL));

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

	function normalizeConfig(raw: unknown): HiveConfig {
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
									: `Hive ${index + 1}`,
						url: typeof target.url === 'string' ? target.url : '',
						machine_id: typeof target.machine_id === 'string' ? target.machine_id : null,
						api_token_masked:
							typeof target.api_token_masked === 'string' ? target.api_token_masked : null,
						enabled,
						uploader: {
							...emptyUploaderStatus(enabled),
							...(uploaderRaw ?? {})
						}
					} satisfies HiveTarget
				];
			});

			return {
				configured_count: normalizedTargets.length,
				enabled_count: normalizedTargets.filter((target) => target.enabled).length,
				targets: normalizedTargets
			};
		}

		const legacy = data as LegacyHiveConfig;
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

	function getTarget(targetId: string | null): HiveTarget | null {
		if (!targetId) return null;
		return targets.find((target) => target.id === targetId) ?? null;
	}

	function clearMessages() {
		statusMsg = null;
		errorMsg = null;
		backfillResult = null;
		backfillTargetId = null;
		purgeResult = null;
		purgeTargetId = null;
	}

	function queueHref(target: HiveTarget): string {
		return `/settings/hive/queue?target_id=${encodeURIComponent(target.id)}`;
	}

	function resetTargetForm(target: HiveTarget | null = null) {
		targetName = target?.name ?? '';
		targetUrl = target?.url ?? '';
		targetEnabled = target?.enabled ?? true;
	}

	async function loadConfig() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive`);
			if (!res.ok) throw new Error(await res.text());
			config = normalizeConfig(await res.json());

			if (editingTargetId) {
				resetTargetForm(getTarget(editingTargetId));
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load Hive config.';
		} finally {
			loading = false;
		}
	}

	function openTargetEditor(target: HiveTarget | null = null) {
		clearMessages();
		if (!target) return;
		editingTargetId = target.id;
		resetTargetForm(target);
	}

	function closeForms() {
		editingTargetId = null;
		resetTargetForm();
	}

	function openHiveLinkModal() {
		clearMessages();
		linkModalOpen = true;
	}

	function suggestedMachineName(): string {
		const identity = machine.machine?.identity;
		return (
			(identity?.nickname ?? '').trim() ||
			(identity?.machine_id ?? '').trim() ||
			'Lego Sorter'
		);
	}

	async function handleHiveLinkReturn() {
		try {
			const result = await completeReturnedHiveLink(currentBackendBaseUrl());
			if (result.completed) {
				statusMsg =
					result.message ??
					`Connected ${result.machineName || result.targetName || 'this sorter'} to Hive.`;
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Hive link could not be completed.';
		}
	}

	function handleBeginHiveLink() {
		if (!linkHiveUrl.trim()) return;
		linkingHive = true;
		clearMessages();
		try {
			linkHiveUrl = normalizeHiveBaseUrl(linkHiveUrl);
			beginHiveLink({
				hiveUrl: linkHiveUrl,
				targetName: linkTargetPreview,
				machineName: suggestedMachineName(),
				returnPath: '/settings/hive'
			});
		} catch (e: any) {
			errorMsg = e.message ?? 'Hive link could not be started.';
			linkingHive = false;
		}
	}

	async function handleSaveTarget() {
		if (!targetUrl.trim()) return;
		const existing = editingTargetId ? getTarget(editingTargetId) : null;
		if (!existing) return;

		savingTarget = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					id: existing?.id ?? null,
					name: targetName.trim(),
					url: targetUrl.trim(),
					api_token: '',
					enabled: targetEnabled
				})
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = `Updated Hive target "${targetName.trim() || existing.name}" and kept the current token.`;
			closeForms();
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save Hive target.';
		} finally {
			savingTarget = false;
		}
	}

	async function handleRemoveTarget(target: HiveTarget) {
		if (!confirm(`Remove the Hive target "${target.name}" from this sorter?`)) return;
		removingTargetId = target.id;
		clearMessages();
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/settings/hive?target_id=${encodeURIComponent(target.id)}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) throw new Error(await res.text());
			statusMsg = `Removed Hive target "${target.name}".`;
			if (editingTargetId === target.id) {
				closeForms();
			}
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to remove Hive target.';
		} finally {
			removingTargetId = null;
		}
	}

	async function handleToggleEnabled(target: HiveTarget) {
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive`, {
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

	async function handleBackfill(target: HiveTarget) {
		backfillingTargetId = target.id;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/backfill`, {
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
			backfillResult =
				`Queued ${data.queued} archived samples for "${target.name}" ` +
				`(${data.skipped} skipped` +
				`${data.needs_gemini ? `, ${data.needs_gemini} need Gemini` : ''}` +
				`${data.no_teacher_detection ? `, ${data.no_teacher_detection} no Gemini box` : ''}` +
				`${data.bad_teacher_sample ? `, ${data.bad_teacher_sample} bad crop` : ''}` +
				`${data.errors ? `, ${data.errors} errors` : ''}).`;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Backfill failed.';
		} finally {
			backfillingTargetId = null;
		}
	}

	async function handlePurge(target: HiveTarget) {
		const queueHint =
			target.uploader.queue_size > 0
				? `This will remove ${target.uploader.queue_size} queued sync job${target.uploader.queue_size === 1 ? '' : 's'} for "${target.name}".`
				: `This will clear any queued or retrying sync jobs for "${target.name}".`;
		if (
			!confirm(
				`${queueHint} An upload that is already in flight may still finish.`
			)
		) {
			return;
		}

		purgingTargetId = target.id;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/purge`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_ids: [target.id]
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) throw new Error(data.error ?? 'Queue purge failed.');
			purgeTargetId = target.id;
			purgeResult =
				data.purged > 0
					? `Purged ${data.purged} queued sample sync job${data.purged === 1 ? '' : 's'} for "${target.name}".`
					: `No queued sample sync jobs were waiting for "${target.name}".`;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Queue purge failed.';
		} finally {
			purgingTargetId = null;
		}
	}

	function statusLabel(target: HiveTarget): string {
		if (!target.enabled) return 'Connected, uploads disabled';
		if (target.uploader.server_reachable) return 'Connected and ready';
		return 'Connected, waiting for server';
	}

	function statusToneClass(target: HiveTarget): string {
		if (!target.enabled) return 'text-amber-600 dark:text-amber-400';
		if (target.uploader.server_reachable) return 'text-success dark:text-emerald-400';
		return 'text-amber-600 dark:text-amber-400';
	}

	onMount(() => {
		void (async () => {
			await handleHiveLinkReturn();
			const linkError = errorMsg;
			await loadConfig();
			if (linkError && !errorMsg) {
				errorMsg = linkError;
			}
		})();
	});
</script>

<div class="grid gap-4">
	{#if loading}
		<div class="text-sm text-text-muted">Loading Hive configuration...</div>
	{:else if config}
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="text-sm text-text-muted">
				{#if targets.length > 0}
					{config.enabled_count} of {config.configured_count} Hive target{config.configured_count === 1 ? '' : 's'} enabled.
				{:else}
					No Hive targets configured yet.
				{/if}
			</div>
			<div class="flex flex-wrap gap-2">
				<button
					type="button"
					onclick={openHiveLinkModal}
					class="inline-flex items-center gap-1.5 border border-success bg-success px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-success/90"
				>
					<Plus size={12} />
					Hive koppeln
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
				<a
					href="/settings/hive/queue"
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
					title="Open Hive queue details"
				>
					<ListChecks size={12} />
					Queue
				</a>
			</div>
		</div>

		{#if targets.length === 0}
			<div class="border border-border bg-surface px-3 py-3">
				<div class="text-sm text-text-muted">
					Noch kein Hive verbunden. Klicke oben auf
					<span class="font-medium text-text">Hive koppeln</span>,
					um das offizielle Hive oder eine lokale Instanz zu verbinden.
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
									onclick={() => void handlePurge(target)}
									disabled={purgingTargetId === target.id}
									class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
								>
									<Trash2 size={12} />
									{purgingTargetId === target.id ? 'Purging...' : 'Purge Queue'}
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
									class="inline-flex items-center gap-1.5 border border-danger bg-danger px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-danger/80 disabled:cursor-not-allowed disabled:opacity-50 dark:border-danger dark:bg-danger dark:hover:bg-danger/80"
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
							<div class="mt-3 border border-success bg-success/10 px-3 py-2 text-sm font-medium text-success dark:border-success dark:bg-success/10 dark:text-emerald-200">
								{backfillResult}
							</div>
						{/if}

						{#if purgeTargetId === target.id && purgeResult}
							<div class="mt-3 border border-amber-500 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-700 dark:border-amber-400 dark:bg-amber-400/10 dark:text-amber-200">
								{purgeResult}
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
								<a
									href={queueHref(target)}
									class="group border border-transparent px-2 py-1 transition-colors hover:border-border hover:bg-bg"
									title={`Open queue details for ${target.name}`}
								>
									<div class="font-mono text-lg font-semibold text-text tabular-nums group-hover:text-primary">
										{target.uploader.queue_size}
									</div>
									<div class="text-text-muted">Queued</div>
								</a>
								<div>
									<div class="text-lg font-semibold {target.uploader.requeued > 0 ? 'text-amber-500' : 'text-text'}">{target.uploader.requeued}</div>
									<div class="text-text-muted">Requeued</div>
								</div>
								<div>
									<div class="text-lg font-semibold {target.uploader.failed > 0 ? 'text-danger' : 'text-text'}">{target.uploader.failed}</div>
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
					Edit {getTarget(editingTargetId)?.name ?? 'Hive Target'}
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
					placeholder="https://hive.example.com"
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<div class="text-xs text-text-muted">
					Der bestehende Token bleibt erhalten. Wenn du einen neuen Token brauchst, starte oben
					den Hive-Link erneut.
				</div>
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
						disabled={savingTarget || !targetUrl.trim()}
						class="border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						{savingTarget ? 'Saving...' : 'Save'}
					</button>
				</div>
			</div>
		{/if}
	{/if}

	{#if errorMsg}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:border-danger dark:bg-danger/10 dark:text-red-400">
			{errorMsg}
		</div>
	{/if}
	{#if statusMsg}
		<div class="text-sm text-text-muted">{statusMsg}</div>
	{/if}

	<Modal bind:open={linkModalOpen} title="Hive koppeln">
		<div class="grid gap-4">
			<div class="grid gap-1">
				<div class="flex items-center gap-2 text-sm font-medium text-text">
					<Cloud size={14} class="text-text-muted" />
					Hive-Instanz auswählen
				</div>
				<p class="text-sm leading-relaxed text-text-muted">
					Der Sorter öffnet die angegebene Hive-Instanz. Dort meldest du dich an,
					benennst die Maschine und bestätigst die Kopplung. Der API-Token wird danach
					automatisch zurückgegeben und hier gespeichert.
				</p>
			</div>

			<label class="grid gap-1">
				<span class="text-xs font-medium text-text">Hive URL</span>
				<input
					bind:value={linkHiveUrl}
					type="url"
					placeholder={DEFAULT_HIVE_URL}
					class="border border-border bg-bg px-3 py-2 font-mono text-sm text-text"
				/>
			</label>

			<div class="border border-border bg-surface px-3 py-2 text-xs text-text-muted">
				Zielname:
				<span class="font-medium text-text">{linkTargetPreview}</span>
			</div>

			<div class="flex flex-wrap justify-end gap-2">
				<button
					type="button"
					onclick={() => {
						linkModalOpen = false;
					}}
					disabled={linkingHive}
					class="border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
				>
					Abbrechen
				</button>
				<button
					type="button"
					onclick={handleBeginHiveLink}
					disabled={linkingHive || !linkHiveUrl.trim()}
					class="inline-flex min-h-10 items-center justify-center gap-2 border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
				>
					{#if linkingHive}
						Weiterleiten...
					{:else}
						<ExternalLink size={14} />
						In Hive fortfahren
					{/if}
				</button>
			</div>
		</div>
	</Modal>
</div>
