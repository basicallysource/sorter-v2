<script lang="ts">
	import type { PartsGroup, ResolvedPart } from '$lib/server/content';

	let {
		parts,
		tools
	}: {
		parts?: { groups: PartsGroup[]; notes: ResolvedPart[] };
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
										{#if part.image}
											<img class="part-card-img" src={part.image} alt={part.name} loading="lazy" />
										{/if}
										{#if part.qty}<span class="part-card-qty">{part.qty}×</span>{/if}
										<!-- One screw photo stands in for every length in its family, so the
										     length gets stamped on the corner, as on the parts calculator. -->
										{#if part.length_mm}<span class="part-card-len">{part.length_mm}mm</span>{/if}
										{#if part.not_in_calc}<span class="part-card-warn" title="Not currently in the parts calculator">!</span>{/if}
										{#if part.alternative}<span
												class="part-card-alt"
												title={typeof part.alternative === 'string'
													? part.alternative
													: 'Interchangeable alternative'}>A</span
											>{/if}
									</div>
									<span class="part-card-name">
										{#if part.page}<a href={part.page}>{part.name}</a>{:else}{part.name}{/if}
									</span>
									{#if part.caption}<span class="part-card-caption">{part.caption}</span>{/if}
								{/if}
							</li>
						{/each}
					</ul>
				{/each}
				{#if parts.notes.length}
					<ul class="parts-notes">
						{#each parts.notes as part (part.id)}
							<li><strong>{part.name}:</strong> {part.notes}</li>
						{/each}
					</ul>
				{/if}
				{#if parts.groups.some((g) => g.parts.some((p) => p.not_in_calc))}
					<p class="parts-warn-legend"><span class="part-card-warn">!</span> not currently in the parts calculator.</p>
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
{/if}
