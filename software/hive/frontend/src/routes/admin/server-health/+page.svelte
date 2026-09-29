<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth.svelte';
	import { api, type ServerHealth } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
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
		if (n == null) return '—';
		if (n === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
		return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
	}

	function num(n: number | null | undefined): string {
		return n != null ? Math.round(n).toLocaleString() : '—';
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
	<title>Server Health · Hive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<div>
		<h1 class="text-2xl font-bold text-ink">Server Health</h1>
		<p class="text-sm text-ink-muted">Image storage, database size, and memory usage.</p>
	</div>
	<Button variant="secondary" size="sm" loading={refreshing} onclick={() => load(true)}>Refresh storage</Button>
</div>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary-ink">{error}</div>
{/if}

{#if refreshQueued}
	<div class="mb-4 bg-info/8 p-3 text-sm text-info-ink">
		Storage refresh queued — a background walk of the object store is running. Reload in a few
		minutes to see the updated figures.
	</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12"><Spinner size={32} /></div>
{:else if health}
	<!-- Storage -->
	<section class="border border-line bg-surface p-5">
		<div class="flex items-baseline justify-between">
			<h2 class="text-lg font-semibold text-ink">Image & file storage</h2>
			<span class="text-2xl font-bold text-ink tabular-nums">{bytes(storageTotal)}</span>
		</div>
		<p class="mt-0.5 text-xs text-ink-muted">
			{num(health.storage.total_files)} files · as of {storageAsOf()}{health.storage.pending
				? ' · first walk in progress'
				: ''}
		</p>

		<!-- Stacked proportion bar -->
		{#if storageTotal > 0}
			<div class="mt-4 flex h-3 w-full overflow-hidden bg-border">
				{#each storageParts as part (part.key)}
					{#if part.bytes > 0}
						<div style="width: {(part.bytes / storageTotal) * 100}%; background: {part.color}"></div>
					{/if}
				{/each}
			</div>
		{/if}

		<div class="mt-4 grid grid-cols-1 gap-px border border-line bg-border sm:grid-cols-3">
			{#each storageParts as part (part.key)}
				<div class="bg-surface p-4">
					<div class="flex items-center gap-2">
						<span class="inline-block h-2.5 w-2.5" style="background: {part.color}"></span>
						<span class="text-sm font-medium text-ink">{part.label}</span>
					</div>
					<p class="mt-1 text-xl font-bold text-ink tabular-nums">{bytes(part.bytes)}</p>
					<p class="text-xs text-ink-muted">{num(part.files)} files</p>
				</div>
			{/each}
		</div>
	</section>

	<!-- Memory -->
	<section class="mt-6 border border-line bg-surface p-5">
		<h2 class="text-lg font-semibold text-ink">Memory</h2>
		{#if health.memory.total_bytes == null}
			<p class="mt-2 text-sm text-ink-muted">
				Memory stats unavailable (host is not Linux / <code>/proc</code> not accessible).
			</p>
		{:else}
			<div class="mt-2 flex items-baseline justify-between text-sm">
				<span class="text-ink-muted">Used</span>
				<span class="text-ink tabular-nums">
					{bytes(health.memory.used_bytes)} / {bytes(health.memory.total_bytes)}
					{#if memUsedPct != null}<span class="text-ink-muted"> ({memUsedPct}%)</span>{/if}
				</span>
			</div>
			<div class="mt-2 h-3 w-full bg-border">
				<div
					class="h-full {memUsedPct != null && memUsedPct >= 90 ? 'bg-primary' : 'bg-success'}"
					style="width: {memUsedPct ?? 0}%"
				></div>
			</div>
			<dl class="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
				<div>
					<dt class="text-ink-muted">Available</dt>
					<dd class="text-ink tabular-nums">{bytes(health.memory.available_bytes)}</dd>
				</div>
				<div>
					<dt class="text-ink-muted">Total</dt>
					<dd class="text-ink tabular-nums">{bytes(health.memory.total_bytes)}</dd>
				</div>
				<div>
					<dt class="text-ink-muted">Backend process (RSS)</dt>
					<dd class="text-ink tabular-nums">{bytes(health.memory.process_rss_bytes)}</dd>
				</div>
			</dl>
		{/if}
	</section>

	<!-- Database -->
	<section class="mt-6 border border-line bg-surface p-5">
		<div class="flex items-baseline justify-between">
			<h2 class="text-lg font-semibold text-ink">Database</h2>
			<span class="text-2xl font-bold text-ink tabular-nums">{bytes(health.database.total_bytes)}</span>
		</div>
		<p class="mt-0.5 text-xs text-ink-muted">{health.database.dialect}</p>

		{#if health.database.tables.length === 0}
			<p class="mt-3 text-sm text-ink-muted">Per-table sizes are only available on PostgreSQL.</p>
		{:else}
			<div class="mt-4 overflow-x-auto border border-line">
				<table class="min-w-full divide-y divide-line">
					<thead class="bg-well">
						<tr>
							<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Table</th>
							<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Size</th>
							<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Rows (est.)</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-line">
						{#each health.database.tables as t (t.name)}
							<tr class="hover:bg-hover">
								<td class="whitespace-nowrap px-4 py-2 font-mono text-sm text-ink">{t.name}</td>
								<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink tabular-nums">{bytes(t.bytes)}</td>
								<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink-muted tabular-nums">{num(t.rows)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
{/if}
