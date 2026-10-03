<script lang="ts">
	import { sentence } from '$lib/text';
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
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';

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
		parts: 'Full part catalog from Rebrickable (the largest sync; it pages, and resumes).',
		categories: 'Rebrickable part categories.',
		colors: 'Rebrickable color list.',
		prices: 'BrickLink price guide (requires BLA_API_KEY).',
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

<svelte:head><title>Catalog sync - Hive</title></svelte:head>

<div class="mx-auto flex w-full max-w-3xl flex-col gap-(--gap-panels)">
	<div>
		<Button href="/settings" size="sm" variant="ghost" icon={ArrowLeft}>Settings</Button>
	</div>
	<PageHeader
		title="Catalog sync"
		description="The Rebrickable and BrickLink catalog. A sync picks up where it stopped: if the server restarts during one, start the same one again."
	/>

	{#if error}<Alert tone="danger" class="wrap-anywhere">{error}</Alert>{/if}
	{#if actionError}<Alert tone="danger">{actionError}</Alert>{/if}

	{#if loading && !status}
		<div class="flex justify-center p-8"><Spinner size={32} /></div>
	{:else if status}
		<Panel flush>
			<div class="px-(--pad-panel) py-1">
				<KeyValue
					items={[
						{ label: 'Sync on its own', value: status.auto_sync_enabled ? 'On' : 'Off' },
						{ label: 'Running now', value: status.sync_type ? sentence(status.sync_type) : 'Nothing' },
						{ label: 'Last checked', value: fmtTime(status.auto_sync_last_checked_at) }
					]}
				/>
			</div>
		</Panel>

		{#each orderedTypes as [type, state] (type)}
			{@const percent = pct(state)}
			<Panel title={TYPE_LABELS[type]} description={TYPE_BLURBS[type]}>
				{#snippet actions()}
					<Badge tone={badgeVariant(state.status)}>{sentence(state.status)}</Badge>
				{/snippet}
				<div class="flex flex-col gap-3">
					{#if percent !== null}
						<div>
							<div class="num mb-1.5 flex justify-between text-sm text-ink-muted">
								<span>{state.progress_current ?? 0} of {state.progress_total}</span>
								<span>{percent}%</span>
							</div>
							<ProgressBar label={`${TYPE_LABELS[type]} progress`} value={percent} />
						</div>
					{/if}
					{#if state.last_message}<p class="text-sm break-words text-ink">{state.last_message}</p>{/if}
					{#if state.error && state.status !== 'running'}<Alert tone="danger" class="wrap-anywhere">{state.error}</Alert>{/if}
					<div class="flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-muted">
						{#if state.cached_count !== null}
							<span>Cached <span class="num text-ink">{state.cached_count}</span></span>
						{/if}
						<span>Last finished {fmtTime(state.last_synced_at)}</span>
						{#if state.pages_fetched > 0}<span>Pages this run <span class="num text-ink">{state.pages_fetched}</span></span>{/if}
					</div>
				</div>
				{#snippet footer()}
					{#if state.status === 'running'}
						<Button variant="danger" loading={busy === 'stop'} disabled={busy !== null} onclick={stopSync}>Stop</Button>
					{:else}
						<Button
							variant="primary"
							loading={busy === type}
							disabled={anyRunning || busy !== null}
							onclick={() => startSync(type)}>{actionLabel(state.status)}</Button
						>
					{/if}
				{/snippet}
			</Panel>
		{/each}
	{/if}
</div>
