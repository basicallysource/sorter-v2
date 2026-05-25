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
		in_review: { label: 'Needs more reviews', color: '#0055BF', bg: 'rgba(0,85,191,0.10)' },
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
	// True when the Hive teacher (Gemini/Perceptron) hasn't re-processed
	// the sample yet — boxes are likely raw sorter detections that aren't
	// training-ready. Surface a badge so reviewers can spot them at a
	// glance and skip them via the Annotation sidebar filter.
	const isRaw = $derived(!sample.extra_metadata || !('teacher_rerun' in sample.extra_metadata));

	// Mirror ExposureStats.classify on the backend so the badge stays in
	// sync with the sidebar filter. Null stats (older un-backfilled rows)
	// produce no badge at all rather than guessing. Thresholds match
	// app/services/image_stats.py — keep both ends in sync.
	const exposureLabel = $derived.by<'underexposed' | 'overexposed' | null>(() => {
		const mean = sample.luminance_mean;
		const low = sample.clipped_low_ratio;
		const high = sample.clipped_high_ratio;
		if (mean === null && low === null && high === null) return null;
		if ((mean !== null && mean <= 120) || (low !== null && low >= 0.7)) return 'underexposed';
		if ((mean !== null && mean >= 240) || (high !== null && high >= 0.6)) return 'overexposed';
		return null;
	});
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
	class="group block overflow-hidden border border-border bg-surface transition hover:border-text-muted"
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
		<!-- Status pill — top left. Global consensus state. -->
		<span
			class="absolute top-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
			style="color: {cfg.color}; background: {cfg.bg}; backdrop-filter: blur(4px);"
		>
			{cfg.label}
		</span>
		<!-- Personal decision badge — adjacent to the global pill so you can
		     see at a glance whether you've already voted on this sample. -->
		{#if sample.my_review_decision}
			<span
				class="absolute top-1.5 left-1.5 mt-5 flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
				style="color: #FFFFFF; background: {sample.my_review_decision === 'accept' ? 'rgba(0,133,43,0.85)' : 'rgba(208,16,18,0.85)'}; backdrop-filter: blur(4px);"
				title={sample.my_review_decision === 'accept' ? 'You accepted this' : 'You rejected this'}
			>
				You: {sample.my_review_decision === 'accept' ? '✓' : '✗'}
			</span>
		{/if}
		<!-- Detection count — top right -->
		{#if sample.detection_count != null && sample.detection_count > 0}
			<span class="absolute top-1.5 right-1.5 flex h-5 min-w-5 items-center justify-center bg-black/50 px-1 text-[10px] font-bold text-white backdrop-blur-sm">
				{sample.detection_count}
			</span>
		{/if}
		<!-- "Raw" marker — no teacher pass yet, boxes are likely incomplete. -->
		{#if isRaw}
			<span
				class="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#A16207]"
				style="background: rgba(255,213,0,0.85); backdrop-filter: blur(4px);"
				title="No teacher pass yet — boxes may be incomplete. Consider waiting before reviewing."
			>
				Raw
			</span>
		{/if}
		<!-- Exposure badge — bottom right so it doesn't collide with Raw. -->
		{#if exposureLabel}
			<span
				class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white"
				style="background: {exposureLabel === 'underexposed' ? 'rgba(30,30,60,0.85)' : 'rgba(208,16,18,0.85)'}; backdrop-filter: blur(4px);"
				title={exposureLabel === 'underexposed'
					? `Underexposed (mean ${sample.luminance_mean?.toFixed(0)}). Likely a lights-off frame.`
					: `Overexposed (mean ${sample.luminance_mean?.toFixed(0)}). Likely sensor saturation.`}
			>
				{exposureLabel === 'underexposed' ? 'Dark' : 'Bright'}
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
