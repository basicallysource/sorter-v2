<script lang="ts">
	import { AlertTriangle, RefreshCw } from 'lucide-svelte';
	import Badge from './Badge.svelte';
	import PriorityBadge from './PriorityBadge.svelte';
	import Popover from './Popover.svelte';
	import { plannedChangesFor, type ChangeTargetKind } from '$lib/filament';

	let { kind, id, name }: { kind: ChangeTargetKind; id: string; name: string } = $props();
	const changes = $derived(plannedChangesFor(kind, id));
</script>

{#each changes as change (change.id)}
	{@const isBroken = change.condition === 'broken'}
	{@const isNiceToHave = Number(change.priority.slice(1)) >= 4}
	<Popover width="w-80" label={isNiceToHave ? `Possible improvement for ${name}` : isBroken ? `Broken feature on ${name}` : `Why ${name} is subject to change`}>
		{#snippet trigger({ toggle, open })}
			<PriorityBadge as="button" priority={change.priority} class={isBroken ? 'uppercase tracking-wide' : ''} onclick={toggle} aria-expanded={open}>
				{#if isBroken}<AlertTriangle size={11} /> Broken Feature{:else}<RefreshCw size={11} /> {isNiceToHave ? 'Nice to Improve' : 'Subject to Change'}{/if} · {change.priority}
			</PriorityBadge>
		{/snippet}
		<div class="flex items-start gap-2">
			<AlertTriangle size={14} class="mt-0.5 shrink-0 {isBroken ? 'text-danger' : 'text-warning-dark'}" />
			<div>
				<b class="text-text">{isBroken ? 'This design has a broken feature that is intended to be fixed.' : isNiceToHave ? 'The current design is usable; this improvement would be nice to have.' : 'Works now, but is intended to be replaced shortly with an improvement.'}</b>
				<p class="mt-1"><b>{change.priority}</b> priority — {isBroken && change.priority === 'P0' ? 'highest priority.' : isNiceToHave ? 'nice-to-have improvement.' : 'planned change.'}</p>
			</div>
		</div>
		<div class="mt-2 border-t border-border pt-2 text-text">
			<PriorityBadge priority={change.priority} />
			<a class="ml-1 font-semibold text-primary hover:text-primary-hover" href="/changes#{change.id}">{change.name}</a>
			<p class="mt-1">{change.description}</p>
			{#if change.images?.length}
				<div class="mt-2 space-y-1.5">
					{#each change.images as image}
						<figure>
							<img src={image.url} alt={image.alt} class="max-h-44 w-full border border-border bg-white object-contain" />
							{#if image.caption}<figcaption class="mt-1 text-[10px] text-text-muted">{image.caption}</figcaption>{/if}
						</figure>
					{/each}
				</div>
			{/if}
		</div>
	</Popover>
{/each}
