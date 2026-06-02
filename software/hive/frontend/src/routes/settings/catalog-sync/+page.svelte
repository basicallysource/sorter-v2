<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth.svelte';
	import {
		api,
		type ProfileCatalogStatus,
		type CatalogSyncType,
		type CatalogSyncStatus,
		type CatalogSyncTypeState
	} from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import { Button, Alert } from '$lib/components/primitives';

	const REFRESH_MS = 2000;

	const TYPE_ORDER: CatalogSyncType[] = ['parts', 'categories', 'colors', 'prices', 'brickstore', 'geometry'];
	const TYPE_LABELS: Record<CatalogSyncType, string> = {
		parts: 'Parts',
		categories: 'Categories',
		colors: 'Colors',
		prices: 'BrickLink Prices',
		brickstore: 'BrickStore Import',
		geometry: 'LDraw Geometry'
	};
	const TYPE_BLURBS: Record<CatalogSyncType, string> = {
		parts: 'Full part catalog from Rebrickable (largest sync — paginated, resumable).',
		categories: 'Rebrickable part categories.',
		colors: 'Rebrickable color list.',
		prices: 'BrickLink affiliate price guide (requires BL_AFFILIATE_API_KEY).',
		brickstore: 'Import from a local BrickStore database file.',
		geometry: 'True part dimensions in mm from the LDraw library (downloads ~135MB on first run).'
	};

	let status = $state<ProfileCatalogStatus | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let actionError = $state<string | null>(null);
	let busy = $state<CatalogSyncType | 'stop' | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void load();
		timer = setInterval(load, REFRESH_MS);
		return () => {
			if (timer) clearInterval(timer);
		};
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	function errText(e: unknown): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: 'Request failed';
	}

	async function load() {
		try {
			status = await api.getProfileCatalogStatus();
			error = null;
		} catch (e: unknown) {
			error = errText(e);
		} finally {
			loading = false;
		}
	}

	async function startSync(type: CatalogSyncType) {
		actionError = null;
		busy = type;
		try {
			await api.startProfileCatalogSync(type);
			await load();
		} catch (e: unknown) {
			actionError = errText(e);
		} finally {
			busy = null;
		}
	}

	async function stopSync() {
		actionError = null;
		busy = 'stop';
		try {
			await api.stopProfileCatalogSync();
			await load();
		} catch (e: unknown) {
			actionError = errText(e);
		} finally {
			busy = null;
		}
	}

	function badgeVariant(s: CatalogSyncStatus): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
		if (s === 'running') return 'info';
		if (s === 'completed') return 'success';
		if (s === 'error') return 'danger';
		if (s === 'interrupted') return 'warning';
		return 'neutral';
	}

	function actionLabel(s: CatalogSyncStatus): string {
		if (s === 'interrupted' || s === 'stopped' || s === 'error') return 'Resume';
		if (s === 'completed') return 'Re-sync';
		return 'Sync';
	}

	function pct(state: CatalogSyncTypeState): number | null {
		if (!state.progress_total || state.progress_total <= 0) return null;
		const current = state.progress_current ?? 0;
		return Math.min(100, Math.round((current / state.progress_total) * 100));
	}

	function fmtTime(iso: string | null): string {
		if (!iso) return 'never';
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return iso;
		return d.toLocaleString();
	}

	let anyRunning = $derived(status?.running ?? false);
	let orderedTypes = $derived(
		status ? TYPE_ORDER.filter((t) => status!.types[t]).map((t) => [t, status!.types[t]] as const) : []
	);
</script>

<svelte:head><title>Catalog Sync · Hive</title></svelte:head>

<div class="mx-auto max-w-3xl px-4 py-8">
	<div class="mb-6 flex items-center justify-between">
		<div>
			<a href="/settings" class="text-sm text-text-muted hover:text-text">← Settings</a>
			<h1 class="mt-1 text-2xl font-bold text-text">Catalog Sync</h1>
			<p class="text-sm text-text-muted">
				Manage the Rebrickable / BrickLink catalog. Syncs resume where they left off — if the
				server restarts mid-sync, just start the same one again.
			</p>
		</div>
	</div>

	{#if error}
		<div class="mb-4"><Alert variant="danger">{error}</Alert></div>
	{/if}
	{#if actionError}
		<div class="mb-4"><Alert variant="danger">{actionError}</Alert></div>
	{/if}

	{#if loading && !status}
		<Spinner />
	{:else if status}
		<div class="mb-6 border border-border bg-bg p-4 text-sm text-text-muted">
			<div class="flex flex-wrap gap-x-6 gap-y-1">
				<span>
					Auto-sync:
					<span class="font-medium text-text">{status.auto_sync_enabled ? 'on' : 'off'}</span>
				</span>
				<span>
					Currently running:
					<span class="font-medium text-text">{status.sync_type ?? 'nothing'}</span>
				</span>
				<span>Last checked: {fmtTime(status.auto_sync_last_checked_at)}</span>
			</div>
		</div>

		<div class="space-y-4">
			{#each orderedTypes as [type, state] (type)}
				{@const percent = pct(state)}
				<div class="border border-border bg-surface p-5">
					<div class="flex items-start justify-between gap-3">
						<div>
							<div class="flex items-center gap-2">
								<h2 class="font-semibold text-text">{TYPE_LABELS[type]}</h2>
								<Badge text={state.status} variant={badgeVariant(state.status)} />
							</div>
							<p class="mt-1 text-xs text-text-muted">{TYPE_BLURBS[type]}</p>
						</div>
						<div class="flex shrink-0 gap-2">
							{#if state.status === 'running'}
								<Button
									variant="danger"
									size="sm"
									loading={busy === 'stop'}
									disabled={busy !== null}
									onclick={stopSync}
								>
									Stop
								</Button>
							{:else}
								<Button
									variant="primary"
									size="sm"
									loading={busy === type}
									disabled={anyRunning || busy !== null}
									onclick={() => startSync(type)}
								>
									{actionLabel(state.status)}
								</Button>
							{/if}
						</div>
					</div>

					{#if percent !== null}
						<div class="mt-4">
							<div class="mb-1 flex justify-between text-xs text-text-muted">
								<span>{state.progress_current ?? 0} / {state.progress_total}</span>
								<span>{percent}%</span>
							</div>
							<div class="h-2 bg-bg">
								<div
									class="h-full bg-primary transition-[width] duration-300"
									style="width: {percent}%"
								></div>
							</div>
						</div>
					{/if}

					{#if state.last_message}
						<p class="mt-3 text-sm text-text">{state.last_message}</p>
					{/if}

					{#if state.error && state.status !== 'running'}
						<div class="mt-3"><Alert variant="danger">{state.error}</Alert></div>
					{/if}

					<div class="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-text-muted">
						{#if state.cached_count !== null}
							<span>Cached: <span class="font-medium text-text">{state.cached_count}</span></span>
						{/if}
						<span>Last completed: {fmtTime(state.last_synced_at)}</span>
						{#if state.pages_fetched > 0}
							<span>Pages this run: {state.pages_fetched}</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
