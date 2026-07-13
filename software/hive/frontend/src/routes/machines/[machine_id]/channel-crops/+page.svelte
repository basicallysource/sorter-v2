<script lang="ts">
	import { page } from '$app/state';
	import { api, type MachineChannelCropInfo } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	const PAGE_SIZE = 120;

	const machineId = $derived(page.params.machine_id ?? '');

	let machineName = $state<string>('');
	let crops = $state<MachineChannelCropInfo[]>([]);
	let total = $state(0);
	let nextCursor = $state<number | null>(null);
	let loading = $state(true);
	let loadingMore = $state(false);
	let error = $state<string | null>(null);
	let sentinel = $state<HTMLDivElement | null>(null);

	// Filters. null = all.
	let channel = $state<number | null>(null);
	let zoneCode = $state<number | null>(null);

	$effect(() => {
		// Re-run the initial load whenever route id or a filter changes.
		void machineId;
		void channel;
		void zoneCode;
		void loadInitial();
	});

	$effect(() => {
		const el = sentinel;
		if (!el) return;
		const observer = new IntersectionObserver((entries) => {
			if (entries.some((e) => e.isIntersecting)) void loadMore();
		});
		observer.observe(el);
		return () => observer.disconnect();
	});

	async function loadInitial() {
		if (!machineId) return;
		loading = true;
		error = null;
		crops = [];
		nextCursor = null;
		try {
			const res = await api.getMachineChannelCrops(machineId, {
				limit: PAGE_SIZE,
				channel,
				zoneCode
			});
			machineName = res.machine.name;
			crops = res.items;
			total = res.total;
			nextCursor = res.next_cursor;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load channel crops');
		} finally {
			loading = false;
		}
	}

	async function loadMore() {
		if (loadingMore || loading || nextCursor == null) return;
		loadingMore = true;
		try {
			const res = await api.getMachineChannelCrops(machineId, {
				limit: PAGE_SIZE,
				cursor: nextCursor,
				channel,
				zoneCode
			});
			crops = [...crops, ...res.items];
			nextCursor = res.next_cursor;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load more crops');
		} finally {
			loadingMore = false;
		}
	}

	function errMsg(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: fallback;
	}

	const ZONE_LABELS: Record<number, string> = { 0: 'mid', 1: 'drop', 2: 'exit', 3: 'precise' };

	function zoneLabel(z: number | null): string {
		return z == null ? '—' : (ZONE_LABELS[z] ?? String(z));
	}

	// Border color encodes the zone the piece's COM sat in — dense near the exit
	// is where the same-piece heuristic cares most, so make exit/precise pop.
	function zoneBorder(z: number | null): string {
		switch (z) {
			case 3:
				return 'border-success';
			case 2:
				return 'border-primary';
			case 1:
				return 'border-info';
			default:
				return 'border-border';
		}
	}

	function deg(d: number | null): string {
		return d == null ? '—' : `${d.toFixed(1)}°`;
	}

	function when(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleTimeString();
	}

	const CHANNEL_FILTERS = [
		{ label: 'All channels', value: null },
		{ label: 'C2', value: 2 },
		{ label: 'C3', value: 3 }
	];
	const ZONE_FILTERS = [
		{ label: 'All zones', value: null },
		{ label: 'Exit', value: 2 },
		{ label: 'Precise', value: 3 },
		{ label: 'Drop', value: 1 },
		{ label: 'Mid', value: 0 }
	];
</script>

<svelte:head>
	<title>{machineName ? `${machineName} — Channel crops` : 'Channel crops'} · Hive</title>
</svelte:head>

<div class="mb-4">
	<a href={`/machines/${machineId}`} class="text-sm text-text-muted hover:text-text">← Machine overview</a>
</div>

<div class="mb-4 flex items-end justify-between">
	<div>
		<h1 class="text-2xl font-bold text-text">{machineName || 'Machine'}</h1>
		<p class="text-sm text-text-muted">
			Unlabeled C2/C3 bbox crops synced from this machine — tagged with the piece's
			distance to the exit zone, for same-piece lookup.
		</p>
	</div>
	{#if !loading}
		<span class="shrink-0 text-sm text-text-muted">
			{crops.length.toLocaleString()} of {total.toLocaleString()} loaded
		</span>
	{/if}
</div>

<div class="mb-5 flex flex-wrap items-center gap-2">
	<div class="flex flex-wrap gap-1">
		{#each CHANNEL_FILTERS as f (f.label)}
			<Button
				variant={channel === f.value ? 'primary' : 'secondary'}
				size="sm"
				onclick={() => (channel = f.value)}>{f.label}</Button
			>
		{/each}
	</div>
	<div class="flex flex-wrap gap-1">
		{#each ZONE_FILTERS as f (f.label)}
			<Button
				variant={zoneCode === f.value ? 'primary' : 'secondary'}
				size="sm"
				onclick={() => (zoneCode = f.value)}>{f.label}</Button
			>
		{/each}
	</div>
</div>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12">
		<Spinner />
	</div>
{:else if crops.length === 0}
	<div class="border border-border bg-surface p-8 text-center text-sm text-text-muted">
		No channel crops synced from this machine yet.
	</div>
{:else}
	<div class="flex flex-wrap gap-2">
		{#each crops as crop (crop.local_id)}
			<div class="flex w-24 flex-col border border-border bg-surface p-1">
				{#if crop.available}
					<img
						src={api.machineChannelCropImageUrl(machineId, crop.local_id)}
						alt={`crop ${crop.local_id}`}
						loading="lazy"
						title={`C${crop.channel} · ${zoneLabel(crop.zone_code)} · ${deg(
							crop.com_forward_to_exit_deg
						)} to exit · track ${crop.track_id ?? '—'} · ${when(crop.ts)}`}
						class="h-20 w-full border-2 object-contain {zoneBorder(crop.zone_code)}"
					/>
				{:else}
					<div
						class="flex h-20 w-full items-center justify-center border border-dashed border-border bg-bg text-center text-[9px] text-text-muted"
						title="evicted before sync"
					>
						evicted
					</div>
				{/if}
				<div class="mt-1 text-center text-[10px] leading-tight text-text-muted">
					<div class="text-text">C{crop.channel} · {zoneLabel(crop.zone_code)}</div>
					<div class="tabular-nums">{deg(crop.com_forward_to_exit_deg)}</div>
				</div>
			</div>
		{/each}
	</div>

	<div bind:this={sentinel} class="h-px"></div>

	<div class="flex justify-center py-6">
		{#if loadingMore}
			<Spinner />
		{:else if nextCursor != null}
			<Button variant="secondary" size="sm" onclick={loadMore}>Load more</Button>
		{:else}
			<span class="text-xs text-text-muted">End of list · {total.toLocaleString()} crops total</span>
		{/if}
	</div>
{/if}
