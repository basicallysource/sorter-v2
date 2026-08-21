<script lang="ts">
	import AssemblyDescription from '$lib/components/AssemblyDescription.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import { copyText } from '$lib/clipboard';
	import { SITE_URL } from '$lib/seo';
	import {
		assembliesContaining,
		bestUsVendor,
		buyCost,
		buyUnits,
		fmtPrice,
		getHardware,
		getPart,
		hardwareImage,
		hardwareQtySource,
		hardwareTotalQty,
		JOIN_LABELS,
		lineQty,
		packsNeeded,
		resolveHardwareTotals,
		usagePaths,
		type Assembly,
		type Hardware
	} from '$lib/filament';
	import { ArrowUpRight, Check, ExternalLink, Share2, Zap } from 'lucide-svelte';

	// The off-the-shelf hardware detail view: photo, specs, where it goes on the
	// machine, what it's joined to, and where to buy it. Rendered two ways off the
	// SAME markup — inside HardwareDetailModal (hardware page, assembly tab) and as
	// the standalone /part/<id> page, exactly as PartDetail is for printed parts.
	// `showCart` + `selected` wire the Amazon-cart checkbox on the hardware page;
	// pages without a cart (the assembly tab, the standalone page) leave them off.
	let {
		hardware,
		layers,
		showCart = false,
		selected = $bindable({})
	}: {
		hardware: Hardware;
		layers: number;
		showCart?: boolean;
		selected?: Record<string, boolean>;
	} = $props();

	// parts already placed in the assembly tree get their count computed from it
	const treeTotals = $derived(resolveHardwareTotals('machine', layers));

	// A part that gets soldered/crimped/glued to something else says so here, but the
	// fact lives on the assembly that joins them, not on the part.
	const jointsOf = (h: Hardware) => assembliesContaining(h.id).filter((a) => a.joining?.length);

	/** The other members of an assembly, resolved to a display name and quantity. */
	function siblings(asm: Assembly, selfId: string) {
		return (asm.lines ?? [])
			.filter((l) => l.part && l.part !== selfId)
			.map((l) => {
				const id = l.part!;
				return {
					id,
					name: getHardware(id)?.name ?? getPart(id)?.name ?? id,
					qty: lineQty(l, layers)
				};
			});
	}

	// The view answers "where does this live?": the paths down to the item, then the
	// walk up through the assemblies that contain it.
	const paths = $derived(usagePaths(hardware.id, layers));
	const assemblyHref = (id: string) => `/assembly?focus=${encodeURIComponent(id)}`;

	// Share = the item's permanent /part/<id> page, which unfurls with its own product
	// photo + name. The hardware page's ?hw=… deep link can't do that on a static site
	// (crawlers don't run JS and every ?hw=… serves the same prerendered HTML).
	let copied = $state(false);
	let copyTimer: ReturnType<typeof setTimeout> | undefined;
	async function share() {
		if (await copyText(`${SITE_URL}/part/${hardware.id}`)) {
			copied = true;
			clearTimeout(copyTimer);
			copyTimer = setTimeout(() => (copied = false), 1800);
		}
	}
</script>

{#key hardware.id}
	{@const h = hardware}
	{@const qty = hardwareTotalQty(h, treeTotals, layers)}
	{@const src = hardwareQtySource(h, treeTotals)}
	{@const dimg = hardwareImage(h)}
	<!-- the view owns its own padding: Modal supplies none, and the page shell is bare -->
	<div class="p-4">
		<div class="flex flex-col gap-4 sm:flex-row">
			{#if dimg}
				<img
					src={dimg.src}
					alt={h.name}
					class="h-72 w-72 shrink-0 self-start border border-border bg-white object-contain p-2 sm:h-80 sm:w-80"
				/>
			{/if}
			<div class="min-w-0 flex-1">
				<p class="text-sm text-text-muted">{h.description}</p>
				{#if h.note}
					<p class="mt-2 border border-warning/50 bg-warning/[0.08] p-2 text-sm text-warning-dark">
						{h.note}
					</p>
				{/if}

				<dl class="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
					<dt class="text-text-muted">Needed</dt>
					<dd class="text-text">
						{#if h.sheet_qty_text}
							{h.sheet_qty_text}
						{:else if qty == null}
							not settled yet
						{:else}
							{buyUnits(h, qty)}{#if h.stock}&nbsp;×&nbsp;{h.stock.unit_label}{/if}
							{#if src === 'tree'}
								<span class="text-text-muted">— summed from the assembly tree</span>
							{:else}
								<span class="text-warning-dark">
									— hand count from the BOM sheet, not placed in the assembly tree yet
									{#if h.sheet_qty?.per_layer != null}({h.sheet_qty.per_layer} per layer
										× {layers} layers){/if}
								</span>
							{/if}
						{/if}
					</dd>
					{#if h.stock}
						<dt class="text-text-muted">Cut into</dt>
						<dd class="text-text">
							{qty} × {h.stock.piece_label}
						</dd>
					{/if}
					{#each h.attributes ?? [] as a}
						<dt class="text-text-muted">{a.label}</dt>
						<dd class="text-text">{a.value}</dd>
					{/each}
				</dl>
				<div class="mt-3">
					<button
						type="button"
						onclick={share}
						class="inline-flex items-center gap-1 text-xs {copied
							? 'text-success'
							: 'text-primary hover:text-primary-hover'}"
						title="Copy a shareable link to this part's page"
					>
						{#if copied}<Check size={13} /> Copied{:else}<Share2 size={13} /> Share{/if}
					</button>
				</div>
			</div>
		</div>

		{#if paths.length}
			<h4 class="mt-5 text-xs font-semibold uppercase tracking-wider text-text-muted">
				Where it goes
			</h4>
			<div class="mt-2 space-y-2">
				{#each paths as path, pi (pi)}
					{@const inner = path.steps[path.steps.length - 1].assembly}
					<div class="border border-border p-3">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0">
								<!-- innermost first: the assembly you'd actually be holding -->
								<div class="flex flex-wrap items-baseline gap-x-1.5">
									<span class="text-sm font-semibold text-text">{inner.name}</span>
									{#if path.via}
										<span class="text-xs text-text-muted">in the {path.via.name}</span>
									{/if}
									<span class="text-xs tabular-nums text-text-muted">· {path.qty} here</span>
								</div>
								<!-- then the walk up, outermost last -->
								<div class="mt-1 flex flex-wrap items-center gap-x-1 text-xs text-text-muted">
									{#each path.steps as step, si (si)}
										{#if si > 0}<span aria-hidden="true">›</span>{/if}
										<a
											href={assemblyHref(step.assembly.id)}
											class="hover:text-primary hover:underline"
											title="Show {step.assembly.name} on the assembly tree"
										>{step.assembly.name}</a>
									{/each}
								</div>
							</div>
							<a
								href={assemblyHref(inner.id)}
								class="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover"
								title="Open {inner.name} on the assembly tree"
							>
								Go to <ArrowUpRight size={12} />
							</a>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- how the count was arrived at: jargon the list itself shouldn't carry -->
		<p class="mt-3 text-xs {src === 'sheet' ? 'text-warning-dark' : 'text-text-muted'}">
			{src === 'sheet'
				? 'This count is a hand count carried over from the BOM spreadsheet — it has not been placed in the assembly tree yet, so it may not match the machine.'
				: src === 'tree'
					? 'This count is summed from the machine assembly tree.'
					: 'No count settled for this item yet.'}
		</p>

		{#each jointsOf(h) as asm (asm.id)}
			<h4 class="mt-5 text-xs font-semibold uppercase tracking-wider text-text-muted">
				Goes together with
			</h4>
			<div class="mt-2 border border-border p-3">
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
					<span class="text-sm font-semibold text-text">{asm.name}</span>
					{#each asm.joining ?? [] as j (j.method)}
						<Badge variant="warning"><Zap size={10} />{JOIN_LABELS[j.method]}</Badge>
					{/each}
				</div>
				<AssemblyDescription text={asm.description} class="mt-1 text-xs text-text-muted" />
				<ul class="mt-2 space-y-0.5 text-sm text-text">
					{#each siblings(asm, h.id) as s (s.id)}
						<li class="tabular-nums">
							<span class="text-text-muted">×{s.qty}</span>
							{s.name}
						</li>
					{/each}
				</ul>
				{#each asm.joining ?? [] as j (j.method)}
					{#if j.note}
						<AssemblyDescription text={j.note} class="mt-2 text-xs text-warning-dark" />
					{/if}
				{/each}
			</div>
		{/each}

		<h4 class="mt-5 text-xs font-semibold uppercase tracking-wider text-text-muted">Where to buy</h4>
		<div class="mt-2 divide-y divide-border border border-border">
			{#each h.sourcing?.vendors ?? [] as v (v.url)}
				{#if v.vendor === 'basically'}
					<!-- in-house part, not shipping yet — no link out, no price to show -->
					<div class="p-2 text-sm italic text-text-muted/70">Coming soon to basically</div>
				{:else}
					{@const cost = buyCost(v, buyUnits(h, qty))}
					<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 p-2 text-sm">
						<span class="inline-flex items-center gap-2">
							<a
								href={v.affiliate_url ?? v.url}
								target="_blank"
								rel="noopener"
								class="inline-flex items-center gap-1 font-medium text-primary hover:text-primary-hover"
							>
								{v.vendor ?? v.region} <ExternalLink size={12} />
							</a>
							<span class="text-xs text-text-muted">{v.region}</span>
							{#if v.affiliate_url}
								<a
									href={v.url}
									target="_blank"
									rel="noopener"
									class="text-xs text-text-muted underline decoration-dotted underline-offset-2 hover:text-text"
									title="The same listing, without the referral tag">Not affiliate</a
								>
							{/if}
						</span>
						<span class="tabular-nums text-text-muted">
							{#if fmtPrice(v)}
								{fmtPrice(v)}{v.pack_qty && v.pack_qty > 1 ? ` for ${v.pack_qty}` : ''}
								{#if cost != null && v.pack_qty && qty != null}
									· buy <span class="text-text">{packsNeeded(v, buyUnits(h, qty)!)}</span> =
									<span class="font-semibold text-text">${cost.toFixed(2)}</span>
								{/if}
							{:else}
								no price recorded
							{/if}
							{#if v.as_of}<span class="ml-2 text-xs">as of {v.as_of}</span>{/if}
						</span>
						{#if v.note}<span class="w-full text-xs text-text-muted">{v.note}</span>{/if}
					</div>
				{/if}
			{:else}
				<p class="p-2 text-sm text-text-muted">No source picked yet.</p>
			{/each}
		</div>

		{#if showCart && bestUsVendor(h)}
			<label class="mt-4 flex cursor-pointer items-center gap-2 text-sm text-text">
				<input type="checkbox" class="setup-toggle h-4 w-4" bind:checked={selected[h.id]} />
				Include in the Amazon cart
			</label>
		{/if}
	</div>
{/key}
