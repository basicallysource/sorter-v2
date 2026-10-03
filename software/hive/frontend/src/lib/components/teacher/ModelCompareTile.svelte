<script lang="ts">
	import type { TeacherModelInfo, TeacherPreviewResponse } from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	type RunStatus = 'idle' | 'running' | 'done' | 'error';

	interface Props {
		model: TeacherModelInfo;
		color: string;
		imageUrl: string;
		status: RunStatus;
		result: TeacherPreviewResponse | null;
		error: string | null;
		onRun: () => void;
	}

	let { model, color, imageUrl, status, result, error, onRun }: Props = $props();

	// Each tile owns its own image-size state so the overlay scales correctly regardless
	// of grid breakpoint or how the responsive layout sized this card.
	let imgEl = $state<HTMLImageElement | null>(null);
	let naturalWidth = $state(0);
	let naturalHeight = $state(0);
	let renderedWidth = $state(0);
	let renderedHeight = $state(0);

	function onImgLoad(e: Event) {
		const img = e.currentTarget as HTMLImageElement;
		naturalWidth = img.naturalWidth;
		naturalHeight = img.naturalHeight;
		renderedWidth = img.clientWidth;
		renderedHeight = img.clientHeight;
	}

	function onWindowResize() {
		if (imgEl) {
			renderedWidth = imgEl.clientWidth;
			renderedHeight = imgEl.clientHeight;
		}
	}

	function formatUsd(value: number | null | undefined): string {
		if (value == null) return '-';
		if (value === 0) return '$0.00';
		if (Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
		return `$${value.toFixed(2)}`;
	}

	function formatMs(ms: number | null | undefined): string {
		if (ms == null) return '-';
		if (ms < 1000) return `${ms} ms`;
		return `${(ms / 1000).toFixed(1)} s`;
	}

	function scaledBox(
		bbox: [number, number, number, number],
		refW: number,
		refH: number
	): { left: number; top: number; width: number; height: number } | null {
		if (!naturalWidth || !naturalHeight || !renderedWidth || !renderedHeight) return null;
		const w = refW || naturalWidth;
		const h = refH || naturalHeight;
		const sx = renderedWidth / w;
		const sy = renderedHeight / h;
		return {
			left: bbox[0] * sx,
			top: bbox[1] * sy,
			width: (bbox[2] - bbox[0]) * sx,
			height: (bbox[3] - bbox[1]) * sy
		};
	}
</script>

<svelte:window onresize={onWindowResize} />

<section class="overflow-hidden rounded-panel bg-surface">
	<header class="flex items-center gap-2.5 px-(--pad-panel) py-3">
		<span class="size-3.5 shrink-0 rounded-item" style="background: {color};"></span>
		<div class="min-w-0 flex-1">
			<div class="truncate text-sm font-semibold text-ink">{model.display_name}</div>
			<div class="truncate font-mono text-sm text-ink-muted">{model.model_id}, {model.adapter_kind}</div>
		</div>
		<Button size="sm" loading={status === 'running'} onclick={onRun}
			>{status === 'idle' ? 'Run' : status === 'running' ? 'Running' : 'Run again'}</Button
		>
	</header>

	<div class="relative bg-media">
		<img bind:this={imgEl} src={imageUrl} alt={model.display_name} class="block w-full" onload={onImgLoad} />
		{#if status === 'done' && result && renderedWidth > 0}
			{#each result.bboxes as bbox, bi (bi)}
				{@const box = scaledBox(bbox, result.image_width, result.image_height)}
				{#if box}
					<div
						class="pointer-events-none absolute border-2"
						style="left: {box.left}px; top: {box.top}px; width: {box.width}px; height: {box.height}px; border-color: {color};"
					></div>
				{/if}
			{/each}
		{/if}
		{#if status === 'running'}
			<div class="absolute inset-0 flex items-center justify-center bg-scrim text-white"><Spinner /></div>
		{/if}
	</div>

	{#if status === 'done' && result}
		<dl class="grid grid-cols-4 gap-2 border-t border-line px-(--pad-panel) py-2.5">
			{#each [
				['Boxes', String(result.count)],
				['Top score', result.score > 0 ? result.score.toFixed(2) : '-'],
				['Cost', formatUsd(result.cost_usd)],
				['Time', formatMs(result.elapsed_ms)]
			] as [name, value] (name)}
				<div class="min-w-0">
					<dt class="truncate text-sm text-ink-muted">{name}</dt>
					<dd class="num truncate text-sm font-semibold text-ink">{value}</dd>
				</div>
			{/each}
		</dl>
		{#if result.raw_text || result.raw_annotations}
			<div class="border-t border-line">
				<Disclosure title="The raw response">
					<div class="flex flex-col gap-2 px-(--pad-panel)">
						{#if result.raw_text}
							<pre class="max-h-64 overflow-auto rounded-control bg-well p-3 font-mono text-sm break-all whitespace-pre-wrap text-ink">{result.raw_text}</pre>
						{/if}
						{#if result.raw_annotations}
							<pre class="max-h-64 overflow-auto rounded-control bg-well p-3 font-mono text-sm break-all whitespace-pre-wrap text-ink">{JSON.stringify(result.raw_annotations, null, 2)}</pre>
						{/if}
					</div>
				</Disclosure>
			</div>
		{/if}
	{:else if status === 'error'}
		<div class="border-t border-line p-3"><Alert tone="warning">{error}</Alert></div>
	{:else if model.notes}
		<p class="border-t border-line px-(--pad-panel) py-2.5 text-sm text-ink-muted">{model.notes}</p>
	{/if}
</section>
