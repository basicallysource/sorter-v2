<script lang="ts">
	import Panel from '$lib/components/ui/Panel.svelte';
	import FrameStrip from './FrameStrip.svelte';
	import type { Frame } from './types';

	// Every picture of a piece, in the left column of its page: a section for
	// each channel, the classification channel's first, then the views of the
	// same piece found on C3 and on C2. Four tiles to a row, as many rows as a
	// channel has pictures for. The ones that produced the result have a stroke
	// around them. A click opens the picture full size.
	let {
		frames,
		note,
		onZoom
	}: {
		frames: Frame[];
		// One sentence under the title: how many, and from where.
		note: string;
		onZoom: (src: string, label: string) => void;
	} = $props();

	const COLS = 4;
	const CHANNELS = [
		{ channel: 'C4', name: 'Classification channel', none: 'No pictures.' },
		{ channel: 'C3', name: 'C-channel 3', none: 'No pictures linked to this piece here.' },
		{ channel: 'C2', name: 'C-channel 2', none: 'No pictures linked to this piece here.' },
		{ channel: '—', name: 'Channel not recorded', none: '' }
	];

	const sections = $derived(
		CHANNELS.map((c) => ({ ...c, frames: frames.filter((f) => f.channel === c.channel) })).filter(
			(s) => s.frames.length > 0 || s.channel !== '—'
		)
	);

	function firstAt(of: Frame[]): string {
		const ts = of.find((f) => f.ts != null)?.ts;
		if (ts == null) return '';
		return new Date(ts * 1000).toLocaleTimeString(undefined, {
			hour: 'numeric',
			minute: '2-digit',
			second: '2-digit'
		});
	}
</script>

<Panel title="Pictures" description={note}>
	{#if frames.length === 0}
		<p class="text-sm text-ink-muted">No pictures of this piece.</p>
	{:else}
		<div class="flex flex-col gap-4">
			{#each sections as section (section.channel)}
				<section class="flex flex-col gap-1.5">
					<div class="flex items-baseline justify-between gap-2">
						<span class="flex min-w-0 items-baseline gap-2">
							{#if section.channel !== '—'}
								<span class="font-mono text-sm text-ink">{section.channel}</span>
							{/if}
							<span class="truncate text-xs text-ink-muted">{section.name}</span>
						</span>
						<span class="num shrink-0 text-xs text-ink-muted">{firstAt(section.frames)}</span>
					</div>
					{#if section.frames.length === 0}
						<p class="text-sm text-ink-faint">{section.none}</p>
					{:else}
						<FrameStrip
							frames={section.frames}
							size={4.75}
							cols={COLS}
							rows={Math.ceil(section.frames.length / COLS)}
							{onZoom}
						/>
					{/if}
				</section>
			{/each}
		</div>
	{/if}
</Panel>
