<script lang="ts">
	import type { Sample } from '$lib/api';
	import { api } from '$lib/api';

	interface Props {
		sample: Sample;
		href?: string;
	}

	let { sample, href = '#' }: Props = $props();

	let imgNaturalWidth = $state(0);
	let imgNaturalHeight = $state(0);

	const statusConfig: Record<string, { label: string; color: string; bg: string }> = {
		accepted: { label: 'Accepted', color: '#00852B', bg: 'rgba(0,133,43,0.12)' },
		rejected: { label: 'Rejected', color: '#D01012', bg: 'rgba(208,16,18,0.10)' },
		in_review: { label: 'In Review', color: '#0055BF', bg: 'rgba(0,85,191,0.10)' },
		conflict: { label: 'Conflict', color: '#FFD500', bg: 'rgba(255,213,0,0.15)' },
		unreviewed: { label: 'Unreviewed', color: '#FFFFFF', bg: 'rgba(0,0,0,0.45)' }
	};

	const sourceRoleLabels: Record<string, string> = {
		classification_chamber: 'Chamber',
		c_channel_1: 'Channel 1',
		c_channel_2: 'Channel 2',
		c_channel_3: 'Channel 3',
		carousel: 'Carousel',
		top: 'Top',
		bottom: 'Bottom'
	};

	const cfg = $derived(statusConfig[sample.review_status] ?? statusConfig.unreviewed);
	const roleLabel = $derived(sample.source_role ? (sourceRoleLabels[sample.source_role] ?? sample.source_role) : null);
	const score = $derived(sample.detection_score != null ? Math.round(sample.detection_score * 100) : null);
	const bboxes = $derived.by(() => {
		const candidates = (sample.extra_metadata?.detection_candidate_bboxes as number[][] | undefined);
		if (candidates && candidates.length > 0) return candidates;
		return (sample.detection_bboxes as number[][] | null) ?? [];
	});
	const showBboxes = $derived(bboxes.length > 0 && imgNaturalWidth > 0 && imgNaturalHeight > 0);
	const timeAgo = $derived.by(() => {
		const date = sample.captured_at ?? sample.uploaded_at;
		const diff = Date.now() - new Date(date).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 60) return `${mins}m`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h`;
		const days = Math.floor(hrs / 24);
		if (days < 30) return `${days}d`;
		return `${Math.floor(days / 30)}mo`;
	});

	function onImageLoad(e: Event) {
		const img = e.currentTarget as HTMLImageElement;
		imgNaturalWidth = img.naturalWidth;
		imgNaturalHeight = img.naturalHeight;
	}
</script>

<a
	class="group block overflow-hidden border border-border bg-white transition hover:border-text-muted"
	{href}
>
	<!-- Image with overlays -->
	<div class="relative aspect-square overflow-hidden bg-bg">
		<img
			src={api.sampleImageUrl(sample.id)}
			alt="Sample {sample.local_sample_id}"
			class="h-full w-full object-cover transition group-hover:scale-105"
			loading="lazy"
			onload={onImageLoad}
		/>
		<!-- Bbox overlay -->
		{#if showBboxes}
			<svg
				class="pointer-events-none absolute inset-0 h-full w-full transition group-hover:scale-105"
				viewBox="0 0 {imgNaturalWidth} {imgNaturalHeight}"
				preserveAspectRatio="xMidYMid slice"
			>
				{#each bboxes as bbox}
					<rect
						x={bbox[0]}
						y={bbox[1]}
						width={bbox[2] - bbox[0]}
						height={bbox[3] - bbox[1]}
						fill="none"
						stroke="#00852B"
						stroke-width={Math.max(2, Math.round(imgNaturalWidth / 300))}
						opacity="0.8"
					/>
				{/each}
			</svg>
		{/if}
		<!-- Status pill — top left -->
		<span
			class="absolute top-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
			style="color: {cfg.color}; background: {cfg.bg}; backdrop-filter: blur(4px);"
		>
			{cfg.label}
		</span>
		<!-- Detection count — top right -->
		{#if sample.detection_count != null && sample.detection_count > 0}
			<span class="absolute top-1.5 right-1.5 flex h-5 min-w-5 items-center justify-center bg-black/50 px-1 text-[10px] font-bold text-white backdrop-blur-sm">
				{sample.detection_count}
			</span>
		{/if}
	</div>

	<!-- Info row -->
	<div class="flex items-center justify-between px-2.5 py-2">
		<div class="flex items-center gap-1.5 text-[10px] text-text-muted">
			{#if roleLabel}
				<span class="font-medium text-text">{roleLabel}</span>
				<span class="text-border">&middot;</span>
			{/if}
			<span>{timeAgo}</span>
			{#if score !== null}
				<span class="text-border">&middot;</span>
				<span class="{score >= 80 ? 'text-success' : score >= 50 ? 'text-text' : 'text-primary'}">{score}%</span>
			{/if}
		</div>
		{#if sample.review_count > 0}
			<span class="text-[10px] text-text-muted">{sample.review_count}x</span>
		{/if}
	</div>
</a>
