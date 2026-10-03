<script lang="ts">
	import type { SampleDetail, SampleReview } from '$lib/api';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';

	interface Props {
		sample: SampleDetail;
		reviews: SampleReview[];
		camera: string | undefined;
		detectionScope: string | undefined;
		pieceUuid: string | undefined;
		runId: string | undefined;
		extra: Record<string, unknown>;
		extraKeys: string[];
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
		formatValue,
		formatDate,
		shortId
	}: Props = $props();
</script>

<Panel title="Details" flush>
	<div class="divide-y divide-line px-(--pad-panel) pb-2">
		{#if sample.machine}
			{@const machine = sample.machine}
			{@const owner = machine.owner}
			<div class="flex items-center justify-between gap-6 py-2.5">
				<span class="shrink-0 text-sm text-ink-muted">Machine</span>
				<a
					href={`/samples?scope=all&machine_id=${machine.id}`}
					class="flex min-w-0 items-center gap-1.5 text-sm font-medium text-primary-ink hover:underline"
					title={owner?.display_name ? `${owner.display_name}, ${machine.name}` : machine.name}
				>
					{#if owner?.avatar_url}<img src={owner.avatar_url} alt="" class="size-4 shrink-0 rounded-full" />{/if}
					<span class="min-w-0 truncate">{#if owner?.display_name}<span class="text-ink-muted">{`${owner.display_name}, `}</span>{/if}{machine.name}</span>
				</a>
			</div>
		{/if}
		<KeyValue
			items={[
				...(sample.source_role ? [{ label: 'Source', value: sample.source_role, mono: true }] : []),
				...(sample.capture_reason ? [{ label: 'Reason', value: sample.capture_reason, mono: true }] : []),
				...(camera ? [{ label: 'Camera', value: camera }] : []),
				...(detectionScope ? [{ label: 'Scope', value: detectionScope }] : []),
				...(sample.captured_at ? [{ label: 'Captured', value: formatDate(sample.captured_at) }] : []),
				{ label: 'Uploaded', value: formatDate(sample.uploaded_at) },
				...(sample.image_width && sample.image_height ? [{ label: 'Size', value: `${sample.image_width} by ${sample.image_height}` }] : [])
			]}
		/>
	</div>
</Panel>

{#if pieceUuid || runId}
	<Panel title="IDs" flush>
		<div class="px-(--pad-panel) pb-2">
			<KeyValue
				items={[
					{ label: 'Sample', value: sample.local_sample_id, mono: true },
					...(pieceUuid ? [{ label: 'Piece', value: shortId(pieceUuid), mono: true }] : []),
					...(runId ? [{ label: 'Run', value: shortId(runId), mono: true }] : [])
				]}
			/>
		</div>
	</Panel>
{/if}

{#if extraKeys.length > 0}
	<Panel flush>
		<Disclosure title="Metadata" help={`${extraKeys.length} fields`}>
			<dl class="divide-y divide-line px-(--pad-panel)">
				{#each extraKeys as key (key)}
					<div class="flex items-start justify-between gap-3 py-2">
						<dt class="shrink-0 font-mono text-sm text-ink-muted">{key}</dt>
						<dd class="min-w-0 text-right text-sm break-all text-ink">{formatValue(extra[key])}</dd>
					</div>
				{/each}
			</dl>
		</Disclosure>
	</Panel>
{/if}

<Panel title="Reviews" flush>
	{#if reviews.length === 0}
		<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">No reviews yet.</p>
	{:else}
		<ul class="divide-y divide-line border-t border-line">
			{#each reviews as review (review.id)}
				{@const accepted = review.decision === 'accept'}
				<li class="px-(--pad-panel) py-2.5">
					<div class="flex items-center gap-2">
						<span
							class="flex size-5 shrink-0 items-center justify-center rounded-item {accepted
								? 'bg-success-soft text-success-ink'
								: 'bg-danger-soft text-danger-ink'}"
							title={accepted ? 'Accepted' : 'Rejected'}
						>
							{#if accepted}<Check size={14} />{:else}<X size={14} />{/if}
						</span>
						<span class="min-w-0 flex-1 truncate text-sm font-medium text-ink">{review.reviewer_display_name ?? 'Unknown'}</span>
						<span class="num shrink-0 text-sm text-ink-muted">{formatDate(review.created_at)}</span>
					</div>
					{#if review.notes}<p class="mt-1 ml-7 text-sm text-ink-muted">{review.notes}</p>{/if}
				</li>
			{/each}
		</ul>
	{/if}
</Panel>
