<script lang="ts">
	import { sentence } from '$lib/text';
	import { page } from '$app/state';
	import { api, type MachinePieceRecord } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Shapes from '@lucide/svelte/icons/shapes';

	const PAGE_SIZE = 60;

	const machineId = $derived(page.params.machine_id ?? '');

	let machineName = $state<string>('');
	let pieces = $state<MachinePieceRecord[]>([]);
	let total = $state(0);
	let nextCursor = $state<number | null>(null);
	let loading = $state(true);
	let loadingMore = $state(false);
	let error = $state<string | null>(null);
	let sentinel = $state<HTMLDivElement | null>(null);

	$effect(() => {
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
		return c != null ? `${Math.round(c * 100)}%` : '-';
	}

	function when(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString();
	}

	function binLabel(bin: { x: number | null; y: number | null; z: number | null }): string | null {
		if (bin.x == null && bin.y == null && bin.z == null) return null;
		return `${bin.x ?? '-'}, ${bin.y ?? '-'}, ${bin.z ?? '-'}`;
	}
</script>

<svelte:head>
	<title>{machineName ? `${machineName} pieces` : 'Machine pieces'} - Hive</title>
</svelte:head>

<div>
	<Button href={`/machines/${machineId}`} size="sm" variant="ghost" icon={ArrowLeft}>Machine overview</Button>
</div>

<PageHeader title={machineName || 'Machine'} description="Pieces synced from this machine.">
	{#snippet actions()}
		{#if !loading}
			<span class="num text-sm text-ink-muted"
				>{pieces.length.toLocaleString()} of {total.toLocaleString()} loaded</span
			>
		{/if}
	{/snippet}
</PageHeader>

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}

{#if loading}
	<div class="flex justify-center py-12"><Spinner size={32} /></div>
{:else if pieces.length === 0}
	<Panel>
		<EmptyState icon={Shapes} title="No pieces yet">No pieces have synced from this machine yet.</EmptyState>
	</Panel>
{:else}
	<Panel flush>
		<ul class="divide-y divide-line">
			{#each pieces as piece (piece.piece_uuid)}
				{@const bin = binLabel(piece.bin)}
				<li class="flex flex-col gap-4 px-(--pad-panel) py-3 sm:flex-row">
					<!-- The machine's crops. The cap only applies once there is a column beside it. -->
					<div class="flex flex-wrap items-start gap-2 sm:max-w-60 sm:shrink-0">
						{#if piece.images.length === 0}
							<div
								class="flex size-16 items-center justify-center rounded-control bg-well text-xs text-ink-muted"
							>
								No images
							</div>
						{:else}
							{#each piece.images as img (img.seq)}
								{#if img.available}
									<img
										src={api.machinePieceImageUrl(machineId, piece.piece_uuid, img.seq)}
										alt={`Crop ${img.seq}`}
										loading="lazy"
										title={`Crop ${img.seq}${img.source ? `, ${img.source}` : ''}${img.score != null ? `, score ${(img.score * 100).toFixed(0)}%` : ''}${img.used ? ', used' : img.excluded_from_result ? ', left out' : ''}`}
										class="size-16 rounded-control bg-media object-cover {img.used
											? 'outline-2 outline-offset-1 outline-success'
											: img.excluded_from_result
												? 'outline-2 outline-offset-1 outline-danger'
												: ''}"
									/>
								{:else}
									<div
										class="flex size-16 items-center justify-center rounded-control bg-well text-center text-xs text-ink-muted"
										title={`Crop ${img.seq} was removed before it synced`}
									>
										Removed
									</div>
								{/if}
							{/each}
						{/if}
					</div>

					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<Badge tone={statusVariant(piece.classification_status)}
								>{sentence(piece.classification_status ?? 'unknown')}</Badge
							>
							<span class="font-medium text-ink">{piece.part_name || piece.part_id || 'Unidentified'}</span>
							{#if piece.part_id}
								<span class="font-mono text-sm text-ink-muted">{piece.part_id}</span>
							{/if}
							{#if piece.dead}<Badge tone="danger">Dead</Badge>{/if}
						</div>
						<!-- Mold and color are scored by separate providers, so each has its own confidence. -->
						<div class="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-muted">
							<span>Color <span class="text-ink">{piece.color_name || piece.color_id || '-'}</span></span>
							<span>Mold confidence <span class="num text-ink">{conf(piece.confidence)}</span></span>
							<span>Color confidence <span class="num text-ink">{conf(piece.color_confidence)}</span></span>
							{#if bin}<span>Bin <span class="num text-ink">{bin}</span></span>{/if}
							{#if piece.run_id}
								<span class="min-w-0 truncate">Run <span class="font-mono text-ink">{piece.run_id}</span></span>
							{/if}
						</div>
						<div class="mt-1 text-sm text-ink-muted">
							Seen {when(piece.seen_at)}{#if piece.recorded_at}, recorded {when(piece.recorded_at)}{/if}
						</div>
					</div>

					{#if piece.brickognize_preview_url}
						<img
							src={piece.brickognize_preview_url}
							alt="Brickognize reference"
							loading="lazy"
							title="Brickognize reference"
							class="size-16 shrink-0 rounded-control bg-surface object-contain"
						/>
					{/if}
				</li>
			{/each}
		</ul>
	</Panel>

	<div bind:this={sentinel} class="h-px"></div>

	<div class="flex justify-center py-6">
		{#if loadingMore}
			<Spinner size={24} />
		{:else if nextCursor != null}
			<Button size="sm" onclick={loadMore}>Load more</Button>
		{:else}
			<span class="text-sm text-ink-muted">End of the list, {total.toLocaleString()} pieces.</span>
		{/if}
	</div>
{/if}
