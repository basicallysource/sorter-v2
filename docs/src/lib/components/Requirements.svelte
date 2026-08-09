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
									</div>
									<span class="part-card-name">
										{#if part.page}<a href={part.page}>{part.name}</a>{:else}{part.name}{/if}
									</span>
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
