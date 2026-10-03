<script lang="ts">
	// The ONE classification-status badge: the records list, the recent pieces
	// and the piece detail page all render this, so the colors cannot diverge.
	// The green Classified badge is gated strictly on classification_status ===
	// 'classified': failed/unknown/not_found pieces set classified_at too, and
	// must never read as a success.
	import Badge from '$lib/components/ui/Badge.svelte';
	import { effectiveStatus } from '$lib/pieces';

	let {
		status,
		dead = false,
		requestFailed = false
	}: {
		status: string | null | undefined;
		dead?: boolean;
		requestFailed?: boolean;
	} = $props();

	type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger';
	type Spec = { label: string; tone: Tone; title: string | undefined };

	const spec = $derived.by<Spec>(() => {
		const s = effectiveStatus(status, requestFailed);
		if (s === 'classified') return { label: 'Classified', tone: 'success', title: undefined };
		if (s === 'failed')
			return {
				label: 'ID failed',
				tone: 'danger',
				title: 'The identification request failed (a network or transport error), so it was never identified'
			};
		if (s === 'unknown' || s === 'not_found')
			return {
				label: 'Unidentified',
				tone: 'warning',
				title: 'Identification found no usable match for this piece'
			};
		if (s === 'multi_drop_fail')
			return {
				label: 'Multi drop',
				tone: 'danger',
				title: 'Several pieces dropped together and were rejected'
			};
		if (s === 'classifying') return { label: 'Classifying', tone: 'primary', title: undefined };
		if (s === 'pending') return { label: 'Pending', tone: 'primary', title: undefined };
		return {
			label: s ? s.replace(/_/g, ' ') : 'No status',
			tone: 'neutral',
			title: undefined
		};
	});
</script>

<span class="inline-flex" title={spec.title}><Badge tone={spec.tone}>{spec.label}</Badge></span>
{#if dead}
	<span
		class="inline-flex"
		title="Timed out: went silent without ever reaching the distributed stage"
	>
		<Badge tone="warning">Timed out</Badge>
	</span>
{/if}
