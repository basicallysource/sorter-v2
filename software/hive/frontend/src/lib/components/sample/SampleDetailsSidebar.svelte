<script lang="ts">
	import type { SampleDetail, SampleReview } from '$lib/api';

	interface Props {
		sample: SampleDetail;
		reviews: SampleReview[];
		camera: string | undefined;
		detectionScope: string | undefined;
		pieceUuid: string | undefined;
		runId: string | undefined;
		extra: Record<string, unknown>;
		extraKeys: string[];
		showExpandedMeta: boolean;
		onToggleExpandedMeta: () => void;
		formatValue: (val: unknown) => string;
		formatDate: (d: string) => string;
		shortId: (id: string) => string;
	}

	let {
		sample,
		reviews,
		camera,
		detectionScope,
		pieceUuid,
		runId,
		extra,
		extraKeys,
		showExpandedMeta,
		onToggleExpandedMeta,
		formatValue,
		formatDate,
		shortId
	}: Props = $props();
</script>

<div class="border border-border bg-white">
	<div class="border-b border-border px-4 py-2.5">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Details</h2>
	</div>
	<div class="divide-y divide-border">
		{#if sample.source_role}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-text-muted">Source</span>
				<span class="text-xs font-medium text-text">{sample.source_role}</span>
			</div>
		{/if}
		{#if sample.capture_reason}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-text-muted">Reason</span>
				<span class="text-xs font-medium text-text">{sample.capture_reason}</span>
			</div>
		{/if}
		{#if camera}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-text-muted">Camera</span>
				<span class="text-xs font-medium text-text">{camera}</span>
			</div>
		{/if}
		{#if detectionScope}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-text-muted">Scope</span>
				<span class="text-xs font-medium text-text">{detectionScope}</span>
			</div>
		{/if}
		{#if sample.captured_at}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-text-muted">Captured</span>
				<span class="text-xs text-text">{formatDate(sample.captured_at)}</span>
			</div>
		{/if}
		<div class="flex items-center justify-between px-4 py-2">
			<span class="text-xs text-text-muted">Uploaded</span>
			<span class="text-xs text-text">{formatDate(sample.uploaded_at)}</span>
		</div>
		{#if sample.image_width && sample.image_height}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-text-muted">Size</span>
				<span class="text-xs text-text">{sample.image_width}&times;{sample.image_height}</span>
			</div>
		{/if}
	</div>
</div>

{#if pieceUuid || runId}
	<div class="border border-border bg-white">
		<div class="border-b border-border px-4 py-2.5">
			<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">IDs</h2>
		</div>
		<div class="divide-y divide-border">
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-text-muted">Sample</span>
				<span class="text-[11px] font-mono text-text-muted truncate ml-3 max-w-[200px]" title={sample.local_sample_id}>{sample.local_sample_id}</span>
			</div>
			{#if pieceUuid}
				<div class="flex items-center justify-between px-4 py-2">
					<span class="text-xs text-text-muted">Piece</span>
					<span class="text-[11px] font-mono text-text-muted truncate ml-3 max-w-[200px]" title={pieceUuid}>{shortId(pieceUuid)}</span>
				</div>
			{/if}
			{#if runId}
				<div class="flex items-center justify-between px-4 py-2">
					<span class="text-xs text-text-muted">Run</span>
					<span class="text-[11px] font-mono text-text-muted truncate ml-3 max-w-[200px]" title={runId}>{shortId(runId)}</span>
				</div>
			{/if}
		</div>
	</div>
{/if}

{#if extraKeys.length > 0}
	<div class="border border-border bg-white">
		<button
			onclick={onToggleExpandedMeta}
			class="flex w-full items-center justify-between px-4 py-2.5"
		>
			<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Metadata ({extraKeys.length})</h2>
			<svg class="h-3.5 w-3.5 text-text-muted transition-transform {showExpandedMeta ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		</button>
		{#if showExpandedMeta}
			<div class="border-t border-border divide-y divide-border">
				{#each extraKeys as key}
					<div class="flex items-start justify-between gap-3 px-4 py-2">
						<span class="text-[11px] font-mono text-text-muted shrink-0">{key}</span>
						<span class="text-[11px] text-text text-right break-all">{formatValue(extra[key])}</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<div class="border border-border bg-white">
	<div class="border-b border-border px-4 py-2.5">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Reviews</h2>
	</div>
	{#if reviews.length === 0}
		<div class="px-4 py-4 text-center">
			<p class="text-xs text-text-muted">No reviews yet</p>
		</div>
	{:else}
		<div class="divide-y divide-border">
			{#each reviews as review (review.id)}
				<div class="px-4 py-2.5">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							<div class="flex h-5 w-5 items-center justify-center text-[10px] font-bold {review.decision === 'accept' ? 'bg-[#F0F9F5] text-success' : 'bg-primary-light text-primary'}">
								{review.decision === 'accept' ? '✓' : '✗'}
							</div>
							<span class="text-xs font-medium text-text">{review.reviewer_display_name ?? 'Unknown'}</span>
						</div>
						<span class="text-[11px] text-text-muted">{formatDate(review.created_at)}</span>
					</div>
					{#if review.notes}
						<p class="mt-1 ml-7 text-xs text-text-muted">{review.notes}</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
