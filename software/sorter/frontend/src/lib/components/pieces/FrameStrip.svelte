<script lang="ts">
	import FrameTile from './FrameTile.svelte';
	import type { Frame } from './types';

	// Every picture of a piece, from every channel, in one row that wraps: the
	// frames the classification channel took and the views of the same piece
	// found on the channels before it. A picture that produced the result has a
	// stroke around it. Each is enlarged under the pointer, where its time, its
	// probability and its sharpness are said.
	//
	// `md` (the piece's page): each picture names its channel in its corner and
	// opens the full-size viewer when clicked. `sm` (a row of the records list):
	// small, the pictures of one channel together behind the channel's name.
	let {
		frames,
		size = 'md',
		onZoom
	}: {
		frames: Frame[];
		size?: 'sm' | 'md';
		onZoom?: (src: string, label: string) => void;
	} = $props();

	// The channels in the order their first picture comes.
	const groups = $derived.by(() => {
		const out: { channel: string; frames: Frame[] }[] = [];
		for (const frame of frames) {
			const group = out.find((g) => g.channel === frame.channel);
			if (group) group.frames.push(frame);
			else out.push({ channel: frame.channel, frames: [frame] });
		}
		return out;
	});
</script>

{#if size === 'sm'}
	<span class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
		{#each groups as group (group.channel)}
			<span class="flex flex-wrap items-center gap-1.5">
				<span class="w-5 shrink-0 font-mono text-xs text-ink-muted">{group.channel}</span>
				{#each group.frames as frame (frame.key)}
					<FrameTile {frame} {size} {onZoom} />
				{/each}
			</span>
		{/each}
	</span>
{:else}
	<div class="flex flex-wrap gap-1.5">
		{#each frames as frame (frame.key)}
			<FrameTile {frame} {size} {onZoom} />
		{/each}
	</div>
{/if}
