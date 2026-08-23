<script lang="ts">
	import PartModal from '$lib/components/PartModal.svelte';
	import type { PartsGroup, ResolvedPart } from '$lib/server/content';

	// The card a reader clicks opens the part's detail (the 3D model, the print
	// facts, the download, the way through to the parts calculator). Both sites
	// read the same generated catalog, so the modal shows the same part the
	// calculator would.
	let openPart = $state<ResolvedPart | null>(null);
	let modalOpen = $state(false);

	// TEMP screenshot hook, reverted before this branch is reviewed.
	$effect(() => {
		const all = (parts?.groups ?? []).flatMap((g) => g.parts);
		const first = all.find((p) => p.detail?.stl) ?? all.find((p) => p.detail);
		if (first) { openPart = first; modalOpen = true; }
	});

	function show(part: ResolvedPart) {
		if (!part.detail) return; // an id the catalog does not describe: nothing to open
		openPart = part;
		modalOpen = true;
	}

	function fmtClaim(value: unknown): string {
		if (value == null) return 'none';
		if (Array.isArray(value)) {
			if (!value.length) return 'none';
			return value
				.map((v) =>
					v && typeof v === 'object' && 'part' in v
						? `${(v as { qty?: number }).qty ?? 1}× ${(v as { part: string }).part}`
						: String(v)
				)
				.join(' + ');
		}
		return String(value);
	}

	let {
		parts,
		tools
	}: {
		parts?: { groups: PartsGroup[]; conflicts: ResolvedPart[] };
		tools?: string[];
	} = $props();
</script>

{#if parts || tools}
	<div class="requirements">
		{#if parts}
			<section class="requirements-block">
				<h2 class="requirements-title">Parts needed</h2>
				{#each parts.groups as group (group.category)}
					{#if parts.groups.length > 1 || group.category !== 'Other'}
						<p class="parts-category">{group.category}</p>
					{/if}
					<ul class="parts-list">
						{#each group.parts as part (part.id)}
							<li class="part-card">
								{#if part.missing}
									<span class="part-card-name part-card-missing">{part.id}</span>
								{:else}
									<div class="part-card-media">
										<!-- the button carries only the image: the corner badges are its
										     siblings, painted over it, so a badge's popover stays reachable
										     without nesting one control inside another -->
										<button
											class="part-card-open"
											type="button"
											onclick={() => show(part)}
											disabled={!part.detail}
											aria-label="Open details for {part.name}"
											aria-haspopup="dialog"
										>
											{#if part.image}
												<img class="part-card-img" src={part.image} alt={part.name} loading="lazy" />
											{:else}
												<span class="part-card-img part-card-noimg">no image</span>
											{/if}
										</button>
										{#if part.qty}<span class="part-card-qty part-badge" tabindex="0"
											>{part.qty}×<span class="part-badge-pop">How many this step needs.</span></span
										>{/if}
										<!-- One photo stands in for every length in a screw family, and for
										     every cut length of 2020 extrusion, so the length gets stamped on
										     the corner, as on the parts calculator. -->
										{#if part.length_mm}<span class="part-card-len part-badge" tabindex="0"
											>{part.length_mm}mm<span class="part-badge-pop"
												>Length of this piece — the shared photo stands in for every length.</span
											></span
										>{/if}
										{#if part.conflicts?.length}<span class="part-card-conflict part-badge" tabindex="0"
											><svg
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="2.4"
												stroke-linecap="round"
												stroke-linejoin="round"
												aria-label="Unresolved catalog conflict"
												><path
													d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 20h16a2 2 0 0 0 1.73-2Z"
												/><path d="M12 9v4" /><path d="M12 17h.01" /></svg
											><span class="part-badge-pop part-badge-pop-wide">
												{#each part.conflicts as c, i (c.field)}
													<span class={i > 0 ? 'part-badge-pop-rule' : ''}>
														<strong>Conflict · {c.merge}</strong><br />
														{#if c.note}{c.note}<br />{/if}
														{#each c.claims as claim, j (claim.source)}{j > 0
																? ' · '
																: ''}<strong>{claim.source}:</strong> {fmtClaim(claim.value)}{/each}
													</span>
												{/each}
											</span></span
										>{/if}
										{#if part.alternative}<span class="part-card-alt part-badge" tabindex="0"
											>A<span class="part-badge-pop"
												><strong>Interchangeable alternative</strong><br />{typeof part.alternative ===
												'string'
													? part.alternative
													: 'Either variant works here (e.g. socket vs button head).'}</span
											></span
										>{/if}
									</div>
									<span class="part-card-name">
										<button
											class="part-card-name-button"
											type="button"
											onclick={() => show(part)}
											disabled={!part.detail}>{part.name}</button
										>
									</span>
									{#if part.caption}<span class="part-card-caption">{part.caption}</span>{/if}
								{/if}
							</li>
						{/each}
					</ul>
				{/each}
				{#if parts.conflicts.length}
					<p class="parts-warn-legend">
						<span class="part-card-conflict">?</span> the docs and the parts calculator disagreed
						about this part when their catalogs were merged (2026-08-21); not yet settled against
						the machine:
					</p>
					<ul class="parts-notes">
						{#each parts.conflicts as part (part.id)}
							{#each part.conflicts ?? [] as conflict (conflict.field)}
								<li><strong>{part.name}:</strong> {conflict.note ?? conflict.field}</li>
							{/each}
						{/each}
					</ul>
				{/if}
				{#if parts.groups.some((g) => g.parts.some((p) => p.alternative))}
					<p class="parts-warn-legend"><span class="part-card-alt">A</span> an interchangeable alternative works (hover for what).</p>
				{/if}
			</section>
		{/if}

		{#if tools}
			<section class="requirements-block">
				<h2 class="requirements-title">Tools needed</h2>
				<ul class="tools-list">
					{#each tools as tool (tool)}<li>{tool}</li>{/each}
				</ul>
			</section>
		{/if}
	</div>
	<PartModal bind:open={modalOpen} part={openPart} />
{/if}
