<!--
	The color reference palette for one piece, on one line: its machine's
	classification frame with the palette in view nearest the piece, small
	(hover for the whole frame with the swatches boxed, click for its sample
	page in a new tab), the palette's swatches as read in that frame (each the
	color the camera saw, over a band of the color the tile is), and how far
	the frame is from the piece. Each swatch's numbers are in its tooltip, and
	all of them behind the info button.
-->
<script lang="ts">
	import { api, type BrickLinkColor, type PiecePalette, type SampleSwatch } from '$lib/api';
	import { formatDateTime } from '$lib/time';
	import Button from '$lib/components/Button.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import ZoomImage from '$lib/components/ZoomImage.svelte';
	import SwatchOverlay from '$lib/components/sample/SwatchOverlay.svelte';
	import Info from '@lucide/svelte/icons/info';
	import SwatchBook from '@lucide/svelte/icons/swatch-book';

	let { palette, colors }: { palette: PiecePalette; colors: Map<number, BrickLinkColor> } = $props();

	const frame = $derived(palette.frame);
	// The palette's own tiles, not a loose piece's top that read as one.
	const tiles = $derived(frame ? frame.run.swatches.filter((s) => s.in_palette !== false) : []);
	const src = $derived(frame ? (frame.full_frame_url ?? api.sampleFullFrameUrl(frame.sample_id)) : '');
	const aspect = $derived(frame ? frame.run.frame_width / frame.run.frame_height : 16 / 9);

	// What the camera saw: data, so an inline value.
	function seen(values: number[]): string {
		return `rgb(${values.map((v) => Math.round(v)).join(' ')})`;
	}

	function triple(values: number[]): string {
		return values.map((v) => Math.round(v)).join(' ');
	}

	// The color the tile is, from the BrickLink palette.
	function truth(s: SampleSwatch): string | undefined {
		const rgb = s.bricklink_color_id != null ? colors.get(s.bricklink_color_id)?.rgb : null;
		return rgb ? `#${rgb}` : undefined;
	}

	function reading(s: SampleSwatch): string {
		const parts = [
			`${s.colour}${s.bricklink_color_id != null ? ` (${s.bricklink_color_id})` : ''}`,
			`reads ${triple(s.rgb)} ± ${triple(s.rgb_std)}`,
			`${s.pixels.toLocaleString()} px`
		];
		if (s.clipped > 0) parts.push(`${Math.round(s.clipped * 100)}% clipped`);
		if (s.flags.length) parts.push(s.flags.join(', ').replaceAll('_', ' '));
		return parts.join(', ');
	}

	// "12 min before the piece", "1 h 40 min after".
	function apart(seconds: number): string {
		const minutes = Math.round(Math.abs(seconds) / 60);
		if (minutes === 0) return 'the same minute as the piece';
		const hours = Math.floor(minutes / 60);
		const rest = minutes % 60;
		const span = hours === 0 ? `${minutes} min` : rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
		return `${span} ${seconds < 0 ? 'before' : 'after'} the piece`;
	}
</script>

{#snippet chip(s: SampleSwatch, size: string)}
	<span aria-hidden="true" class="flex shrink-0 flex-col overflow-hidden rounded-check border border-line-strong {size}">
		<span class="flex-1" style:background-color={seen(s.rgb)}></span>
		<span class="h-1/4" style:background-color={truth(s)}></span>
	</span>
{/snippet}

<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
	<span class="flex items-center gap-1.5 text-sm text-ink-muted"><SwatchBook size={14} />Palette</span>
	{#if frame}
		<a href={`/samples/${frame.sample_id}`} target="_blank" rel="noopener" class="shrink-0 rounded-item" title="The frame's sample, in a new tab">
			<ZoomImage
				{src}
				alt="The frame the palette was read in"
				class="h-12 rounded-item bg-media object-cover"
				zoom={720}
				{aspect}
			>
				{#snippet overlay()}<SwatchOverlay run={frame.run} />{/snippet}
			</ZoomImage>
		</a>
		<div class="flex flex-wrap gap-1">
			{#each tiles as s (s.position)}
				<span class="flex" title={reading(s)}>{@render chip(s, 'size-7')}</span>
			{/each}
		</div>
		<span class="num text-xs text-ink-muted" title={formatDateTime(frame.frame_at)}>{apart(frame.offset_s)}</span>
		<Popover label="The palette's readings" width="22rem" placement="bottom-end">
			{#snippet trigger(props)}
				<Button {...props} size="sm" variant="ghost" icon={Info} label="The palette's readings" />
			{/snippet}
			<div class="label mb-1">What the camera read</div>
			<div class="flex flex-col divide-y divide-line">
				{#each frame.run.swatches as s (s.position)}
					<div class="flex items-center gap-2 py-1.5 text-sm {s.in_palette === false ? 'opacity-60' : ''}" title={reading(s)}>
						{@render chip(s, 'size-4')}
						<span class="min-w-0 flex-1 truncate text-ink">{s.colour}</span>
						<span class="num font-mono text-ink-muted">{triple(s.rgb)} ± {triple(s.rgb_std)}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-sm text-ink-muted">
				{frame.run.model_name}, {formatDateTime(frame.frame_at)}{frame.run.flags.length
					? `, ${frame.run.flags.join(', ').replaceAll('_', ' ')}`
					: ''}
			</p>
		</Popover>
	{:else}
		<span class="text-sm text-ink-muted">Not in view within {Math.round(palette.window_s / 3600)} hours of the piece</span>
	{/if}
</div>
