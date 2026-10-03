<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth.svelte';
	import { api, type ServerHealth } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Button from '$lib/components/Button.svelte';

	let health = $state<ServerHealth | null>(null);
	let loading = $state(true);
	let refreshing = $state(false);
	let error = $state<string | null>(null);
	let refreshQueued = $state(false);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void load();
	});

	async function load(refreshStorage = false) {
		error = null;
		if (refreshStorage) refreshing = true;
		else loading = true;
		try {
			health = await api.getServerHealth({ refreshStorage });
			if (refreshStorage) refreshQueued = true;
		} catch (e: unknown) {
			error = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to load server health';
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	function bytes(n: number | null | undefined): string {
		if (n == null) return '-';
		if (n === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
		return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
	}

	function num(n: number | null | undefined): string {
		return n != null ? Math.round(n).toLocaleString() : '-';
	}

	const storageParts = $derived(
		health
			? [
					{ key: 'sample_images', label: 'Sample images', color: 'var(--primary)', ...health.storage.sample_images },
					{ key: 'piece_images', label: 'Piece images', color: 'var(--success)', ...health.storage.piece_images },
					{ key: 'model_files', label: 'Model files', color: 'var(--info)', ...health.storage.model_files }
				]
			: []
	);
	const storageTotal = $derived(health?.storage.total_bytes ?? 0);

	const memUsedPct = $derived(
		health && health.memory.total_bytes && health.memory.used_bytes
			? Math.round((health.memory.used_bytes / health.memory.total_bytes) * 100)
			: null
	);

	function storageAsOf(): string {
		if (!health || health.storage.computed_at == null) return 'not yet computed';
		return new Date(health.storage.computed_at * 1000).toLocaleString();
	}
</script>

<svelte:head>
	<title>Server health - Hive</title>
</svelte:head>

<PageHeader title="Server health" description="Picture storage, the database's size and memory.">
	{#snippet actions()}
		<Button icon={RefreshCw} loading={refreshing} onclick={() => load(true)}>Refresh storage</Button>
	{/snippet}
</PageHeader>

<div class="flex flex-col gap-(--gap-panels)">
	{#if error}<Alert tone="danger">{error}</Alert>{/if}
	{#if refreshQueued}
		<Alert tone="info" title="Storage refresh started">
			A background walk of the object store is running. Reload in a few minutes for the new figures.
		</Alert>
	{/if}

	{#if loading}
		<div class="flex justify-center py-12"><Spinner size={32} /></div>
	{:else if health}
		<Panel
			title="Pictures and files"
			description={`${num(health.storage.total_files)} files, as of ${storageAsOf()}${health.storage.pending ? '; the first walk is still running' : ''}.`}
			flush
		>
			{#snippet actions()}<span class="num text-2xl font-medium text-ink">{bytes(storageTotal)}</span>{/snippet}
			{#if storageTotal > 0}
				<div class="px-(--pad-panel) pb-4">
					<div class="flex h-3 w-full overflow-hidden rounded-badge bg-track">
						{#each storageParts as part (part.key)}
							{#if part.bytes > 0}
								<div style="width: {(part.bytes / storageTotal) * 100}%; background: {part.color}"></div>
							{/if}
						{/each}
					</div>
				</div>
			{/if}
			<div class="-ml-px grid grid-cols-1 sm:grid-cols-3">
				{#each storageParts as part (part.key)}
					<div class="border-t border-l border-line p-4">
						<div class="flex items-center gap-2 text-sm">
							<span class="size-2.5 rounded-full" style="background: {part.color}"></span>
							<span class="text-ink">{part.label}</span>
						</div>
						<p class="num mt-1 text-xl font-medium text-ink">{bytes(part.bytes)}</p>
						<p class="num text-sm text-ink-muted">{num(part.files)} files</p>
					</div>
				{/each}
			</div>
		</Panel>

		<Panel title="Memory">
			{#if health.memory.total_bytes == null}
				<p class="text-sm text-ink-muted">Not available here: the server is not Linux, or it cannot read /proc.</p>
			{:else}
				<div class="mb-2 flex items-baseline justify-between text-sm">
					<span class="text-ink-muted">Used</span>
					<span class="num text-ink"
						>{bytes(health.memory.used_bytes)} of {bytes(health.memory.total_bytes)}{#if memUsedPct != null}{' '}<span class="text-ink-muted">({memUsedPct}%)</span>{/if}</span
					>
				</div>
				<ProgressBar
					label="Memory used"
					value={memUsedPct ?? 0}
					tone={memUsedPct != null && memUsedPct >= 90 ? 'danger' : 'success'}
				/>
				<div class="mt-3">
					<KeyValue
						items={[
							{ label: 'Available', value: bytes(health.memory.available_bytes) },
							{ label: 'Total', value: bytes(health.memory.total_bytes) },
							{ label: 'The backend process', value: bytes(health.memory.process_rss_bytes) }
						]}
					/>
				</div>
			{/if}
		</Panel>

		<Panel title="Database" description={health!.database.dialect} flush>
			{#snippet actions()}<span class="num text-2xl font-medium text-ink">{bytes(health!.database.total_bytes)}</span>{/snippet}
			{#if health.database.tables.length === 0}
				<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">Sizes for each table need PostgreSQL.</p>
			{:else}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead><tr><th>Table</th><th class="num">Size</th><th class="num">Rows, about</th></tr></thead>
						<tbody>
							{#each health.database.tables as t (t.name)}
								<tr>
									<td class="font-mono">{t.name}</td>
									<td class="num whitespace-nowrap">{bytes(t.bytes)}</td>
									<td class="num text-ink-muted">{num(t.rows)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Panel>
	{/if}
</div>
