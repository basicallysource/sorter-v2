<script lang="ts">
	import {
		CheckCircle2,
		ExternalLink,
		Loader2,
		Plus,
		RefreshCcw,
		RotateCcw,
		ShieldAlert
	} from 'lucide-svelte';
	import type { HiveConfigBackupSummary, HiveSetupTarget } from '$lib/setup/wizard-types';

	type IdentityMode = 'new' | 'restore';

	let {
		machineId,
		mode = $bindable(),
		nicknameDraft = $bindable(),
		nameError,
		nameStatus,
		officialHiveTarget,
		defaultHiveUrl,
		hiveUrl = $bindable(),
		hiveConnecting,
		restoreBackups,
		restoreLoadingBackups,
		restoreSelectedVersion = $bindable(),
		restoreIncludeCalibration = $bindable(),
		restoreApplying,
		restoreError,
		restoreStatus,
		restoreApplied,
		onConnectRestore,
		onRefreshBackups,
		onRestore
	}: {
		machineId: string;
		mode: IdentityMode;
		nicknameDraft: string;
		nameError: string | null;
		nameStatus: string;
		officialHiveTarget: HiveSetupTarget | null;
		defaultHiveUrl: string;
		hiveUrl: string;
		hiveConnecting: boolean;
		restoreBackups: HiveConfigBackupSummary[];
		restoreLoadingBackups: boolean;
		restoreSelectedVersion: number | null;
		restoreIncludeCalibration: boolean;
		restoreApplying: boolean;
		restoreError: string | null;
		restoreStatus: string | null;
		restoreApplied: boolean;
		onConnectRestore: () => void;
		onRefreshBackups: () => void;
		onRestore: () => void;
	} = $props();

	const MACHINE_NAME_INPUT_ID = 'setup-machine-name';

	function shortHash(hash: string): string {
		return hash ? hash.slice(0, 10) : 'unknown';
	}

	function backupLabel(backup: HiveConfigBackupSummary): string {
		const created = new Date(backup.created_at);
		const date = Number.isNaN(created.getTime())
			? backup.created_at
			: created.toLocaleString(undefined, {
					dateStyle: 'medium',
					timeStyle: 'short'
				});
		return `Version ${backup.version} · ${date}`;
	}
</script>

<div class="flex flex-col gap-4">
	<div class="grid gap-2 sm:grid-cols-2">
		<button
			type="button"
			onclick={() => {
				mode = 'new';
			}}
			class={`setup-panel flex min-h-24 items-start gap-3 px-4 py-3 text-left transition-colors ${
				mode === 'new' ? 'border-success/50 bg-success/[0.06]' : 'hover:border-primary'
			}`}
		>
			<div class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center border border-border bg-bg text-text">
				<Plus size={16} />
			</div>
			<div class="min-w-0">
				<div class="text-sm font-semibold text-text">Set up as new</div>
				<div class="mt-1 text-xs leading-relaxed text-text-muted">
					Use this device's fresh local identity and continue through hardware setup.
				</div>
			</div>
		</button>
		<button
			type="button"
			onclick={() => {
				mode = 'restore';
			}}
			class={`setup-panel flex min-h-24 items-start gap-3 px-4 py-3 text-left transition-colors ${
				mode === 'restore' ? 'border-success/50 bg-success/[0.06]' : 'hover:border-primary'
			}`}
		>
			<div class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center border border-border bg-bg text-text">
				<RotateCcw size={16} />
			</div>
			<div class="min-w-0">
				<div class="text-sm font-semibold text-text">Restore from Hive</div>
				<div class="mt-1 text-xs leading-relaxed text-text-muted">
					Reconnect to an existing machine profile and pull its latest settings.
				</div>
			</div>
		</button>
	</div>

	<div class="text-xs text-text-muted">
		Local machine ID:
		<span class="font-mono text-text">{machineId || '-'}</span>
	</div>

	{#if mode === 'new'}
		<div>
			<label for={MACHINE_NAME_INPUT_ID} class="mb-2 block text-sm font-medium text-text">
				Machine name
			</label>
			<input
				id={MACHINE_NAME_INPUT_ID}
				type="text"
				bind:value={nicknameDraft}
				placeholder="e.g. Sorting Bench A"
				class="setup-control w-full px-3 py-2 text-sm text-text"
			/>
		</div>
		{#if nameError}
			<div class="text-sm text-danger">{nameError}</div>
		{:else if nameStatus}
			<div class="text-sm text-success">{nameStatus}</div>
		{/if}
	{:else}
		<div class="setup-panel flex flex-col gap-3 px-4 py-3">
			<div class="flex flex-col gap-2 sm:flex-row sm:items-end">
				<label class="min-w-0 flex-1">
					<span class="mb-2 block text-sm font-medium text-text">Hive server</span>
					<input
						type="url"
						bind:value={hiveUrl}
						placeholder={defaultHiveUrl}
						class="setup-control w-full px-3 py-2 font-mono text-sm text-text"
						disabled={hiveConnecting || restoreApplying}
					/>
				</label>
				<button
					type="button"
					onclick={onConnectRestore}
					disabled={hiveConnecting || restoreApplying || !hiveUrl.trim()}
					class="setup-button-primary inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
				>
					{#if hiveConnecting}
						<Loader2 size={14} class="animate-spin" />
						Opening Hive...
					{:else}
						<ExternalLink size={14} />
						Connect
					{/if}
				</button>
			</div>

			{#if officialHiveTarget}
				<div class="flex items-start gap-2 border border-success/40 bg-success/[0.06] px-3 py-2 text-sm text-text">
					<CheckCircle2 size={16} class="mt-0.5 shrink-0 text-success" />
					<div class="min-w-0">
						<div class="font-medium">Connected to {officialHiveTarget.name}</div>
						<div class="truncate font-mono text-xs text-text-muted">{officialHiveTarget.url}</div>
					</div>
				</div>
			{/if}
		</div>

		<div class="setup-panel flex flex-col gap-3 px-4 py-3">
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div>
					<div class="text-sm font-semibold text-text">Machine backups</div>
					<div class="text-xs text-text-muted">Settings restore skips live motor positions by default.</div>
				</div>
				<button
					type="button"
					onclick={onRefreshBackups}
					disabled={restoreLoadingBackups || restoreApplying || !officialHiveTarget}
					class="setup-button-secondary inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
				>
					<RefreshCcw size={13} class={restoreLoadingBackups ? 'animate-spin' : ''} />
					Refresh
				</button>
			</div>

			{#if restoreLoadingBackups}
				<div class="flex items-center gap-2 text-sm text-text-muted">
					<Loader2 size={14} class="animate-spin" />
					Loading backups...
				</div>
			{:else if restoreBackups.length > 0}
				<label class="grid gap-1">
					<span class="text-sm font-medium text-text">Version</span>
					<select
						bind:value={restoreSelectedVersion}
						disabled={restoreApplying}
						class="setup-control px-3 py-2 text-sm text-text"
					>
						{#each restoreBackups as backup}
							<option value={backup.version}>
								{backupLabel(backup)} · {backup.trigger} · {shortHash(backup.content_hash)}
							</option>
						{/each}
					</select>
				</label>
				<label class="flex items-start gap-2 text-sm text-text-muted">
					<input
						type="checkbox"
						bind:checked={restoreIncludeCalibration}
						disabled={restoreApplying}
						class="mt-1"
					/>
					<span>
						Also restore stored stepper and servo positions.
					</span>
				</label>
				<button
					type="button"
					onclick={onRestore}
					disabled={restoreApplying || restoreSelectedVersion === null}
					class="inline-flex items-center justify-center gap-2 border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
				>
					{#if restoreApplying}
						<Loader2 size={14} class="animate-spin" />
						Restoring...
					{:else}
						<RotateCcw size={14} />
						Restore selected version
					{/if}
				</button>
			{:else}
				<div class="text-sm text-text-muted">
					{officialHiveTarget ? 'No backups found for this Hive machine yet.' : 'Connect to Hive first.'}
				</div>
			{/if}
		</div>

		{#if restoreIncludeCalibration}
			<div class="flex items-start gap-2 border border-warning/40 bg-warning/[0.08] px-3 py-2 text-sm text-text">
				<ShieldAlert size={16} class="mt-0.5 shrink-0 text-warning" />
				<div>
					Stored positions can be stale after transport or mechanical changes. Home the machine before running.
				</div>
			</div>
		{/if}

		{#if restoreError}
			<div class="border border-danger/40 bg-danger/[0.06] px-3 py-2 text-sm text-danger">
				{restoreError}
			</div>
		{:else if restoreStatus}
			<div
				class={`border px-3 py-2 text-sm ${
					restoreApplied
						? 'border-success/40 bg-success/[0.06] text-text'
						: 'border-border bg-bg text-text-muted'
				}`}
			>
				{restoreStatus}
			</div>
		{/if}
	{/if}
</div>
