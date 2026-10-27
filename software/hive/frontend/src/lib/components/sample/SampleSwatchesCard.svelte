<script lang="ts">
	import type { SampleSwatchRun } from '$lib/api';
	import { sentence } from '$lib/text';
	import Badge from '$lib/components/Badge.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';

	// The colour reference palette's readings on this frame: one swatch run
	// (the newest by default), whether it calls the palette in view, and the
	// swatches it found in order along the palette.
	let {
		runs,
		selectedId,
		onselect
	}: {
		runs: SampleSwatchRun[];
		selectedId: string | undefined;
		onselect: (id: string) => void;
	} = $props();

	const run = $derived(runs.find((r) => r.id === selectedId) ?? runs[0]);
	const runOptions = $derived(
		runs.map((r) => ({ value: r.id, label: r.model_name, hint: r.created_at ? when(r.created_at) : undefined }))
	);

	function when(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
	}

	function rgb(values: number[]): string {
		return `rgb(${values.map((v) => Math.round(v)).join(' ')})`;
	}

	function triple(values: number[]): string {
		return values.map((v) => Math.round(v)).join(' ');
	}
</script>

{#if run}
	<Panel title="Palette swatches" flush>
		{#snippet actions()}
			{#if runs.length > 1}
				<Select size="sm" label="Swatch model run" value={run.id} options={runOptions} onchange={onselect} />
			{:else}
				<span class="text-sm text-ink-muted">{run.model_name}</span>
			{/if}
		{/snippet}
		<div class="flex flex-col gap-2 px-(--pad-panel) pb-2">
			<div class="flex flex-wrap gap-1.5">
				{#if run.palette_present}
					<Badge tone="success" dot>Palette in view, {run.palette_swatches} swatches</Badge>
				{:else if run.palette_present === false}
					<Badge dot>No palette in view</Badge>
				{:else}
					<Badge>Read before the palette call</Badge>
				{/if}
				{#each run.flags as flag (flag)}<Badge tone="warning">{sentence(flag)}</Badge>{/each}
			</div>
			<p class="num text-sm text-ink-muted">
				{run.swatch_count} found in {run.seconds.toFixed(2)} s, {when(run.created_at)}
			</p>
		</div>
		{#if run.swatches.length}
			<ul class="divide-y divide-line border-t border-line">
				{#each run.swatches as s (s.position)}
					<li
						class="flex items-start gap-2.5 px-(--pad-panel) py-2 text-sm {s.in_palette === false ? 'opacity-60' : ''}"
						title={`Colour score ${s.colour_score.toFixed(2)}, top face ${s.surface_score.toFixed(2)}, ${Math.round(s.length)} x ${Math.round(s.width)} px, ${(s.clipped * 100).toFixed(0)}% clipped`}
					>
						<span class="num w-5 shrink-0 text-ink-muted">{s.position}</span>
						<!-- The colour the tile reads as: data, so an inline value. -->
						<span class="mt-0.5 size-4 shrink-0 rounded-item" style:background-color={rgb(s.rgb)}></span>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
								<span class="text-ink">{s.colour}</span>
								{#if s.bricklink_color_id != null}<span class="num text-xs text-ink-muted">BL {s.bricklink_color_id}</span>{/if}
								{#if s.in_palette === false}<Badge>Not in the palette</Badge>{/if}
								{#each s.flags as flag (flag)}<Badge tone="warning">{sentence(flag)}</Badge>{/each}
							</div>
							<div class="num font-mono text-sm text-ink-muted">
								{triple(s.rgb)} &plusmn; {triple(s.rgb_std)}, {s.pixels.toLocaleString('en-US')} px
							</div>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	</Panel>
{/if}
