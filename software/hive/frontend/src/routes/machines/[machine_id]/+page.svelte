<script lang="ts">
	import { page } from '$app/state';
	import {
		api,
		type Machine,
		type MachineConfigBackupSummary,
		type MachineConfigBackupDetail
	} from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Alert } from '$lib/components/primitives';

	const machineId = $derived(page.params.machine_id ?? '');

	let machine = $state<Machine | null>(null);
	let backups = $state<MachineConfigBackupSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let expanded = $state<number | null>(null);
	let detail = $state<MachineConfigBackupDetail | null>(null);
	let detailLoading = $state(false);

	function formatDate(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('de-DE', {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function triggerVariant(trigger: string): 'success' | 'neutral' | 'warning' {
		if (trigger === 'manual') return 'warning';
		if (trigger === 'heartbeat') return 'neutral';
		return 'success';
	}

	$effect(() => {
		const id = machineId;
		if (!id) return;
		loading = true;
		error = null;
		Promise.all([api.getMachines({ scope: 'mine' }), api.getMachineConfigBackups(id)])
			.then(([machines, backupList]) => {
				machine = machines.find((m) => m.id === id) ?? null;
				backups = backupList;
				if (!machine) error = 'Machine not found (or not owned by you).';
			})
			.catch((err) => {
				error = (err as { error?: string }).error || 'Failed to load machine.';
			})
			.finally(() => {
				loading = false;
			});
	});

	async function toggle(version: number) {
		if (expanded === version) {
			expanded = null;
			detail = null;
			return;
		}
		expanded = version;
		detail = null;
		detailLoading = true;
		try {
			detail = await api.getMachineConfigBackup(machineId, version);
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to load backup detail.';
		} finally {
			detailLoading = false;
		}
	}

	function localStateKeys(d: MachineConfigBackupDetail): string[] {
		const ls = (d.payload?.local_state ?? {}) as Record<string, unknown>;
		return Object.entries(ls)
			.filter(([, v]) => v !== null && v !== undefined)
			.map(([k]) => k);
	}

	function tomlText(d: MachineConfigBackupDetail): string {
		const t = d.payload?.toml_text;
		return typeof t === 'string' ? t : '';
	}
</script>

<div class="mx-auto max-w-4xl px-4 py-8">
	<a href="/machines" class="text-sm text-text-muted hover:text-primary hover:underline">← Machines</a>

	{#if loading}
		<div class="mt-8 flex justify-center"><Spinner /></div>
	{:else if error}
		<div class="mt-6"><Alert variant="danger">{error}</Alert></div>
	{:else if machine}
		<header class="mt-3 border border-border bg-surface p-5">
			<div class="flex items-start justify-between gap-4">
				<div class="min-w-0">
					<h1 class="text-xl font-semibold text-text">{machine.name}</h1>
					{#if machine.description}
						<p class="mt-1 text-sm text-text-muted">{machine.description}</p>
					{/if}
				</div>
				<Badge text={machine.is_active ? 'Active' : 'Inactive'} variant={machine.is_active ? 'success' : 'neutral'} />
			</div>
			<dl class="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
				<div>
					<dt class="text-text-muted">Last seen</dt>
					<dd class="text-text">{formatDate(machine.last_seen_at)}</dd>
				</div>
				<div>
					<dt class="text-text-muted">Token</dt>
					<dd class="text-text">{machine.token_prefix}…</dd>
				</div>
				<div>
					<dt class="text-text-muted">Added</dt>
					<dd class="text-text">{formatDate(machine.created_at)}</dd>
				</div>
			</dl>
		</header>

		<section class="mt-6">
			<div class="flex items-baseline justify-between">
				<h2 class="text-lg font-semibold text-text">Config backups</h2>
				<span class="text-sm text-text-muted">{backups.length} version{backups.length === 1 ? '' : 's'}</span>
			</div>
			<p class="mt-1 text-sm text-text-muted">
				Versioned snapshots of this machine's settings. A new version is stored only when the config
				actually changes.
			</p>

			{#if backups.length === 0}
				<div class="mt-4 border border-border bg-surface p-6 text-center text-sm text-text-muted">
					No backups yet. The machine pushes one automatically once its settings are saved.
				</div>
			{:else}
				<div class="mt-4 border border-border bg-surface">
					{#each backups as backup (backup.id)}
						<div class="border-b border-border last:border-b-0">
							<button
								type="button"
								onclick={() => toggle(backup.version)}
								class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-bg"
							>
								<span class="font-mono text-sm font-semibold text-text">v{backup.version}</span>
								<Badge text={backup.trigger} variant={triggerVariant(backup.trigger)} />
								<span class="text-sm text-text-muted">{formatDate(backup.created_at)}</span>
								<span class="ml-auto font-mono text-xs text-text-muted">{backup.content_hash.slice(0, 12)}</span>
								<span class="text-text-muted">{expanded === backup.version ? '▾' : '▸'}</span>
							</button>
							{#if expanded === backup.version}
								<div class="border-t border-border bg-bg px-4 py-3">
									{#if detailLoading}
										<div class="flex justify-center py-4"><Spinner /></div>
									{:else if detail}
										<div class="mb-2 text-xs font-semibold tracking-wider text-text-muted uppercase">
											local_state
										</div>
										{#if localStateKeys(detail).length > 0}
											<div class="mb-4 flex flex-wrap gap-2">
												{#each localStateKeys(detail) as key}
													<span class="bg-primary-light px-2 py-0.5 text-xs text-text">{key}</span>
												{/each}
											</div>
										{:else}
											<p class="mb-4 text-sm text-text-muted">No local_state captured.</p>
										{/if}
										<div class="mb-2 text-xs font-semibold tracking-wider text-text-muted uppercase">
											machine_params.toml
										</div>
										<pre class="max-h-96 overflow-auto border border-border bg-surface p-3 text-xs text-text">{tomlText(detail) || '(empty)'}</pre>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</section>
	{/if}
</div>
