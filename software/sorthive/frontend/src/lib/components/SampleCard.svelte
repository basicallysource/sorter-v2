<script lang="ts">
	import type { Sample } from '$lib/api';
	import { api } from '$lib/api';
	import Badge from './Badge.svelte';

	interface Props {
		sample: Sample;
		href?: string;
	}

	let { sample, href = '#' }: Props = $props();

	const statusVariant: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
		unreviewed: 'neutral',
		in_review: 'info',
		accepted: 'success',
		rejected: 'danger',
		conflict: 'warning'
	};

	const statusBorder: Record<string, string> = {
		accepted: 'border-t-green-400',
		rejected: 'border-t-red-400',
		in_review: 'border-t-blue-400',
		conflict: 'border-t-yellow-400',
		unreviewed: 'border-t-gray-200'
	};
</script>

<a
	class="group block cursor-pointer overflow-hidden rounded-lg border border-gray-200 border-t-2 {statusBorder[sample.review_status] ?? 'border-t-gray-200'} bg-white text-left shadow-sm transition hover:shadow-md"
	{href}
>
	<div class="aspect-square overflow-hidden bg-gray-100">
		<img
			src={api.sampleImageUrl(sample.id)}
			alt="Sample {sample.local_sample_id}"
			class="h-full w-full object-cover transition group-hover:scale-105"
			loading="lazy"
		/>
	</div>
	<div class="p-3">
		<div class="mb-2 flex flex-wrap gap-1">
			<Badge text={sample.review_status} variant={statusVariant[sample.review_status] ?? 'neutral'} />
			{#if sample.source_role}
				<Badge text={sample.source_role} variant="info" />
			{/if}
		</div>
		<p class="text-xs text-gray-500">
			{new Date(sample.uploaded_at).toLocaleDateString()}
		</p>
	</div>
</a>
