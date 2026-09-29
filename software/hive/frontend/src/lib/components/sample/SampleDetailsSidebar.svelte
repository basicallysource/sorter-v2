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

<div class="border border-line bg-surface">
	<div class="border-b border-line px-4 py-2.5">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Details</h2>
	</div>
	<div class="divide-y divide-line">
		{#if sample.machine}
			{@const machine = sample.machine}
			{@const owner = machine.owner}
			{@const machineHref = `/samples?scope=all&machine_id=${machine.id}`}
			<div class="flex items-center justify-between gap-3 px-4 py-2">
				<span class="text-xs text-ink-muted">Machine</span>
				<a
					href={machineHref}
					class="flex min-w-0 items-center gap-1.5 text-xs font-medium text-primary-ink hover:underline"
					title={owner?.display_name ? `${owner.display_name} / ${machine.name}` : machine.name}
				>
					{#if owner?.avatar_url}
						<img src={owner.avatar_url} alt="" class="h-4 w-4 shrink-0 rounded-full" />
					{/if}
					<span class="min-w-0 truncate">
						{#if owner?.display_name}<span class="text-ink-muted">{owner.display_name} /</span> {/if}{machine.name}
					</span>
				</a>
			</div>
		{/if}
		{#if sample.source_role}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-ink-muted">Source</span>
				<span class="text-xs font-medium text-ink">{sample.source_role}</span>
			</div>
		{/if}
		{#if sample.capture_reason}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-ink-muted">Reason</span>
				<span class="text-xs font-medium text-ink">{sample.capture_reason}</span>
			</div>
		{/if}
		{#if camera}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-ink-muted">Camera</span>
				<span class="text-xs font-medium text-ink">{camera}</span>
			</div>
		{/if}
		{#if detectionScope}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-ink-muted">Scope</span>
				<span class="text-xs font-medium text-ink">{detectionScope}</span>
			</div>
		{/if}
		{#if sample.captured_at}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-ink-muted">Captured</span>
				<span class="text-xs text-ink">{formatDate(sample.captured_at)}</span>
			</div>
		{/if}
		<div class="flex items-center justify-between px-4 py-2">
			<span class="text-xs text-ink-muted">Uploaded</span>
			<span class="text-xs text-ink">{formatDate(sample.uploaded_at)}</span>
		</div>
		{#if sample.image_width && sample.image_height}
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-ink-muted">Size</span>
				<span class="text-xs text-ink">{sample.image_width}&times;{sample.image_height}</span>
			</div>
		{/if}
	</div>
</div>

{#if pieceUuid || runId}
	<div class="border border-line bg-surface">
		<div class="border-b border-line px-4 py-2.5">
			<h2 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">IDs</h2>
		</div>
		<div class="divide-y divide-line">
			<div class="flex items-center justify-between px-4 py-2">
				<span class="text-xs text-ink-muted">Sample</span>
				<span class="text-xs font-mono text-ink-muted truncate ml-3 max-w-[200px]" title={sample.local_sample_id}>{sample.local_sample_id}</span>
			</div>
			{#if pieceUuid}
				<div class="flex items-center justify-between px-4 py-2">
					<span class="text-xs text-ink-muted">Piece</span>
					<span class="text-xs font-mono text-ink-muted truncate ml-3 max-w-[200px]" title={pieceUuid}>{shortId(pieceUuid)}</span>
				</div>
			{/if}
			{#if runId}
				<div class="flex items-center justify-between px-4 py-2">
					<span class="text-xs text-ink-muted">Run</span>
					<span class="text-xs font-mono text-ink-muted truncate ml-3 max-w-[200px]" title={runId}>{shortId(runId)}</span>
				</div>
			{/if}
		</div>
	</div>
{/if}

{#if extraKeys.length > 0}
	<div class="border border-line bg-surface">
		<button
			onclick={onToggleExpandedMeta}
			class="flex w-full items-center justify-between px-4 py-2.5"
		>
			<h2 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Metadata ({extraKeys.length})</h2>
			<svg class="h-3.5 w-3.5 text-ink-muted transition-transform {showExpandedMeta ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		</button>
		{#if showExpandedMeta}
			<div class="border-t border-line divide-y divide-line">
				{#each extraKeys as key}
					<div class="flex items-start justify-between gap-3 px-4 py-2">
						<span class="text-xs font-mono text-ink-muted shrink-0">{key}</span>
						<span class="text-xs text-ink text-right break-all">{formatValue(extra[key])}</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<div class="border border-line bg-surface">
	<div class="border-b border-line px-4 py-2.5">
		<h2 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Reviews</h2>
	</div>
	{#if reviews.length === 0}
		<div class="px-4 py-4 text-center">
			<p class="text-xs text-ink-muted">No reviews yet</p>
		</div>
	{:else}
		<div class="divide-y divide-line">
			{#each reviews as review (review.id)}
				<div class="px-4 py-2.5">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							<div class="flex h-5 w-5 items-center justify-center text-xs font-bold {review.decision === 'accept' ? 'bg-success/[0.08] text-success-ink' : 'bg-primary-soft text-primary-ink'}">
								{review.decision === 'accept' ? '✓' : '✗'}
							</div>
							<span class="text-xs font-medium text-ink">{review.reviewer_display_name ?? 'Unknown'}</span>
						</div>
						<span class="text-xs text-ink-muted">{formatDate(review.created_at)}</span>
					</div>
					{#if review.notes}
						<p class="mt-1 ml-7 text-xs text-ink-muted">{review.notes}</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
