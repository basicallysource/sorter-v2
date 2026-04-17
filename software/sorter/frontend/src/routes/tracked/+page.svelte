<script lang="ts">
	import { onMount } from 'svelte';
	import { RefreshCw } from 'lucide-svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { getMachineContext } from '$lib/machines/context';
	import TrackedPieceDetailModal from '$lib/components/TrackedPieceDetailModal.svelte';

	type HistoryItem = {
		global_id: number;
		created_at: number;
		finished_at: number;
		duration_s: number;
		roles: string[];
		handoff_count: number;
		segment_count: number;
		total_hit_count: number;
		live: boolean;
		composite_jpeg_b64?: string;
		max_sector_snapshots?: number;
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	let items = $state<HistoryItem[]>([]);
	let selectedId = $state<number | null>(null);
	let minSectors = $state(3);
	let limit = $state(120);
	let loading = $state(false);

	async function load() {
		loading = true;
		try {
			const res = await fetch(
				`${effectiveBase()}/api/feeder/tracking/history?limit=${limit}&min_sectors=${minSectors}`
			);
			if (!res.ok) return;
			const json = await res.json();
			items = Array.isArray(json?.items) ? json.items : [];
		} catch {
			// ignore
		} finally {
			loading = false;
		}
	}

	function formatHashId(id: number): string {
		const mixed = (id * 2654435761) >>> 0;
		return (mixed % 10000).toString().padStart(4, '0');
	}

	function formatDuration(seconds: number): string {
		if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const m = Math.floor(seconds / 60);
		return `${m}m ${Math.floor(seconds % 60)}s`;
	}

	function formatRoles(roles: string[]): string {
		return roles.map((r) => r.replace('c_channel_', 'C')).join(' → ');
	}

	onMount(() => {
		void load();
	});

	// Filter changes trigger an explicit fetch — no $effect, because
	// capturing reactive context reads (e.g. ctx.machine.url heartbeats)
	// would silently re-trigger the load on every websocket event.
	function onFilterChange() {
		void load();
	}
</script>

<svelte:head>
	<title>Tracked Pieces · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="flex flex-col gap-4 p-4 sm:p-6">
		<header class="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
			<div>
				<h2 class="text-xl font-bold text-text">Tracked Pieces</h2>
				<p class="mt-1 text-sm text-text-muted">
					Each card is a piece the tracker followed across the feeder ring. Click to open the full trajectory.
				</p>
			</div>
		<div class="flex flex-wrap items-center gap-4 text-xs text-text-muted">
			<label class="flex items-center gap-2">
				<span>min sectors</span>
				<input
					type="number"
					min="0"
					max="12"
					bind:value={minSectors}
					onchange={onFilterChange}
					class="w-16 border border-border bg-bg px-2 py-1 text-text"
				/>
			</label>
			<label class="flex items-center gap-2">
				<span>limit</span>
				<input
					type="number"
					min="10"
					max="300"
					step="10"
					bind:value={limit}
					onchange={onFilterChange}
					class="w-20 border border-border bg-bg px-2 py-1 text-text"
				/>
			</label>
			<span class="text-text-muted">{items.length} shown</span>
			<button
				type="button"
				onclick={() => void load()}
				disabled={loading}
				aria-label="Reload"
				title="Reload tracked pieces"
				class="border border-border bg-surface p-1.5 text-text-muted hover:text-text disabled:opacity-50"
			>
				<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
			</button>
		</div>
	</header>

	{#if items.length === 0}
		<div class="flex min-h-40 items-center justify-center border border-dashed border-border bg-surface text-sm text-text-muted">
			No pieces tracked yet.
		</div>
	{:else}
		<div class="grid gap-4" style="grid-template-columns: repeat(auto-fill, minmax(660px, 1fr));">
			{#each items as item (item.global_id)}
				<button
					type="button"
					onclick={() => (selectedId = item.global_id)}
					class="group flex flex-col border border-border bg-surface text-left transition-colors hover:border-primary/70"
				>
					<div class="relative aspect-square w-full bg-black">
						{#if item.composite_jpeg_b64}
							<img
								src={`data:image/jpeg;base64,${item.composite_jpeg_b64}`}
								alt=""
								class="block h-full w-full object-cover"
							/>
						{:else}
							<div class="flex h-full w-full items-center justify-center text-sm text-text-muted">
								{item.live ? '…' : '—'}
							</div>
						{/if}
						<span
							class={`absolute top-2 left-2 inline-flex h-2 w-2 rounded-full ${
								item.live ? 'bg-success' : 'bg-text-muted/70'
							}`}
							aria-hidden="true"
						></span>
						{#if item.handoff_count > 0}
							<span class="absolute top-2 right-2 border border-primary bg-bg/80 px-1.5 py-0.5 text-xs font-medium text-primary">
								handoff
							</span>
						{/if}
						{#if item.live}
							<span class="absolute bottom-2 left-2 border border-success bg-bg/80 px-1.5 py-0.5 text-xs font-medium text-success">
								LIVE
							</span>
						{/if}
					</div>
					<div class="flex flex-col gap-0.5 px-3 py-2 text-xs text-text">
						<div class="flex items-center justify-between">
							<span class="font-mono text-sm font-semibold">#{formatHashId(item.global_id)}</span>
							<span class="text-text-muted">{formatDuration(item.duration_s)}</span>
						</div>
						<div class="flex items-center justify-between text-text-muted">
							<span>{formatRoles(item.roles)}</span>
							{#if item.max_sector_snapshots != null}
								<span>{item.max_sector_snapshots} sec.</span>
							{/if}
						</div>
					</div>
				</button>
			{/each}
		</div>
	{/if}
	</div>
</div>

{#if selectedId !== null}
	<TrackedPieceDetailModal
		globalId={selectedId}
		onClose={() => (selectedId = null)}
	/>
{/if}
