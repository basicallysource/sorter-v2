<script lang="ts">
	import DetailPanes from '$lib/components/DetailPanes.svelte';
	import StlViewer from '$lib/components/StlViewer.svelte';
	import DownloadButton from '$lib/components/DownloadButton.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import { fmtDate } from '$lib/filament';
	import type { LaserCutPart } from '$lib/lasercut';
	import { ExternalLink } from 'lucide-svelte';

	// The laser-cut part detail view: the solid model (or the DXF outline when
	// none is published), then the facts, the downloads and the source link —
	// the same one-thing-one-view treatment printed parts and hardware get.
	let { part }: { part: LaserCutPart } = $props();

	let view3d = $state(true);
	$effect(() => {
		part.id;
		view3d = true;
	});
</script>

<DetailPanes>
	{#snippet visual()}
	{#if part.stl && view3d}
		<StlViewer url={part.stl} color="#b08d57" heightClass="h-[45vh] lg:h-[76vh]" />
	{:else}
		<div class="flex h-[45vh] items-center justify-center bg-[var(--color-bg)] p-6 lg:h-[76vh]">
			<img src={part.preview} alt="{part.name} outline" class="max-h-full w-auto max-w-full" />
		</div>
	{/if}
	{#if part.stl}
		<button
			type="button"
			class="absolute left-3 top-3 border border-border bg-surface px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted hover:text-text"
			onclick={() => (view3d = !view3d)}
		>
			{view3d ? 'Outline' : '3D'}
		</button>
	{/if}
	{/snippet}

	{#snippet facts()}
	<div class="px-5 py-4">
	<div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
		<div class="min-w-0 flex-1 space-y-2 text-sm">
			<p class="text-text">{part.description}</p>
			<ChangeStatus kind="lasercut" id={part.id} name={part.name} />
		</div>
		<div class="flex shrink-0 flex-col items-start gap-2 sm:items-end">
			<DownloadButton href={part.dxf} size="md" label="Download DXF" />
			{#if part.stl}
				<DownloadButton href={part.stl} size="sm" label="STL" title="The solid model — for viewing or CAM, not for printing" />
			{/if}
			<a
				href={part.onshape}
				target="_blank"
				rel="noopener"
				class="inline-flex items-center gap-0.5 text-xs text-primary hover:text-primary-hover"
				title="Open the pinned OnShape version">OnShape <ExternalLink size={11} /></a>
		</div>
	</div>

	{#snippet tile(label: string, value: string)}
		<div class="border border-border bg-[var(--color-bg)] px-3 py-2">
			<dt class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">{label}</dt>
			<dd class="mt-0.5 text-sm font-medium text-text">{value}</dd>
		</div>
	{/snippet}
	<dl class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
		{@render tile('Material', `${part.thicknessIn} plywood (${part.thicknessMm} mm)`)}
		{@render tile('Cut size', `${part.widthMm} × ${part.heightMm} mm`)}
		{@render tile('Needed', `×${part.qty} per machine`)}
		{@render tile('Updated', fmtDate(part.updated))}
	</dl>

	{#if part.handcut}
		<p class="mt-3 text-xs text-text-muted">
			No laser? This one can be laid out and cut by hand ({part.handcut.tools}) — the guide is on the
			<a class="text-primary hover:text-primary-hover" href="/lasercut#laser-{part.id}">Laser cut parts</a> page.
		</p>
	{/if}
	</div>
	{/snippet}
</DetailPanes>
