<script lang="ts">
	import { onMount } from 'svelte';
	import {
		machineHttpBaseUrlFromWsUrl,
		getBackendHttpBase,
		waitForBackend
	} from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Button from '$lib/components/ui/Button.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import GitBranch from '@lucide/svelte/icons/git-branch';
	import Tag from '@lucide/svelte/icons/tag';
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';

	const machine = getMachineContext();

	type CurrentVersion = {
		ref: string;
		branch: string | null;
		detached: boolean;
		describe: string;
		dirty: boolean;
		sha?: string;
		commit_unix?: number;
		subject?: string;
	};

	type VersionEntry = {
		kind: 'branch' | 'tag';
		channel?: string;
		name: string;
		sha: string;
		commit_unix: number;
		subject: string;
		is_current: boolean;
		up_to_date: boolean;
	};

	type VersionsPayload = {
		ok: boolean;
		current: CurrentVersion;
		available: VersionEntry[];
		fetch_error: string | null;
		update_in_progress: string | null;
	};

	let payload = $state<VersionsPayload | null>(null);
	let loading = $state(false);
	let loadError = $state<string | null>(null);
	let updatingRef = $state<string | null>(null);
	let updateError = $state<string | null>(null);
	let updateNotice = $state<string | null>(null);
	let depsWarning = $state<string | null>(null);

	// The ref this machine is on (branch or tag) that has moved on origin —
	// i.e. an update is available for whatever variant you're currently running.
	const currentUpdate = $derived(
		payload?.available.find((e) => e.is_current && !e.up_to_date) ?? null
	);
	// Which release channel (if any) the machine is currently sitting on.
	const currentChannel = $derived(
		payload?.available.find((e) => e.is_current && e.channel)?.channel ?? null
	);

	function httpBase(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function formatDate(unix: number | undefined): string {
		if (!unix) return '';
		return new Date(unix * 1000).toLocaleString();
	}

	async function load(refresh: boolean) {
		loading = true;
		loadError = null;
		try {
			const res = await fetch(`${httpBase()}/api/system/versions?refresh=${refresh}`);
			if (!res.ok) throw new Error(await res.text());
			payload = await res.json();
		} catch (e: any) {
			loadError = e.message ?? 'Failed to load versions';
		} finally {
			loading = false;
		}
	}

	async function applyUpdate(entry: VersionEntry) {
		updatingRef = `${entry.kind}:${entry.name}`;
		updateError = null;
		updateNotice = null;
		depsWarning = null;
		try {
			const res = await fetch(`${httpBase()}/api/system/update`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ kind: entry.kind, name: entry.name })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) {
				updateError = data.message ?? 'Update failed';
				return;
			}
			if (Array.isArray(data.deps_changed) && data.deps_changed.length > 0) {
				depsWarning = `Dependency files changed (${data.deps_changed.join(', ')}). A manual dependency install and service restart may be needed.`;
			}
			updateNotice = data.changed
				? `Updated ${data.old_sha} → ${data.new_sha}. Restarting backend...`
				: 'Already at this version. Restarting backend...';
			await waitForBackend(httpBase());
			// The update rebuilt the UI as well: load the new one.
			if (data.changed) location.reload();
			updateNotice = updateNotice.replace('Restarting backend...', 'Backend is back up.');
			await load(false);
		} catch (e: any) {
			updateError = e.message ?? 'Update failed';
		} finally {
			updatingRef = null;
		}
	}

	onMount(() => {
		void load(true);
	});
</script>

<div class="flex flex-col gap-4">
	<div class="border border-line bg-surface px-3 py-3">
		<div class="flex items-center gap-2">
			<span class="text-sm font-medium text-ink">Current version</span>
			{#if payload?.current.dirty}
				<span class="text-xs text-warning-ink">local changes present</span>
			{/if}
			<button
				type="button"
				class="ml-auto inline-flex items-center gap-1 text-sm text-ink-muted transition-colors hover:text-ink"
				title="Refresh from origin"
				disabled={loading}
				onclick={() => void load(true)}
			>
				<RefreshCcw size={14} class={loading ? 'animate-spin' : ''} />
			</button>
		</div>
		{#if payload}
			<div class="mt-2 flex flex-col gap-0.5">
				<div class="text-sm text-ink-muted">
					{#if currentChannel}
						Channel: <span class="text-ink capitalize">{currentChannel}</span>
					{:else}
						{payload.current.detached ? 'Version' : 'Branch'}:
						<span class="font-mono text-ink">{payload.current.ref}</span>
					{/if}
				</div>
				<div class="text-sm text-ink-muted">
					Commit:
					<span class="font-mono text-ink">{payload.current.sha}</span>
					{#if payload.current.subject}
						<span class="text-ink-muted"> — {payload.current.subject}</span>
					{/if}
				</div>
				{#if payload.current.commit_unix}
					<div class="text-sm text-ink-muted">{formatDate(payload.current.commit_unix)}</div>
				{/if}
			</div>
		{:else if loading}
			<div class="mt-2 text-sm text-ink-muted">Loading...</div>
		{/if}
		{#if currentUpdate}
			<div class="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3">
				<span class="text-sm text-ink-muted">
					New version available —
					<span class="font-mono text-ink">{currentUpdate.sha}</span>
				</span>
				<Button
					variant="primary"
					disabled={updatingRef !== null}
					loading={updatingRef === `${currentUpdate.kind}:${currentUpdate.name}`}
					onclick={() => void applyUpdate(currentUpdate)}
				>
					Update
				</Button>
			</div>
		{/if}
	</div>

	{#if payload?.fetch_error}
		<Alert tone="warning">Could not fetch from origin: {payload.fetch_error}</Alert>
	{/if}
	{#if loadError}
		<Alert tone="danger">{loadError}</Alert>
	{/if}
	{#if updateError}
		<Alert tone="danger">{updateError}</Alert>
	{/if}
	{#if updateNotice}
		<Alert tone="success">{updateNotice}</Alert>
	{/if}
	{#if depsWarning}
		<Alert tone="warning">{depsWarning}</Alert>
	{/if}

	{#if payload && payload.available.length > 0}
		<div class="border border-line">
			<div class="border-b border-line bg-surface px-3 py-2">
				<span class="text-sm font-medium text-ink">Release channels</span>
			</div>
			<ul class="divide-y divide-line">
				{#each payload.available as entry (entry.kind + entry.name)}
					<li class="flex items-center gap-3 px-3 py-2.5">
						{#if entry.kind === 'branch'}
							<GitBranch size={14} class="shrink-0 text-ink-muted" />
						{:else}
							<Tag size={14} class="shrink-0 text-ink-muted" />
						{/if}
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								{#if entry.channel}
									<span class="shrink-0 text-sm font-medium text-ink capitalize">{entry.channel}</span>
									<span class="truncate font-mono text-xs text-ink-muted">{entry.name}</span>
								{:else}
									<span class="truncate font-mono text-sm text-ink">{entry.name}</span>
								{/if}
								{#if entry.is_current && entry.up_to_date}
									<span class="shrink-0 text-xs text-success-ink">up to date</span>
								{:else if entry.is_current}
									<span class="shrink-0 text-xs text-ink-muted">current</span>
								{/if}
							</div>
							<div class="truncate text-xs text-ink-muted">
								<span class="font-mono">{entry.sha}</span>
								— {entry.subject} · {formatDate(entry.commit_unix)}
							</div>
						</div>
						{#if !entry.is_current}
							<Button
								variant="secondary"
								size="sm"
								disabled={updatingRef !== null}
								loading={updatingRef === `${entry.kind}:${entry.name}`}
								onclick={() => void applyUpdate(entry)}
							>
								{updatingRef === `${entry.kind}:${entry.name}` ? 'Switching...' : 'Switch'}
							</Button>
						{/if}
					</li>
				{/each}
			</ul>
		</div>
	{/if}

	<p class="text-sm text-ink-muted">
		Updating checks out the selected version on this machine, builds its UI and restarts the
		backend. Machine config (machine.toml, .env, sorting data) is never touched; local code edits
		are stashed, not lost.
	</p>
</div>
