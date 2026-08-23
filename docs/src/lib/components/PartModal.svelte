<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import StlViewer from '$lib/components/StlViewer.svelte';
	import type { ResolvedPart } from '$lib/server/content';

	// What a "Parts needed" card opens: the same facts the parts calculator's own
	// part modal shows, rendered in this site's styling, off the same generated
	// catalog both sites build from. Deliberately not a copy of everything over
	// there — versions, candidates, build plates and the cart maths stay one
	// click away on the part's own calculator page, which every modal links to.
	let { open = $bindable(false), part }: { open?: boolean; part: ResolvedPart | null } = $props();

	const detail = $derived(part?.detail);

	function duration(seconds: number): string {
		const h = Math.floor(seconds / 3600);
		const m = Math.round((seconds % 3600) / 60);
		return h ? `${h} h ${m} min` : `${m} min`;
	}

	function fmtDate(value?: string): string {
		if (!value) return '—';
		const d = new Date(value);
		return isNaN(+d)
			? value
			: d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
	}
</script>

<Modal bind:open title={part?.name} subtitle={part?.id}>
	{#if part && detail}
		<div class="part-modal">
			<div class="part-modal-media">
				{#if detail.kind === 'printed' && detail.stl}
					{#key detail.stl}
						<StlViewer url={detail.stl} poster={part.image} />
					{/key}
				{:else if part.image}
					<img class="part-modal-img" src={part.image} alt={part.name} />
				{:else}
					<p class="part-modal-noimg">No image for this part yet.</p>
				{/if}
			</div>

			<div class="part-modal-detail">
				{#each detail.changes ?? [] as change (change.id)}
					{@const broken = change.condition === 'broken'}
					<div class="callout {broken ? 'callout-warning' : ''} part-modal-change">
						<span class="callout-icon" aria-hidden="true">{broken ? '⚠' : '↻'}</span>
						<p>
							<strong
								>{broken ? 'Broken feature' : 'Subject to change'} · {change.priority} · {change.name}</strong
							><br />{change.description}
						</p>
					</div>
				{/each}

				{#if detail.description}<p class="part-modal-desc">{detail.description}</p>{/if}
				{#if detail.info}<p class="part-modal-note">{detail.info}</p>{/if}
				{#if detail.note}<p class="part-modal-note">{detail.note}</p>{/if}
				{#if detail.low_tolerance}
					<div class="callout callout-warning part-modal-change">
						<span class="callout-icon" aria-hidden="true">⚠</span>
						<p>
							<strong>Low tolerance, test print suggested.</strong>
							{detail.low_tolerance_note ??
								'This part has little room for dimensional error. Print one first and confirm the fit before committing to the full set.'}
						</p>
					</div>
				{/if}

				{#if detail.attributes?.length}
					<ul class="part-modal-attrs">
						{#each detail.attributes as attr (attr.label)}
							<li><span>{attr.label}</span> {attr.value}</li>
						{/each}
					</ul>
				{/if}

				{#if detail.kind === 'printed'}
					<dl class="part-modal-facts">
						<div>
							<dt>Version</dt>
							<dd>v{detail.version ?? '1'}</dd>
						</div>
						<div>
							<dt>Updated</dt>
							<dd>{fmtDate(detail.updated_at)}</dd>
						</div>
						<div>
							<dt>Filament</dt>
							<dd>{detail.grams != null ? `${detail.grams.toFixed(0)} g` : '—'}</dd>
						</div>
						<div>
							<dt>Print time</dt>
							<dd>{detail.print_seconds != null ? duration(detail.print_seconds) : '—'}</dd>
						</div>
					</dl>
				{/if}

				{#if detail.stock_label || detail.sheet_qty_text}
					<p class="part-modal-note">
						{#if detail.stock_label}Sold as a {detail.stock_label}.{/if}
						{#if detail.sheet_qty_text}{detail.sheet_qty_text}{/if}
					</p>
				{/if}

				{#if part.qty}
					<p class="part-modal-note">This page needs <strong>{part.qty}×</strong> of it.</p>
				{/if}

				{#if detail.requires?.length}
					<div class="part-modal-block">
						<h3>Takes</h3>
						<ul class="part-modal-list">
							{#each detail.requires as req (req.id)}
								<li>{req.qty}× {req.name}</li>
							{/each}
						</ul>
					</div>
				{/if}

				{#if detail.vendors?.length}
					<div class="part-modal-block">
						<h3>Where to buy</h3>
						<ul class="part-modal-list">
							{#each detail.vendors as vendor (vendor.url)}
								<li>
									<a href={vendor.url} target="_blank" rel="noopener nofollow sponsored"
										>{vendor.vendor}</a
									>{#if vendor.region}<span class="part-modal-region"> {vendor.region}</span>{/if}
								</li>
							{/each}
						</ul>
					</div>
				{/if}

				<div class="part-modal-actions">
					{#if detail.kind === 'printed' && detail.stl}
						<a class="part-modal-button" href={detail.stl} download>Download STL</a>
					{:else if detail.kind === 'lasercut' && detail.dxf}
						<a class="part-modal-button" href={detail.dxf} download>Download DXF</a>
					{/if}
					<a class="part-modal-link" href={detail.calc_url} target="_blank" rel="noopener">
						{detail.kind === 'lasercut' ? 'Laser-cut parts' : 'Everything else'} on the parts calculator
						↗
					</a>
					{#if part.page}<a class="part-modal-link" href={part.page}>Its page in these docs</a>{/if}
					{#if detail.onshape}<a
							class="part-modal-link"
							href={detail.onshape}
							target="_blank"
							rel="noopener">OnShape ↗</a
						>{/if}
				</div>
			</div>
		</div>
	{/if}
</Modal>
