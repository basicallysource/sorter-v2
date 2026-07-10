<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { auth } from '$lib/auth.svelte';
	import { api, type MachinePieceRecord } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	const PAGE_SIZE = 60;

	const machineId = $derived(page.params.id ?? '');

	let machineName = $state<string>('');
	let pieces = $state<MachinePieceRecord[]>([]);
	let total = $state(0);
	let nextCursor = $state<number | null>(null);
	let loading = $state(true);
	let loadingMore = $state(false);
	let error = $state<string | null>(null);
	let sentinel = $state<HTMLDivElement | null>(null);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		// Re-run the initial load whenever the route id changes.
		void machineId;
		void loadInitial();
	});

	// Auto-load the next page when the sentinel scrolls into view, so the list
	// behaves like the on-machine /records page (scroll, don't click).
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
		pieces = [];
		nextCursor = null;
		try {
			const res = await api.getMachinePieces(machineId, { limit: PAGE_SIZE });
			machineName = res.machine.name;
			pieces = res.items;
			total = res.total;
			nextCursor = res.next_cursor;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load pieces');
		} finally {
			loading = false;
		}
	}

	async function loadMore() {
		if (loadingMore || loading || nextCursor == null) return;
		loadingMore = true;
		try {
			const res = await api.getMachinePieces(machineId, {
				limit: PAGE_SIZE,
				cursor: nextCursor
			});
			pieces = [...pieces, ...res.items];
			nextCursor = res.next_cursor;
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load more pieces');
		} finally {
			loadingMore = false;
		}
	}

	function errMsg(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: fallback;
	}

	function statusVariant(status: string | null): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
		switch (status) {
			case 'classified':
				return 'success';
			case 'failed':
			case 'not_found':
			case 'multi_drop_fail':
				return 'danger';
			case 'unknown':
				return 'warning';
			case 'pending':
			case 'classifying':
				return 'info';
			default:
				return 'neutral';
		}
	}

	function conf(c: number | null): string {
		return c != null ? `${Math.round(c * 100)}%` : '—';
	}

	function when(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleString();
	}

	function binLabel(bin: { x: number | null; y: number | null; z: number | null }): string | null {
		if (bin.x == null && bin.y == null && bin.z == null) return null;
		return `${bin.x ?? '·'}, ${bin.y ?? '·'}, ${bin.z ?? '·'}`;
	}
</script>

<svelte:head>
	<title>{machineName ? `${machineName} — Pieces` : 'Machine Pieces'} - Hive</title>
</svelte:head>

<div class="mb-4">
	<a href="/admin/machines" class="text-sm text-text-muted hover:text-text">← All machines</a>
</div>

<div class="mb-6 flex items-end justify-between">
	<div>
		<h1 class="text-2xl font-bold text-text">{machineName || 'Machine'}</h1>
		<p class="text-sm text-text-muted">Pieces synced from this machine</p>
	</div>
	{#if !loading}
		<span class="text-sm text-text-muted">
			{pieces.length.toLocaleString()} of {total.toLocaleString()} loaded
		</span>
	{/if}
</div>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12">
		<Spinner />
	</div>
{:else if pieces.length === 0}
	<div class="border border-border bg-surface p-8 text-center text-sm text-text-muted">
		No pieces synced from this machine yet.
	</div>
{:else}
	<div class="flex flex-col gap-2">
		{#each pieces as piece (piece.piece_uuid)}
			{@const bin = binLabel(piece.bin)}
			<div class="flex gap-4 border border-border bg-surface p-3">
				<!-- Left: crops from the machine -->
				<div class="flex shrink-0 flex-wrap items-start gap-1.5" style="max-width: 15rem">
					{#if piece.images.length === 0}
						<div class="flex h-16 w-16 items-center justify-center border border-border bg-bg text-[10px] text-text-muted">
							no images
						</div>
					{:else}
						{#each piece.images as img (img.seq)}
							{#if img.available}
								<img
									src={api.machinePieceImageUrl(machineId, piece.piece_uuid, img.seq)}
									alt={`crop ${img.seq}`}
									loading="lazy"
									title={`seq ${img.seq}${img.source ? ` · ${img.source}` : ''}${img.score != null ? ` · score ${(img.score * 100).toFixed(0)}%` : ''}`}
									class="h-16 w-16 border-2 object-cover {img.used
										? 'border-success'
										: img.excluded_from_result
											? 'border-primary'
											: 'border-border'}"
								/>
							{:else}
								<div
									class="flex h-16 w-16 items-center justify-center border border-dashed border-border bg-bg text-center text-[9px] text-text-muted"
									title={`seq ${img.seq} · evicted before sync`}
								>
									evicted
								</div>
							{/if}
						{/each}
					{/if}
				</div>

				<!-- Middle: classification -->
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-2">
						<Badge text={piece.classification_status ?? 'unknown'} variant={statusVariant(piece.classification_status)} />
						<span class="text-sm font-medium text-text">
							{piece.part_name || piece.part_id || 'Unidentified'}
						</span>
						{#if piece.part_id}
							<span class="text-xs text-text-muted">#{piece.part_id}</span>
						{/if}
						{#if piece.dead}
							<Badge text="dead" variant="danger" />
						{/if}
					</div>

					<div class="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
						<span>Color: <span class="text-text">{piece.color_name || piece.color_id || '—'}</span></span>
						<span>Conf: <span class="text-text tabular-nums">{conf(piece.confidence)}</span></span>
						{#if bin}
							<span>Bin: <span class="text-text tabular-nums">{bin}</span></span>
						{/if}
						{#if piece.run_id}
							<span class="truncate">Run: <span class="text-text">{piece.run_id}</span></span>
						{/if}
					</div>

					<div class="mt-1 text-xs text-text-muted">
						Seen {when(piece.seen_at)}
						{#if piece.recorded_at} · Recorded {when(piece.recorded_at)}{/if}
					</div>
				</div>

				<!-- Right: Brickognize reference -->
				{#if piece.brickognize_preview_url}
					<div class="shrink-0">
						<img
							src={piece.brickognize_preview_url}
							alt="reference"
							loading="lazy"
							title="Brickognize reference"
							class="h-16 w-16 border border-border object-contain"
						/>
					</div>
				{/if}
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
			<span class="text-xs text-text-muted">End of list · {total.toLocaleString()} pieces total</span>
		{/if}
	</div>
{/if}
