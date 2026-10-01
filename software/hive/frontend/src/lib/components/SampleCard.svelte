<script lang="ts">
	import Card from './Card.svelte';
	import type { Sample } from '$lib/api';
	import { api } from '$lib/api';

	interface Props {
		sample: Sample;
		href?: string;
	}

	let { sample, href = '#' }: Props = $props();

	let imgNaturalWidth = $state(0);
	let imgNaturalHeight = $state(0);

	// These pills sit on top of the sample photo, not on a themed surface, so the
	// status hues stay put in both themes — but they come from the tokens rather
	// than repeating the hex values.
	const statusConfig: Record<string, { label: string; color: string; bg: string }> = {
		// Chips on a photo are solid, so they read on any picture.
		accepted: { label: 'Accepted', color: 'var(--on-success)', bg: 'var(--success)' },
		rejected: { label: 'Rejected', color: 'var(--on-danger)', bg: 'var(--danger)' },
		in_review: { label: 'Needs more reviews', color: 'var(--on-info)', bg: 'var(--info)' },
		conflict: { label: 'Conflict', color: 'var(--on-warning)', bg: 'var(--warning)' },
		unreviewed: { label: 'Unreviewed', color: '#ffffff', bg: 'var(--scrim)' }
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

<Card {href} label="Sample {sample.local_sample_id}" padded={false} class="overflow-hidden">
	<div class="relative aspect-square overflow-hidden bg-media">
		<img
			src={api.sampleImageUrl(sample.id)}
			alt="Sample {sample.local_sample_id}"
			class="size-full object-cover"
			loading="lazy"
			onload={onImageLoad}
		/>
		{#if showBboxes}
			<svg
				class="absolute inset-0 size-full"
				viewBox="0 0 {imgNaturalWidth} {imgNaturalHeight}"
				preserveAspectRatio="xMidYMid slice"
			>
				{#each bboxes as bbox, i (i)}
					<rect
						x={bbox[0]}
						y={bbox[1]}
						width={bbox[2] - bbox[0]}
						height={bbox[3] - bbox[1]}
						fill="none"
						stroke="var(--success)"
						stroke-width={Math.max(2, Math.round(imgNaturalWidth / 300))}
						opacity="0.8"
					/>
				{/each}
			</svg>
		{/if}
		<!-- The consensus, and under it your own vote, top left. -->
		<div class="absolute top-1.5 left-1.5 flex flex-col items-start gap-1">
			<span class="inline-flex h-(--size-badge) items-center rounded-badge px-1.5 text-xs font-medium" style="color: {cfg.color}; background: {cfg.bg};">{cfg.label}</span>
			{#if sample.my_review_decision}
				<span
					class="inline-flex h-(--size-badge) items-center rounded-badge px-1.5 text-xs font-medium {sample.my_review_decision === 'accept' ? 'bg-success text-on-success' : 'bg-danger text-on-danger'}"
					title={sample.my_review_decision === 'accept' ? 'You accepted this' : 'You rejected this'}
					>You {sample.my_review_decision === 'accept' ? 'accepted' : 'rejected'}</span
				>
			{/if}
		</div>
		{#if sample.detection_count != null && sample.detection_count > 0}
			<span class="inline-flex h-(--size-badge) items-center rounded-badge px-1.5 text-xs font-medium num absolute top-1.5 right-1.5 bg-scrim text-white" title="Pieces found">{sample.detection_count}</span>
		{/if}
		{#if isRaw}
			<span
				class="inline-flex h-(--size-badge) items-center rounded-badge px-1.5 text-xs font-medium absolute bottom-1.5 left-1.5 bg-warning text-on-warning"
				title="No teacher pass yet, so the boxes may be incomplete. Consider waiting before reviewing."
				>Raw</span
			>
		{/if}
		{#if exposureLabel}
			<span
				class="inline-flex h-(--size-badge) items-center rounded-badge px-1.5 text-xs font-medium absolute right-1.5 bottom-1.5 bg-scrim text-white"
				title={exposureLabel === 'underexposed'
					? `Underexposed (mean ${sample.luminance_mean?.toFixed(0)}); probably a frame with the lights off.`
					: `Overexposed (mean ${sample.luminance_mean?.toFixed(0)}); probably a saturated sensor.`}
				>{exposureLabel === 'underexposed' ? 'Dark' : 'Bright'}</span
			>
		{/if}
	</div>

	<div class="flex items-center justify-between gap-2 px-2.5 py-2 text-sm text-ink-muted">
		<span class="flex min-w-0 items-center gap-1.5">
			{#if roleLabel}<span class="truncate text-ink">{roleLabel}</span>{/if}
			<span class="shrink-0">{timeAgo}</span>
			{#if score !== null}
				<span class="num shrink-0 {score >= 80 ? 'text-success-ink' : score >= 50 ? 'text-ink' : 'text-danger-ink'}"
					>{score}%</span
				>
			{/if}
		</span>
		{#if sample.review_count > 0}<span class="num shrink-0" title="Reviews">{sample.review_count}x</span>{/if}
	</div>
</Card>
