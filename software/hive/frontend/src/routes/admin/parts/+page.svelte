<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import {
		api,
		type PartsDbOverview,
		type PartsDbPart,
		type PartsDbPartDetail,
		type PartsDbCategory
	} from '$lib/api';
	import { goto } from '$app/navigation';
	import Badge from '$lib/components/Badge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	let overview = $state<PartsDbOverview | null>(null);
	let categories = $state<PartsDbCategory[]>([]);

	let parts = $state<PartsDbPart[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Filters
	let query = $state('');
	let catId = $state<number | null>(null);
	let missing = $state('');
	const PAGE_SIZE = 100;
	let offset = $state(0);

	// Detail modal
	let detail = $state<PartsDbPartDetail | null>(null);
	let detailLoading = $state(false);
	let detailOpen = $state(false);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		init();
	});

	async function init() {
		try {
			const [ov, cats] = await Promise.all([
				api.getPartsDbOverview(),
				api.listPartsDbCategories()
			]);
			overview = ov;
			categories = cats.results;
		} catch (e: any) {
			error = e.error || 'Failed to load catalog overview';
		}
		await loadParts();
	}

	async function loadParts() {
		loading = true;
		error = null;
		try {
			const page = await api.listPartsDbParts({
				q: query || undefined,
				cat_id: catId ?? undefined,
				missing: missing || undefined,
				limit: PAGE_SIZE,
				offset
			});
			parts = page.results;
			total = page.total;
		} catch (e: any) {
			error = e.error || 'Failed to load parts';
		} finally {
			loading = false;
		}
	}

	function applyFilters() {
		offset = 0;
		loadParts();
	}

	function nextPage() {
		if (offset + PAGE_SIZE < total) {
			offset += PAGE_SIZE;
			loadParts();
		}
	}

	function prevPage() {
		if (offset > 0) {
			offset = Math.max(0, offset - PAGE_SIZE);
			loadParts();
		}
	}

	async function openDetail(partNum: string) {
		detailOpen = true;
		detailLoading = true;
		detail = null;
		try {
			detail = await api.getPartsDbPart(partNum);
		} catch (e: any) {
			error = e.error || 'Failed to load part detail';
			detailOpen = false;
		} finally {
			detailLoading = false;
		}
	}

	function fmt(n: number | null | undefined): string {
		if (n === null || n === undefined) return '—';
		return n.toLocaleString();
	}

	function money(n: number | null | undefined): string {
		if (n === null || n === undefined) return '—';
		return `$${n.toFixed(2)}`;
	}

	function yearRange(from: number | null, to: number | null): string {
		if (!from && !to) return '—';
		if (from && to && from !== to) return `${from}–${to}`;
		return String(from || to);
	}

	const pageStart = $derived(total === 0 ? 0 : offset + 1);
	const pageEnd = $derived(Math.min(offset + PAGE_SIZE, total));

	const coverageCards = $derived(
		overview
			? [
					{ label: 'Parts', value: overview.coverage.parts_total, tone: 'neutral' as const },
					{
						label: 'With BrickLink ID',
						value: overview.coverage.parts_with_bricklink_id,
						tone: overview.coverage.parts_with_bricklink_id > 0 ? ('ok' as const) : ('bad' as const)
					},
					{
						label: 'With BrickLink item',
						value: overview.coverage.parts_with_bricklink_item,
						tone: overview.coverage.parts_with_bricklink_item > 0 ? ('ok' as const) : ('bad' as const)
					},
					{
						label: 'With price guide',
						value: overview.coverage.parts_with_price_guide,
						tone: overview.coverage.parts_with_price_guide > 0 ? ('ok' as const) : ('bad' as const)
					},
					{
						label: 'BL IDs w/o item record',
						value: overview.coverage.bricklink_ids_without_item,
						tone: overview.coverage.bricklink_ids_without_item > 0 ? ('bad' as const) : ('ok' as const)
					},
					{
						label: 'Items with dimensions',
						value: overview.coverage.bricklink_items_with_dims,
						tone: overview.coverage.bricklink_items_with_dims > 0 ? ('ok' as const) : ('neutral' as const)
					},
					{
						label: 'Per-color price rows',
						value: overview.coverage.price_color_rows_mapped_to_rb,
						tone: overview.coverage.price_color_rows_mapped_to_rb > 0 ? ('ok' as const) : ('neutral' as const)
					}
				]
			: []
	);
</script>

<svelte:head>
	<title>Parts Database — Hive</title>
</svelte:head>

<div class="mb-6 flex items-end justify-between">
	<div>
		<h1 class="text-2xl font-bold text-text">Parts Database</h1>
		<p class="mt-1 text-sm text-text-muted">
			Browse and verify the catalog extracted from Rebrickable, BrickStore/BrickLink, and price guides.
		</p>
	</div>
</div>

{#if error}
	<div class="mb-4 border border-primary/30 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

<!-- Overview / coverage -->
{#if overview}
	<div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
		{#each coverageCards as card}
			<div
				class="border bg-surface p-3 {card.tone === 'bad'
					? 'border-primary/40'
					: card.tone === 'ok'
						? 'border-success/40'
						: 'border-border'}"
			>
				<div class="text-xs uppercase tracking-wider text-text-muted">{card.label}</div>
				<div
					class="mt-1 text-xl font-bold {card.tone === 'bad'
						? 'text-primary'
						: card.tone === 'ok'
							? 'text-success'
							: 'text-text'}"
				>
					{fmt(card.value)}
				</div>
			</div>
		{/each}
	</div>

	<div class="mb-6 flex flex-wrap gap-x-4 gap-y-1 border border-border bg-bg p-3 text-xs text-text-muted">
		{#each Object.entries(overview.tables) as [name, count]}
			<span><span class="font-mono text-text">{fmt(count)}</span> {name}</span>
		{/each}
	</div>
{/if}

<!-- Filters -->
<div class="mb-4 flex flex-wrap items-center gap-2">
	<input
		type="text"
		bind:value={query}
		onkeydown={(e) => e.key === 'Enter' && applyFilters()}
		placeholder="Search part #, name, or BrickLink ID…"
		class="min-w-64 flex-1 border border-border bg-surface px-3 py-2 text-sm text-text"
	/>
	<select
		bind:value={catId}
		class="border border-border bg-surface px-3 py-2 text-sm text-text"
	>
		<option value={null}>All categories</option>
		{#each categories as cat}
			<option value={cat.id}>{cat.name} ({fmt(cat.actual_part_count)})</option>
		{/each}
	</select>
	<select
		bind:value={missing}
		class="border border-border bg-surface px-3 py-2 text-sm text-text"
	>
		<option value="">Any connection</option>
		<option value="bricklink_id">Missing BrickLink ID</option>
		<option value="bricklink_item">Missing BrickLink item</option>
	</select>
	<Button variant="primary" size="md" onclick={applyFilters}>Search</Button>
</div>

<!-- Results -->
{#if loading}
	<div class="flex justify-center py-12"><Spinner /></div>
{:else}
	<div class="mb-2 flex items-center justify-between text-sm text-text-muted">
		<span>{fmt(total)} parts</span>
		<span>Showing {fmt(pageStart)}–{fmt(pageEnd)}</span>
	</div>

	<div class="overflow-x-auto border border-border bg-surface">
		<table class="min-w-full divide-y divide-border">
			<thead class="bg-bg">
				<tr>
					<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Part</th>
					<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Name</th>
					<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Category</th>
					<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Years</th>
					<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-text-muted">BL IDs</th>
					<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-text-muted">BL items</th>
					<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Prices</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each parts as part (part.part_num)}
					<tr
						class="cursor-pointer hover:bg-bg"
						onclick={() => openDetail(part.part_num)}
					>
						<td class="px-4 py-2">
							<div class="flex items-center gap-2">
								{#if part.part_img_url}
									<img src={part.part_img_url} alt="" class="h-8 w-8 object-contain" loading="lazy" />
								{:else}
									<div class="h-8 w-8 bg-bg"></div>
								{/if}
								<span class="font-mono text-sm text-text">{part.part_num}</span>
							</div>
						</td>
						<td class="px-4 py-2 text-sm text-text">{part.name}</td>
						<td class="px-4 py-2 text-sm text-text-muted">{part._category_name}</td>
						<td class="px-4 py-2 text-sm text-text-muted">{yearRange(part.year_from, part.year_to)}</td>
						<td class="px-4 py-2 text-right text-sm text-text-muted">{part._bl_id_count}</td>
						<td
							class="px-4 py-2 text-right text-sm {part._bl_item_count > 0
								? 'text-success'
								: 'text-primary'}"
						>
							{part._bl_item_count}
						</td>
						<td class="px-4 py-2 text-right text-sm text-text-muted">{part._price_count}</td>
					</tr>
				{:else}
					<tr>
						<td colspan="7" class="px-4 py-8 text-center text-sm text-text-muted">No parts match.</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<div class="mt-4 flex items-center justify-between">
		<Button variant="secondary" size="sm" disabled={offset === 0} onclick={prevPage}>Previous</Button>
		<span class="text-sm text-text-muted">{fmt(pageStart)}–{fmt(pageEnd)} of {fmt(total)}</span>
		<Button variant="secondary" size="sm" disabled={offset + PAGE_SIZE >= total} onclick={nextPage}>Next</Button>
	</div>
{/if}

<!-- Detail modal -->
<Modal open={detailOpen} title={detail ? `${detail.part.part_num} — ${detail.part.name}` : 'Part detail'} onclose={() => (detailOpen = false)}>
	{#if detailLoading}
		<div class="flex justify-center py-8"><Spinner /></div>
	{:else if detail}
		<div class="space-y-4">
			<div class="flex gap-3">
				{#if detail.part.part_img_url}
					<img src={detail.part.part_img_url} alt="" class="h-20 w-20 object-contain border border-border" />
				{/if}
				<dl class="grid flex-1 grid-cols-2 gap-x-3 gap-y-1 text-sm">
					<dt class="text-text-muted">Category</dt>
					<dd class="text-text">{detail.part._category_name}</dd>
					<dt class="text-text-muted">Years</dt>
					<dd class="text-text">{yearRange(detail.part.year_from, detail.part.year_to)}</dd>
					<dt class="text-text-muted">Size (LEGO units)</dt>
					<dd class="text-text">
						{#if detail.part.dim_x_studs != null}
							{detail.part.dim_x_studs} × {detail.part.dim_y_studs} studs
							<span class="text-text-muted">({(detail.part.dim_x_studs * 8).toFixed(0)} × {((detail.part.dim_y_studs ?? 0) * 8).toFixed(0)} mm)</span>
						{:else}—{/if}
					</dd>
					<dt class="text-text-muted">Rebrickable</dt>
					<dd>
						{#if detail.part.part_url}
							<a href={detail.part.part_url} target="_blank" rel="noopener" class="text-info hover:underline">open ↗</a>
						{:else}—{/if}
					</dd>
				</dl>
			</div>

			<!-- External IDs from Rebrickable -->
			<div>
				<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">External IDs (Rebrickable)</h3>
				{#if Object.keys(detail.part.external_ids).length === 0}
					<p class="text-sm text-text-muted">None.</p>
				{:else}
					<div class="space-y-1 text-sm">
						{#each Object.entries(detail.part.external_ids) as [source, ids]}
							<div class="flex gap-2">
								<span class="w-24 shrink-0 text-text-muted">{source}</span>
								<span class="font-mono text-text">{ids.join(', ')}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- BrickLink links -->
			<div>
				<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
					BrickLink items ({detail.bricklink.length})
				</h3>
				{#if detail.bricklink.length === 0}
					<p class="text-sm text-text-muted">No BrickLink mapping.</p>
				{:else}
					<div class="space-y-2">
						{#each detail.bricklink as link}
							<div class="border border-border p-2">
								<div class="flex flex-wrap items-center gap-2">
									<span class="font-mono text-sm text-text">{link.item_no}</span>
									{#if link.is_primary}<Badge text="primary" variant="info" />{/if}
									{#if link.has_item_record}
										<Badge text="item record" variant="success" />
									{:else}
										<Badge text="no item record" variant="danger" />
									{/if}
									{#if link.has_price_guide}<Badge text="price guide" variant="success" />{/if}
									{#if link.is_obsolete}<Badge text="obsolete" variant="warning" />{/if}
								</div>
								{#if link.has_item_record}
									<div class="mt-1 text-xs text-text-muted">
										{link.bl_name ?? '—'}
										{#if link.bl_category_name} · {link.bl_category_name}{/if}
										{#if link.weight != null} · {link.weight} g{/if}
										{#if link.year_released} · {link.year_released}{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Per-color prices -->
			<div>
				<h3 class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
					Prices by color ({detail.prices.length})
				</h3>
				{#if detail.prices.length === 0}
					<p class="text-sm text-text-muted">No price data yet — run the price sync.</p>
				{:else}
					<div class="max-h-64 overflow-y-auto border border-border">
						<table class="min-w-full divide-y divide-border text-sm">
							<thead class="sticky top-0 bg-bg">
								<tr>
									<th class="px-3 py-1.5 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Color</th>
									<th class="px-3 py-1.5 text-right text-xs font-medium uppercase tracking-wider text-text-muted">New avg</th>
									<th class="px-3 py-1.5 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Used avg</th>
									<th class="px-3 py-1.5 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Used qty</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-border">
								{#each detail.prices as p}
									<tr>
										<td class="px-3 py-1.5 text-text">
											{p.color_name ?? `BL ${p.bl_color_id}`}
											{#if p.rb_color_id == null}<span class="text-xs text-text-muted"> (BL-only)</span>{/if}
										</td>
										<td class="px-3 py-1.5 text-right text-text">{money(p.new_avg)}</td>
										<td class="px-3 py-1.5 text-right text-text">{money(p.used_avg)}</td>
										<td class="px-3 py-1.5 text-right text-text-muted">{p.used_qty ?? '—'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</Modal>
