<script lang="ts">
	import { AlertTriangle, RefreshCw } from 'lucide-svelte';
	import PriorityBadge from './PriorityBadge.svelte';
	import Popover from './Popover.svelte';
	import { plannedChangesFor, type ChangePriority, type ChangeTargetKind, type PlannedChange } from '$lib/filament';

	// Every open notice on one thing, collapsed into a single control. A part can
	// carry several at once (a broken feature plus two nice-to-haves), and one
	// badge per change turned the row into a wall of them — so the trigger takes
	// its tone from the worst one and the panel lists them all.
	//
	// `variant`:
	//   badge  — the inline badge that sits next to a name.
	//   marker — a small corner mark for an image tile, for the views where a part
	//            is a picture and nothing else. Needs a positioned ancestor.
	let {
		kind,
		id,
		name,
		variant = 'badge',
		align = 'left'
	}: {
		kind: ChangeTargetKind;
		id: string;
		name: string;
		variant?: 'badge' | 'marker';
		align?: 'left' | 'right';
	} = $props();

	const rank = (change: PlannedChange) =>
		(change.condition === 'broken' ? 0 : 1) * 100 + (Number.parseInt(change.priority.slice(1), 10) || 0);
	const changes = $derived([...plannedChangesFor(kind, id)].sort((a, b) => rank(a) - rank(b)));
	const lead = $derived(changes[0]);
	const anyBroken = $derived(changes.some((change) => change.condition === 'broken'));
	// Worst priority across the notices, which is the number the trigger shows.
	const topPriority = $derived(
		changes.reduce<ChangePriority>(
			(worst, change) =>
				(Number.parseInt(change.priority.slice(1), 10) || 0) < (Number.parseInt(worst.slice(1), 10) || 0)
					? change.priority
					: worst,
			changes[0]?.priority ?? 'P9'
		)
	);
	const allNiceToHave = $derived(changes.every((change) => Number(change.priority.slice(1)) >= 4));
	const label = $derived(
		changes.length > 1
			? `${changes.length} notices on ${name}`
			: allNiceToHave
				? `Possible improvement for ${name}`
				: anyBroken
					? `Broken feature on ${name}`
					: `Why ${name} is subject to change`
	);
	const headline = $derived(
		anyBroken
			? 'This design has a broken feature that is intended to be fixed.'
			: allNiceToHave
				? 'The current design is usable; these improvements would be nice to have.'
				: 'Works now, but is intended to be replaced shortly with an improvement.'
	);
</script>

{#if changes.length}
	<!-- Left by default, both variants. The parts table scrolls horizontally
	     (`.pl-scroll`), which clips an absolutely positioned panel, and a marker
	     sits in the narrow thumbnail cell at the very left — so a right-aligned
	     panel runs 20rem off the edge of the table and loses its first half.
	     Opening rightwards into the table body always has room. -->
	<Popover width="w-80" {align} {label}>
		{#snippet trigger({ toggle, open })}
			{#if variant === 'marker'}
				<button
					type="button"
					class="change-marker"
					class:is-broken={anyBroken}
					onclick={toggle}
					aria-expanded={open}
					aria-label={label}
				>
					<AlertTriangle size={11} />
					{#if changes.length > 1}<span class="change-marker-n">{changes.length}</span>{/if}
				</button>
			{:else}
				<PriorityBadge
					as="button"
					priority={topPriority}
					class={anyBroken ? 'uppercase tracking-wide' : ''}
					onclick={toggle}
					aria-expanded={open}
				>
					{#if anyBroken}<AlertTriangle size={11} />{:else}<RefreshCw size={11} />{/if}
					{#if changes.length > 1}
						{changes.length} Notices
					{:else if anyBroken}
						Broken Feature
					{:else}
						{allNiceToHave ? 'Nice to Improve' : 'Subject to Change'}
					{/if}
					· {topPriority}
				</PriorityBadge>
			{/if}
		{/snippet}
		<div class="flex items-start gap-2">
			<AlertTriangle size={14} class="mt-0.5 shrink-0 {anyBroken ? 'text-danger' : 'text-warning-dark'}" />
			<div>
				<b class="text-text">{headline}</b>
				<p class="mt-1">
					{#if changes.length > 1}
						<b>{changes.length}</b> open notices on {name}, worst is <b>{topPriority}</b>.
					{:else}
						<b>{lead.priority}</b> priority — {anyBroken && lead.priority === 'P0'
							? 'highest priority.'
							: allNiceToHave
								? 'nice-to-have improvement.'
								: 'planned change.'}
					{/if}
				</p>
			</div>
		</div>
		{#each changes as change (change.id)}
			<div class="mt-2 border-t border-border pt-2 text-text">
				<PriorityBadge priority={change.priority} />
				{#if change.condition === 'broken'}<span class="ml-1 text-[10px] font-semibold uppercase tracking-wide text-danger">Broken</span>{/if}
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
		{/each}
	</Popover>
{/if}

<style>
	/* Deliberately quiet: a builder scanning a list of renders should notice it
	   without reading it as a stop sign. The panel is where the alarm lives. */
	.change-marker {
		position: absolute;
		top: 1px;
		right: 1px;
		z-index: 10;
		display: inline-flex;
		align-items: center;
		gap: 0.0625rem;
		border: 1px solid var(--color-border);
		background: color-mix(in srgb, var(--color-surface) 88%, transparent);
		padding: 0 0.125rem;
		color: var(--color-warning-dark);
		line-height: 1.35;
	}
	/* warning-dark is a near-black brown, unreadable on the dark surface, so the
	   dark theme takes the bright warning instead. */
	:global(.dark) .change-marker {
		color: var(--color-warning);
	}
	.change-marker.is-broken {
		border-color: color-mix(in srgb, var(--color-danger) 50%, transparent);
		color: var(--color-danger);
	}
	:global(.dark) .change-marker.is-broken {
		color: #ff6b6c;
	}
	.change-marker:hover {
		border-color: currentColor;
	}
	.change-marker-n {
		font-size: 0.625rem;
		font-weight: 700;
	}
</style>
