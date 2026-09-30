<script lang="ts">
	import { sentence } from '$lib/text';
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
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Input from '$lib/components/Input.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Search from '@lucide/svelte/icons/search';

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
		if (n === null || n === undefined) return '-';
		return n.toLocaleString();
	}

	function money(n: number | null | undefined): string {
		if (n === null || n === undefined) return '-';
		return `$${n.toFixed(2)}`;
	}

	function yearRange(from: number | null, to: number | null): string {
		if (!from && !to) return '-';
		if (from && to && from !== to) return `${from} to ${to}`;
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
						label: 'IDs with no item',
						value: overview.coverage.bricklink_ids_without_item,
						tone: overview.coverage.bricklink_ids_without_item > 0 ? ('bad' as const) : ('ok' as const)
					},
					{
						label: 'With dimensions',
						value: overview.coverage.bricklink_items_with_dims,
						tone: overview.coverage.bricklink_items_with_dims > 0 ? ('ok' as const) : ('neutral' as const)
					},
					{
						label: 'Per-color price rows',
						value: overview.coverage.price_color_rows_mapped_to_rb,
						tone: overview.coverage.price_color_rows_mapped_to_rb > 0 ? ('ok' as const) : ('neutral' as const)
					},
					{
						label: 'LDraw geometry',
						value: overview.coverage.parts_with_ldraw_geometry,
						tone: overview.coverage.parts_with_ldraw_geometry > 0 ? ('ok' as const) : ('neutral' as const)
					}
				]
			: []
	);
</script>

<svelte:head>
	<title>Parts database - Hive</title>
</svelte:head>

<PageHeader title="Parts database" description="The catalog built from Rebrickable, BrickStore and BrickLink, and their price guides, to browse and check." />

{#if error}<Alert tone="danger">{error}</Alert>{/if}

{#if overview}
	<Panel flush>
		<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4">
			{#each coverageCards as card (card.label)}
				<div class="border-t border-l border-line">
					<Stat label={card.label} value={fmt(card.value)} tone={card.tone === 'bad' ? 'danger' : card.tone === 'ok' ? 'success' : undefined} />
				</div>
			{/each}
		</div>
		<div class="num flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
			{#each Object.entries(overview.tables) as [name, count] (name)}
				<span><span class="text-ink">{fmt(count)}</span> <span class="font-mono">{name}</span></span>
			{/each}
		</div>
	</Panel>
{/if}

<Panel flush>
	<div class="flex flex-wrap items-center gap-2 px-(--pad-panel) py-3">
		<Input
			type="search"
			bind:value={query}
			onkeydown={(e) => e.key === 'Enter' && applyFilters()}
			placeholder="A part number, name or BrickLink ID"
			class="min-w-0 flex-1 sm:min-w-64"
		/>
		<Select
			class="w-full sm:w-64"
			label="Category"
			value={catId == null ? '' : String(catId)}
			options={[{ value: '', label: 'All categories' }, ...categories.map((cat) => ({ value: String(cat.id), label: cat.name, hint: fmt(cat.actual_part_count) }))]}
			onchange={(v: string) => (catId = v === '' ? null : Number(v))}
		/>
		<Select
			class="w-full sm:w-56"
			label="Connection"
			bind:value={missing}
			options={[
				{ value: '', label: 'Any connection' },
				{ value: 'bricklink_id', label: 'No BrickLink ID' },
				{ value: 'bricklink_item', label: 'No BrickLink item' }
			]}
		/>
		<Button variant="primary" icon={Search} onclick={applyFilters}>Search</Button>
	</div>
</Panel>

{#if loading}
	<div class="flex justify-center py-12"><Spinner size={32} /></div>
{:else}
	<Panel flush>
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr><th>Part</th><th>Name</th><th>Category</th><th>Years</th><th class="num">BrickLink IDs</th><th class="num">BrickLink items</th><th class="num">Prices</th></tr>
				</thead>
				<tbody>
					{#each parts as part (part.part_num)}
						<tr class="is-link" onclick={() => openDetail(part.part_num)}>
							<td>
								<div class="flex items-center gap-2">
									{#if part.part_img_url}
										<img src={part.part_img_url} alt="" class="size-8 object-contain" loading="lazy" />
									{:else}
										<div class="size-8 rounded-item bg-well"></div>
									{/if}
									<span class="font-mono">{part.part_num}</span>
								</div>
							</td>
							<td>{part.name}</td>
							<td class="text-ink-muted">{part._category_name}</td>
							<td class="num whitespace-nowrap text-ink-muted">{yearRange(part.year_from, part.year_to)}</td>
							<td class="num text-ink-muted">{part._bl_id_count}</td>
							<td class="num {part._bl_item_count > 0 ? 'text-success-ink' : 'text-danger-ink'}">{part._bl_item_count}</td>
							<td class="num text-ink-muted">{part._price_count}</td>
						</tr>
					{:else}
						<tr><td colspan="7" class="py-8 text-center text-ink-muted">No parts match.</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#snippet footer()}
			<span class="num mr-auto text-sm text-ink-muted">{fmt(pageStart)} to {fmt(pageEnd)} of {fmt(total)}</span>
			<Button size="sm" disabled={offset === 0} onclick={prevPage}>Previous</Button>
			<Button size="sm" disabled={offset + PAGE_SIZE >= total} onclick={nextPage}>Next</Button>
		{/snippet}
	</Panel>
{/if}

<Modal open={detailOpen} title={detail ? `${detail.part.part_num}, ${detail.part.name}` : 'Part'} size="lg" onclose={() => (detailOpen = false)}>
	{#if detailLoading}
		<div class="flex justify-center py-8"><Spinner size={32} /></div>
	{:else if detail}
		{@const d = detail}
		<div class="flex flex-col gap-5 text-sm">
			<div class="flex gap-4">
				{#if d.part.part_img_url}
					<img src={d.part.part_img_url} alt="" class="size-20 shrink-0 rounded-item bg-well object-contain" />
				{/if}
				<div class="min-w-0 flex-1">
					<KeyValue
						items={[
							{ label: 'Category', value: d.part._category_name ?? '-' },
							{ label: 'Years', value: yearRange(d.part.year_from, d.part.year_to) },
							{
								label: 'Size',
								value:
									d.part.dim_x_studs != null
										? `${d.part.dim_x_studs} by ${d.part.dim_y_studs} studs, ${(d.part.dim_x_studs * 8).toFixed(0)} by ${((d.part.dim_y_studs ?? 0) * 8).toFixed(0)} mm`
										: '-'
							}
						]}
					/>
					{#if d.part.part_url}
						<Button size="sm" variant="ghost" icon={ExternalLink} href={d.part.part_url} target="_blank" rel="noopener">On Rebrickable</Button>
					{/if}
				</div>
			</div>

			<section>
				<h3 class="label mb-1.5 flex items-center gap-2">
					The physical size, in mm
					{#if d.dimensions && d.dimensions.source !== 'none'}
						<Badge tone={d.dimensions.confidence === 'exact' ? 'success' : d.dimensions.confidence === 'family' ? 'info' : 'warning'}
							>{sentence(d.dimensions.confidence)}</Badge
						>
					{/if}
				</h3>
				{#if d.dimensions && d.dimensions.source !== 'none'}
					<div class="num flex flex-wrap gap-x-4 gap-y-1 text-ink">
						<span>Box {d.dimensions.bbox_x_mm} by {d.dimensions.bbox_y_mm} by {d.dimensions.bbox_z_mm ?? '?'} mm</span>
						<span>Longest {d.dimensions.max_extent_mm} mm</span>
						{#if d.dimensions.volume_mm3 != null}
							<span>Volume about {d.dimensions.volume_mm3} mm³</span>
						{/if}
					</div>
					<p class="mt-1 text-ink-muted">
						From {d.dimensions.source}{#if d.dimensions.physical_parent_part_num}, by way of the mold {d.dimensions.physical_parent_part_num}{/if}
					</p>
				{:else}
					<p class="text-ink-muted">No size for this part.</p>
				{/if}
			</section>

			<section>
				<h3 class="label mb-1.5">Other IDs, from Rebrickable</h3>
				{#if Object.keys(d.part.external_ids).length === 0}
					<p class="text-ink-muted">None.</p>
				{:else}
					<dl class="flex flex-col gap-1">
						{#each Object.entries(d.part.external_ids) as [source, ids] (source)}
							<div class="flex min-w-0 gap-2">
								<dt class="w-24 shrink-0 text-ink-muted">{source}</dt>
								<dd class="min-w-0 font-mono break-all text-ink">{ids.join(', ')}</dd>
							</div>
						{/each}
					</dl>
				{/if}
			</section>

			<section>
				<h3 class="label mb-1.5">BrickLink items, {d.bricklink.length}</h3>
				{#if d.bricklink.length === 0}
					<p class="text-ink-muted">No BrickLink mapping.</p>
				{:else}
					<ul class="divide-y divide-line rounded-control bg-well">
						{#each d.bricklink as link (link.item_no)}
							<li class="px-3 py-2">
								<div class="flex flex-wrap items-center gap-2">
									<span class="font-mono text-ink">{link.item_no}</span>
									{#if link.is_primary}<Badge tone="info">Primary</Badge>{/if}
									{#if link.has_item_record}<Badge tone="success">Item record</Badge>{:else}<Badge tone="danger">No item record</Badge>{/if}
									{#if link.has_price_guide}<Badge tone="success">Price guide</Badge>{/if}
									{#if link.is_obsolete}<Badge tone="warning">Obsolete</Badge>{/if}
								</div>
								{#if link.has_item_record}
									<div class="mt-1 text-ink-muted">
										{[link.bl_name ?? '-', link.bl_category_name, link.weight != null ? `${link.weight} g` : null, link.year_released]
											.filter(Boolean)
											.join(', ')}
									</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</section>

			<section>
				<h3 class="label mb-1.5">Prices by color, {d.prices.length}</h3>
				{#if d.prices.length === 0}
					<p class="text-ink-muted">No prices yet: run the price sync.</p>
				{:else}
					<div class="max-h-64 overflow-auto rounded-control bg-well">
						<table class="data-table">
							<thead class="sticky top-0 bg-well">
								<tr><th>Color</th><th class="num">New, average</th><th class="num">Used, average</th><th class="num">Used, quantity</th></tr>
							</thead>
							<tbody>
								{#each d.prices as p, i (i)}
									<tr>
										<td>
											{p.color_name ?? `BrickLink ${p.bl_color_id}`}
											{#if p.rb_color_id == null}{' '}<span class="text-ink-muted">(BrickLink only)</span>{/if}
										</td>
										<td class="num">{money(p.new_avg)}</td>
										<td class="num">{money(p.used_avg)}</td>
										<td class="num text-ink-muted">{p.used_qty ?? '-'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</section>
		</div>
	{/if}
</Modal>
