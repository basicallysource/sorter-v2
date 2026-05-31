<script lang="ts">
	import type { TeacherModelInfo, TeacherPreviewResponse } from '$lib/api';
	import { Button } from '$lib/components/primitives';

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
		if (value == null) return '—';
		if (value === 0) return '$0.00';
		if (Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
		return `$${value.toFixed(2)}`;
	}

	function formatMs(ms: number | null | undefined): string {
		if (ms == null) return '—';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
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

<div class="border border-border bg-surface">
	<div class="flex items-center gap-2 border-b border-border px-3 py-2">
		<span class="h-4 w-4 shrink-0 border border-border" style="background: {color};"></span>
		<div class="min-w-0 flex-1">
			<div class="truncate text-sm font-semibold text-text">{model.display_name}</div>
			<div class="truncate font-mono text-[10px] text-text-muted">
				{model.model_id}
				<span class="ml-1">[{model.adapter_kind}]</span>
			</div>
		</div>
		<Button variant="secondary" size="sm" loading={status === 'running'} onclick={onRun}>
			{status === 'idle' ? 'Run' : status === 'running' ? 'Running…' : 'Re-run'}
		</Button>
	</div>

	<div class="relative bg-bg">
		<img
			bind:this={imgEl}
			src={imageUrl}
			alt={model.display_name}
			class="block w-full"
			onload={onImgLoad}
		/>
		{#if status === 'done' && result && renderedWidth > 0}
			{@const refW = result.image_width}
			{@const refH = result.image_height}
			{#each result.bboxes as bbox, bi (bi)}
				{@const box = scaledBox(bbox, refW, refH)}
				{#if box}
					<div
						class="pointer-events-none absolute border-2"
						style="left: {box.left}px; top: {box.top}px; width: {box.width}px; height: {box.height}px; border-color: {color};"
					></div>
				{/if}
			{/each}
		{/if}
		{#if status === 'running'}
			<div class="absolute inset-0 flex items-center justify-center bg-surface/60">
				<div class="text-xs text-text-muted">Running…</div>
			</div>
		{/if}
	</div>

	{#if status === 'done' && result}
		<div class="grid grid-cols-4 gap-2 border-t border-border px-3 py-2 text-[11px]">
			<div>
				<div class="text-text-muted">Boxes</div>
				<div class="tabular-nums font-semibold text-text">{result.count}</div>
			</div>
			<div>
				<div class="text-text-muted">Top score</div>
				<div class="tabular-nums font-semibold text-text">
					{result.score > 0 ? result.score.toFixed(2) : '—'}
				</div>
			</div>
			<div>
				<div class="text-text-muted">Cost</div>
				<div class="tabular-nums font-semibold text-text">{formatUsd(result.cost_usd)}</div>
			</div>
			<div>
				<div class="text-text-muted">Latency</div>
				<div class="tabular-nums font-semibold text-text">{formatMs(result.elapsed_ms)}</div>
			</div>
		</div>
		{#if result.raw_text || result.raw_annotations}
			<details class="border-t border-border">
				<summary class="cursor-pointer px-3 py-1.5 text-[11px] text-text-muted hover:text-text">
					Show raw response
				</summary>
				{#if result.raw_text}
					<pre class="max-h-64 overflow-auto border-t border-border bg-bg px-3 py-2 font-mono text-[10px] leading-relaxed text-text whitespace-pre-wrap break-all">{result.raw_text}</pre>
				{/if}
				{#if result.raw_annotations}
					<pre class="max-h-64 overflow-auto border-t border-border bg-bg px-3 py-2 font-mono text-[10px] leading-relaxed text-text whitespace-pre-wrap break-all">{JSON.stringify(result.raw_annotations, null, 2)}</pre>
				{/if}
			</details>
		{/if}
	{:else if status === 'error'}
		<div class="border-t border-border bg-warning-bg px-3 py-2 text-[11px] text-warning-strong">
			{error}
		</div>
	{:else if model.notes}
		<div class="border-t border-border px-3 py-2 text-[11px] text-text-muted">
			{model.notes}
		</div>
	{/if}
</div>
