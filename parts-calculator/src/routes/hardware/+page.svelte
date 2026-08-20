<script lang="ts">
	import {
		Blocks,
		ChevronDown,
		ChevronRight,
		ExternalLink,
		ImageOff,
		ShoppingCart,
		Zap
	} from 'lucide-svelte';
	import Seo from '$lib/components/Seo.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import HardwareIcon from '$lib/components/HardwareIcon.svelte';
	import AlternativeBadge from '$lib/components/AlternativeBadge.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import LayerControl from '$lib/components/LayerControl.svelte';
	import HardwareDetailModal from '$lib/components/HardwareDetailModal.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import {
		assembliesContaining,
		bestUsVendor,
		buyCost,
		buyUnits,
		getHardware,
		HARDWARE,
		hardwareImage,
		hardwareLengthLabel,
		hardwareQtySource,
		hardwareTotalQty,
		JOIN_LABELS,
		packsNeeded,
		plainDescription,
		resolveHardwareTotals,
		SIZE_COLORS,
		usagePaths,
		fmtPrice,
		type Assembly,
		type Hardware
	} from '$lib/filament';
	import { layerStore } from '$lib/layers.svelte';
	import { hardwareCsv } from '$lib/hardware-csv';
	import { download, exportSpec, filename } from '$lib/csv';
	import { Download } from 'lucide-svelte';
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { browser } from '$app/environment';
	import { onMount } from 'svelte';

	// Every off-the-shelf part from the BOM sheet, in the unified data format.
	// Quantities come from the assembly tree wherever a part has been placed in
	// it; the sheet's hand counts (sheet_qty) are the fallback for the rest.
	const layers = $derived(layerStore.sizes.length);

	// categories in manifest order, preserving first-seen order
	const groups = $derived.by(() => {
		const by = new Map<string, Hardware[]>();
		for (const h of HARDWARE) {
			const cat = h.category ?? 'Other';
			if (!by.has(cat)) by.set(cat, []);
			by.get(cat)!.push(h);
		}
		return [...by.entries()];
	});

	// parts already placed in the assembly tree get their count computed from it
	const treeTotals = $derived(resolveHardwareTotals('machine', layers));

	// Sourcing/quantity math (totals, pricing, pack counts) lives in $lib/filament so
	// the list, the cart, and the detail modal all price a part identically. These two
	// wrappers just bind the shared resolvers to this page's live `treeTotals`.
	const totalQty = (h: Hardware, l: number) => hardwareTotalQty(h, treeTotals, l);
	const qtySource = (h: Hardware) => hardwareQtySource(h, treeTotals);

	/** How many distinct places on the machine an item lands in — the same paths
	 *  the detail modal lists under "Where it goes". Walked once for the whole
	 *  list rather than per row, since each call re-walks the tree from the root. */
	const placementCount = $derived.by(() => {
		const by = new Map<string, number>();
		for (const h of HARDWARE) by.set(h.id, usagePaths(h.id, layers).length);
		return by;
	});

	const QTY_TITLE = {
		tree: 'Counted from the assembly tree',
		sheet: 'Hand count carried over from the BOM sheet — not yet placed in the assembly tree'
	};

	// ------------------------------------------------------------------ joints
	// A part that gets soldered/crimped/glued to something else says so here, but
	// the fact lives on the assembly that joins them, not on the part — see
	// `joining` in $lib/filament. This page just reads it back out.
	const jointsOf = (h: Hardware) => assembliesContaining(h.id).filter((a) => a.joining?.length);

	/** An assembly with nothing but bought parts in it — no printed members, no
	 *  sub-assemblies. This page is a shopping list, so only those are ITS kind of
	 *  assembly: buy the pieces, join them, done. A light post is three printed
	 *  parts and some screws; it belongs on the parts tab, not here. */
	const isAllHardware = (a: Assembly) =>
		!!a.lines?.length && a.lines.every((l) => l.part != null && getHardware(l.part) != null);

	// Bought parts that are joined into one unit collapse to a single rollup row —
	// a Pico and its header pins are one purchase and one soldering job. Only
	// all-hardware assemblies qualify (see isAllHardware): a screw that self-taps
	// into a printed bracket is joined to plastic, not to other hardware, so it
	// stays its own row and explains itself on its detail modal instead.
	type Block = { kind: 'item'; hw: Hardware } | { kind: 'assembly'; asm: Assembly; items: Hardware[] };
	function groupBlocks(items: Hardware[]): Block[] {
		const blocks: Block[] = [];
		const claimed = new Set<string>();
		for (const h of items) {
			if (claimed.has(h.id)) continue;
			// members that live in this same category; the rollup lands where the
			// first one would have been, so category order is otherwise untouched
			const asm = jointsOf(h)
				.filter(isAllHardware)
				.find((a) => items.filter((m) => (a.lines ?? []).some((l) => l.part === m.id)).length > 1);
			if (!asm) {
				blocks.push({ kind: 'item', hw: h });
				continue;
			}
			const members = items.filter((m) => (asm.lines ?? []).some((l) => l.part === m.id));
			members.forEach((m) => claimed.add(m.id));
			blocks.push({ kind: 'assembly', asm, items: members });
		}
		return blocks;
	}

	let expandedAsm = $state<Record<string, boolean>>({});
	const asmAllOn = (items: Hardware[]) => items.every((h) => selected[h.id]);
	const asmSomeOn = (items: Hardware[]) => items.some((h) => selected[h.id]);
	const setAsm = (items: Hardware[], on: boolean) => {
		for (const h of items) selected[h.id] = on;
	};
	/** What the whole joined unit costs at the cheapest US vendor for each member. */
	const asmCost = (items: Hardware[]) =>
		items.reduce((sum, h) => {
			const v = bestUsVendor(h);
			return sum + (v ? (buyCost(v, buyUnits(h, totalQty(h, layers))) ?? 0) : 0);
		}, 0);

	// ---------------------------------------------------------------- selection
	// Everything starts unselected; the cart is opt-in. Only hardware with a
	// priced US vendor is buyable — "select all" and the total only ever touch
	// those, so an in-house part with no source yet can't end up selected.
	let selected = $state<Record<string, boolean>>({});
	const buyable = $derived(HARDWARE);
	const selectedList = $derived(buyable.filter((h) => selected[h.id]));
	const allSelected = $derived(buyable.every((h) => selected[h.id]));
	const setAll = (on: boolean) => {
		selected = on ? Object.fromEntries(buyable.map((h) => [h.id, true])) : {};
	};

	// ------------------------------------------------------------ detail modal
	// Deep-link the open item: `?hw=<id>` opens its detail modal, so a specific
	// part's view is a shareable link. Query params only exist in the browser —
	// the site is prerendered — so we read them on mount and mirror state back
	// in an effect, same pattern as the parts and laser-cut pages.
	let detail = $state<Hardware | null>(null);
	let detailOpen = $state(false);
	let urlReady = $state(false);
	function openDetail(h: Hardware) {
		detail = h;
		detailOpen = true;
	}

	onMount(() => {
		const id = page.url.searchParams.get('hw');
		const h = id ? getHardware(id) : undefined;
		if (h) openDetail(h);
		urlReady = true;
	});

	$effect(() => {
		if (!browser || !urlReady) return;
		const params = new URLSearchParams(page.url.search);
		if (detailOpen && detail) params.set('hw', detail.id);
		else params.delete('hw');
		const qs = params.toString();
		const target = qs ? `${location.pathname}?${qs}` : location.pathname;
		if (target !== location.pathname + location.search) replaceState(target, {});
	});
	// A click anywhere on a row opens its detail modal — except on the row's own
	// interactive controls, so ticking the checkbox or following a link doesn't.
	function rowClickToOpen(e: MouseEvent, h: Hardware) {
		if ((e.target as HTMLElement).closest('button, a, input, label')) return;
		openDetail(h);
	}

	const selectedTotal = $derived.by(() =>
		selectedList.reduce(
			// an item with no priced source contributes nothing rather than throwing —
			// every item is selectable now, sourced or not
			(sum, h) => {
				const v = bestUsVendor(h);
				return sum + (v ? (buyCost(v, buyUnits(h, totalQty(h, layers))) ?? 0) : 0);
			},
			0
		)
	);

	// -------------------------------------------------------------- csv export
	// The file has to stand alone: someone should be able to hand it to an
	// assistant and ask "which multipacks cover 90% of this?" without the page.
	function downloadCsv() {
		const spec = exportSpec(layers);
		const items = selectedList.length ? selectedList : HARDWARE;
		download(
			filename(spec, 'hardware'),
			hardwareCsv(items, spec, {
				qty: (h) => totalQty(h, layers),
				qtySource,
				buyUnits,
				vendor: bestUsVendor,
				packs: packsNeeded
			})
		);
	}

	// ------------------------------------------------------------ amazon cart
	// Amazon's Associates add-to-cart URL takes ASIN/quantity pairs directly, so a
	// static page can build one — no API, no key. It needs the ASIN, which only
	// canonical /dp/<ASIN> links expose; short links (amzn.to) hide it.
	const ASSOCIATE_TAG = 'sorterv2-20';
	const CART_BATCH = 20; // the endpoint rejects very long carts; batch to stay safe

	const asinOf = (url: string): string | null => url.match(/\/dp\/([A-Z0-9]{10})/)?.[1] ?? null;

	type CartLine = { h: Hardware; asin: string; packs: number };
	/** Selected parts split into what can and can't go in an Amazon cart. */
	const cart = $derived.by(() => {
		const lines: CartLine[] = [];
		const excluded: { h: Hardware; why: string }[] = [];
		for (const h of selectedList) {
			const v = bestUsVendor(h);
			const qty = totalQty(h, layers);
			if (!v) {
				excluded.push({ h, why: 'no US Amazon source' });
				continue;
			}
			const asin = asinOf(v.url);
			if (!asin) {
				// no ASIN means either a non-Amazon retailer or a short link that hides it
				excluded.push({
					h,
					why: /(^|\.)amazon\./.test(new URL(v.url).hostname)
						? 'source is a short link with no ASIN'
						: `sold by ${v.vendor ?? 'another retailer'}, not Amazon`
				});
				continue;
			}
			if (qty == null) {
				excluded.push({ h, why: 'quantity not settled' });
				continue;
			}
			lines.push({ h, asin, packs: packsNeeded(v, buyUnits(h, qty)!) });
		}
		const batches: string[] = [];
		for (let i = 0; i < lines.length; i += CART_BATCH) {
			const params = new URLSearchParams({ AssociateTag: ASSOCIATE_TAG });
			lines.slice(i, i + CART_BATCH).forEach((l, n) => {
				params.set(`ASIN.${n + 1}`, l.asin);
				params.set(`Quantity.${n + 1}`, String(l.packs));
			});
			batches.push(`https://www.amazon.com/gp/aws/cart/add.html?${params}`);
		}
		return { lines, excluded, batches };
	});
</script>

<Seo
	title="Hardware"
	description="Off-the-shelf hardware for the Sorter V2 — screws, bearings, motors and where each one goes, with sourcing links."
/>

<!-- One off-the-shelf part. Rendered standalone, or nested under the rollup row
     of the assembly it's joined into. -->
{#snippet hwRow(h: Hardware)}
	{@const qty = totalQty(h, layers)}
	{@const src = qtySource(h)}
	{@const img = hardwareImage(h)}
	{@const lengthLabel = hardwareLengthLabel(h)}
	{@const spots = placementCount.get(h.id) ?? 0}
	<div
		id="hardware-{h.id}"
		class="hw-row setup-card-shell flex cursor-pointer items-start gap-3 border p-3 {selected[h.id]
			? 'border-primary/60'
			: ''}"
		role="button"
		tabindex="0"
		title="View {h.name} details"
		onclick={(e) => rowClickToOpen(e, h)}
		onkeydown={(e) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				openDetail(h);
			}
		}}
	>
		<!-- the checkbox owns selection; its label keeps the hit target generous
		     without making the whole row a toggle. Every item is selectable, sourced
		     or not — an unsourced part still belongs in the exported list. -->
		<label class="mt-0.5 shrink-0 cursor-pointer p-0.5">
			<input
				type="checkbox"
				class="setup-toggle h-4 w-4"
				bind:checked={selected[h.id]}
				aria-label="Select {h.name}"
			/>
		</label>
		{#if img}
			<span class="hw-thumb relative shrink-0">
				<img src={img.src} alt={h.name} class="h-16 w-16 border border-border bg-white object-contain p-1" />
				<!-- A stand-in photo (a family photo, or the shared socket/button tile)
				     covers every length, so the length — the one thing it can't show —
				     is stamped on the corner. Any screw with a length gets it. -->
				{#if lengthLabel}
					<span class="hw-len">{lengthLabel}</span>
				{/if}
				<!-- hover preview; decorative, the thumbnail already carries the alt -->
				<img src={img.src} alt="" aria-hidden="true" class="hw-zoom" />
			</span>
		{:else}
			<div
				class="flex h-16 w-16 shrink-0 items-center justify-center border border-border bg-[var(--color-bg)] text-text-muted"
			>
				<ImageOff size={18} />
			</div>
		{/if}

		<div class="min-w-0 flex-1">
			<div class="flex items-start justify-between gap-3">
				<div class="flex flex-wrap items-center gap-1.5">
				<h3 class="flex items-center gap-1.5 text-sm font-semibold text-text">
						<HardwareIcon hw={h} />{h.name}
							<AlternativeBadge value={h.alternative} />
						<!-- Placed in the assembly tree, so the modal can say where it goes.
						     A quiet mark rather than a badge: it holds for most rows, and the
						     row's own content is what people are scanning for. -->
						{#if spots > 0}
							<span
								class="shrink-0 text-text-muted"
								title="Placed in the assembly — {spots} {spots === 1 ? 'spot' : 'spots'} on the machine"
							>
								<Blocks size={12} />
							</span>
						{/if}
					</h3>
					<ChangeStatus kind="hardware" id={h.id} name={h.name} />
				</div>
				<span
					class="shrink-0 text-right text-xs tabular-nums text-text-muted"
					title={src ? QTY_TITLE[src] : undefined}
				>
					{#if h.sheet_qty_text}
						{h.sheet_qty_text}
					{:else if qty == null}
						qty TBD
					{:else}
						<span class="font-semibold text-text">×{buyUnits(h, qty)}</span>
						{#if h.stock}
							<div>{h.stock.unit_label}</div>
						{:else if src === 'sheet' && h.sheet_qty?.per_layer != null}
							<div>({h.sheet_qty.per_layer}/layer)</div>
						{/if}
					{/if}
				</span>
			</div>
			<p class="mt-0.5 text-xs text-text-muted">{h.description}</p>
			{#if h.attributes?.length}
				<!-- specs that pin down which variant to buy. flex-wrap rather than
				     inline text: each spec stays whole, the row wraps between them. -->
				<div class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-muted">
					{#each h.attributes as a}
						<span>{a.label} <span class="text-text">{a.value}</span></span>
					{/each}
				</div>
			{/if}
			{#if h.note}
				<p class="mt-1 text-xs text-warning-dark">{h.note}</p>
			{/if}

			<div class="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-0.5">
				{#if h.sourcing?.vendors?.length}
					{#each h.sourcing.vendors as v (v.url)}
						{#if v.vendor === 'basically'}
							<!-- in-house part, not shipping yet — no link out, no price to show -->
							<span class="text-xs italic text-text-muted/70">Coming soon to basically</span>
						{:else}
							{@const cost = buyCost(v, buyUnits(h, qty))}
							<span class="inline-flex items-center gap-1 text-xs">
								<a
									href={v.affiliate_url ?? v.url}
									target="_blank"
									rel="noopener"
									class="inline-flex items-center gap-1 font-medium text-primary hover:text-primary-hover"
									title={v.as_of ? `price as of ${v.as_of}` : undefined}
								>
									{v.vendor ?? v.region}
									<span class="font-normal text-text-muted">({v.region})</span>
									<ExternalLink size={11} />
								</a>
								<!-- the untagged link lives on the detail modal, to keep rows terse -->
								<span class="tabular-nums text-text-muted">
									{#if fmtPrice(v)}
										{fmtPrice(v)}{v.pack_qty && v.pack_qty > 1 ? ` / ${v.pack_qty}` : ''}
										{#if cost != null && v.pack_qty && cost !== v.price}
											→ <span class="font-semibold text-text">${cost.toFixed(2)}</span>
										{/if}
									{:else}
										no price
									{/if}
								</span>
							</span>
						{/if}
					{/each}
				{:else}
					<span class="text-xs text-text-muted">No source picked yet.</span>
				{/if}
			</div>
		</div>
	</div>
{/snippet}

<div class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
	<header class="mb-4">
		<h1 class="text-2xl font-bold text-text">Hardware</h1>
	</header>

	<div class="mb-5">
		<Callout variant="warning" title="Work in progress">
			This list is incomplete and several quantities are unconfirmed. Open any item to see
			where its count comes from and where it goes on the machine.
		</Callout>
	</div>

	<div class="mb-6"><LayerControl /></div>

	<div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
		<!-- LEFT: one vertical list, grouped by category -->
		<div>
			<!-- the icons encode head shape + thread size; say so once, here -->
			<div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
				<span>Icon shows head shape; colour is thread size:</span>
				{#each Object.entries(SIZE_COLORS) as [sz, c] (sz)}
					<span class="inline-flex items-center gap-1">
						<span class="inline-block h-2.5 w-2.5" style="background:{c}"></span>{sz}
					</span>
				{/each}
			</div>
			<div class="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
				<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">
					Rough US total <span class="font-bold normal-case tracking-normal text-text"
						>${selectedTotal > 0 ? selectedTotal.toFixed(2) : '0.00'}</span
					>
					{#if selectedList.length}selected{/if}
				</span>
				<span class="text-sm text-text-muted">
					{selectedList.length}/{buyable.length} selected ·
					<button class="text-primary hover:text-primary-hover" onclick={() => setAll(!allSelected)}>
						{allSelected ? 'deselect all' : 'select all'}
					</button>
					<button
						class="ml-3 inline-flex items-center gap-1 text-primary hover:text-primary-hover"
						onclick={downloadCsv}
						title="Exports exactly what you have set up here: {selectedList.length ||
							HARDWARE.length} items at {layers} layers, with quantities resolved for that build."
					>
						<Download size={13} /> CSV
						<span class="font-normal text-text-muted"
							>· {selectedList.length ? `${selectedList.length} selected` : `all ${HARDWARE.length}`}, {layers}
							layers</span>
					</button>
				</span>
			</div>

			{#each groups as [cat, items] (cat)}
				<section class="mb-6">
					<h2 class="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">{cat}</h2>
					<div class="flex flex-col gap-2">
						{#each groupBlocks(items) as block (block.kind === 'item' ? block.hw.id : block.asm.id)}
							{#if block.kind === 'assembly'}
								{@const open = expandedAsm[block.asm.id]}
								{@const allOn = asmAllOn(block.items)}
								<div class="flex flex-col">
									<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
									<div
										class="hw-row setup-card-shell flex cursor-pointer items-center gap-3 border p-3 {allOn
											? 'border-primary/60'
											: ''}"
										role="button"
										tabindex="0"
										title={plainDescription(block.asm.description)}
										onclick={(e) => {
											if ((e.target as HTMLElement).closest('button, a, input, label')) return;
											expandedAsm[block.asm.id] = !open;
										}}
										onkeydown={(e) => {
											if (e.key === 'Enter' || e.key === ' ') {
												e.preventDefault();
												expandedAsm[block.asm.id] = !open;
											}
										}}
									>
										<label class="shrink-0 cursor-pointer p-0.5">
											<input
												type="checkbox"
												class="setup-toggle h-4 w-4"
												checked={allOn}
												indeterminate={!allOn && asmSomeOn(block.items)}
												onchange={() => setAsm(block.items, !allOn)}
												aria-label="Select every part in {block.asm.name}"
											/>
										</label>
										<!-- fanned thumbnails, same cue the printed-parts rollup uses -->
										<span class="hw-fan shrink-0">
											{#each block.items.slice(0, 3) as m, i (m.id)}
												{@const mi = hardwareImage(m)}
												{#if mi}
													<img src={mi.src} alt={m.name} style="z-index:{3 - i}" />
												{/if}
											{/each}
										</span>
										<div class="min-w-0 flex-1">
											<div class="flex flex-wrap items-center gap-1.5">
												{#if open}<ChevronDown size={15} class="text-text-muted" />{:else}<ChevronRight
														size={15}
														class="text-text-muted"
													/>{/if}
												<h3 class="text-sm font-semibold text-text">{block.asm.name}</h3>
												<Badge variant="info">Assembly</Badge>
												{#each block.asm.joining ?? [] as j (j.method)}
													<Badge variant="warning" title={j.note ? plainDescription(j.note) : undefined}>
														<Zap size={10} />{JOIN_LABELS[j.method]}
													</Badge>
												{/each}
											</div>
											<p class="mt-0.5 text-xs text-text-muted">
												{block.items.length} parts · click to {open ? 'collapse' : 'expand'}
											</p>
										</div>
										{#if asmCost(block.items) > 0}
											<span class="shrink-0 text-right text-xs tabular-nums text-text-muted">
												<span class="font-semibold text-text">${asmCost(block.items).toFixed(2)}</span>
												combined
											</span>
										{/if}
									</div>
									{#if open}
										<div class="hw-children mt-2 flex flex-col gap-2 pl-6">
											{#each block.items as m (m.id)}
												{@render hwRow(m)}
											{/each}
										</div>
									{/if}
								</div>
							{:else}
								{@render hwRow(block.hw)}
							{/if}
						{/each}
					</div>
				</section>
			{/each}

			<!-- Affiliate disclosure. Required because the vendor links and the cart
			     carry a referral tag; kept to one muted line at the foot of the page. -->
			<p class="mt-4 border-t border-border pt-3 text-[11px] text-text-muted">
				As an Amazon Associate we earn from qualifying purchases. Open any part for a
				“Not affiliate” link to the same listing without the referral tag.
			</p>
		</div>


		<!-- RIGHT: cart builder -->
		<aside class="setup-card-shell border p-4 lg:sticky lg:top-4">
			<h2
				class="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted"
			>
				<ShoppingCart size={13} /> Amazon cart
			</h2>

			{#if !selectedList.length}
				<p class="text-sm text-text-muted">
					Tick the parts you want, then build a cart with everything in it.
				</p>
			{:else}
				<div class="mb-3 text-sm text-text">
					<span class="font-semibold tabular-nums">{cart.lines.length}</span>
					{cart.lines.length === 1 ? 'item' : 'items'} ready ·
					<span class="font-semibold tabular-nums">${selectedTotal.toFixed(2)}</span>
				</div>

				{#each cart.batches as url, i (url)}
					<a
						href={url}
						target="_blank"
						rel="noopener"
						class="setup-button-primary mb-2 flex h-9 items-center justify-center gap-1.5 px-3 text-sm font-medium"
					>
						<ShoppingCart size={14} />
						{cart.batches.length > 1 ? `Add batch ${i + 1} of ${cart.batches.length}` : 'Add to Amazon cart'}
					</a>
				{/each}

				{#if cart.batches.length > 1}
					<p class="mb-2 text-[11px] text-text-muted">
						Split into batches — Amazon caps how many items one cart link can carry. Open each.
					</p>
				{/if}

				{#if cart.lines.length}
					<p class="text-[11px] text-text-muted">
						Quantities are whole packs, not individual pieces.
					</p>
				{/if}

				{#if cart.excluded.length}
					<div class="mt-3 border-t border-border pt-2">
						<p class="text-[11px] font-semibold text-warning-dark">
							{cart.excluded.length} can’t be added automatically
						</p>
						<ul class="mt-1 space-y-0.5">
							{#each cart.excluded as e (e.h.id)}
								<li class="text-[11px] text-text-muted">{e.h.name} — {e.why}</li>
							{/each}
						</ul>
					</div>
				{/if}
			{/if}
		</aside>
	</div>
</div>

<HardwareDetailModal bind:open={detailOpen} hardware={detail} {layers} showCart bind:selected />

<style>
	/* same hover as the 3D parts rows — the whole row is clickable, so it says so */
	.hw-row {
		transition: background-color 120ms;
	}
	.hw-row:hover {
		background: color-mix(in oklab, var(--color-bg) 55%, transparent);
	}

	/* the rollup row stands in for several parts, so its thumbnails overlap into a
	   small fan — the same "this is more than one thing" cue the printed list uses */
	.hw-fan {
		display: inline-flex;
	}
	.hw-fan :global(img) {
		position: relative;
		width: 2.75rem;
		height: 2.75rem;
		object-fit: contain;
		padding: 0.125rem;
		background: #fff;
		border: 1px solid var(--color-border);
	}
	.hw-fan :global(img + img) {
		margin-left: -1rem;
	}

	/* members sit on a tint and indent under the rollup, so an expanded assembly
	   still reads as one block rather than loose rows in the category */
	.hw-children {
		border-left: 2px solid var(--color-border);
		margin-left: 0.75rem;
	}

	/* One family photo covers every length in the family, so the length rides in
	   the thumbnail's corner. Small and quiet — the row states it in full below. */
	.hw-len {
		position: absolute;
		right: -1px;
		bottom: -1px;
		padding: 0 0.2rem;
		font-size: 9px;
		font-weight: 600;
		line-height: 1.35;
		font-variant-numeric: tabular-nums;
		color: var(--color-text);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
	}

	/* thumbnails are small enough that the part is hard to make out, so hovering
	   one blows it up beside the row. It takes pointer events (rather than
	   passing them through) so that moving the cursor onto the enlarged image
	   itself still counts as hovering — :hover cascades up to .hw-thumb from
	   any descendant the pointer is actually over, so the preview only closes
	   once the cursor leaves the image too, not the instant it crosses off the
	   64px thumbnail underneath it. */
	.hw-zoom {
		position: absolute;
		left: calc(100% + 0.5rem);
		top: 50%;
		width: 28rem;
		height: 28rem;
		/* the reset's img{max-width:100%} would clamp this to the 64px thumb box */
		max-width: none;
		padding: 0.5rem;
		object-fit: contain;
		background: #fff;
		border: 1px solid var(--color-border);
		box-shadow: 0 12px 32px rgb(0 0 0 / 0.22);
		opacity: 0;
		pointer-events: none;
		transform: translateY(-50%) scale(0.97);
		transition:
			opacity 120ms ease,
			transform 120ms ease;
		z-index: 40;
	}
	/* hover-capable pointers only, so a tap on touch doesn't leave it stuck open */
	@media (hover: hover) {
		.hw-thumb:hover .hw-zoom {
			opacity: 1;
			pointer-events: auto;
			transform: translateY(-50%) scale(1);
		}
	}
	/* On a narrow screen there is nowhere to put a 28rem preview, and being
	   absolutely positioned it still stretched the page's scroll width. The row
	   is tappable and the modal shows the image full size, so it just goes. */
	@media (max-width: 767px) {
		.hw-zoom {
			display: none;
		}
	}
</style>
