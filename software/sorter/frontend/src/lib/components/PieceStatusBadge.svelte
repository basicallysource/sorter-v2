<script lang="ts">
	// The ONE classification-status badge — records list, recent-pieces dropdown,
	// and the piece detail page all render this instead of hand-rolled chips with
	// diverging colors. The green Classified chip is gated strictly on
	// classification_status === 'classified': failed/unknown/not_found pieces set
	// classified_at too, and must never read as a success.
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

	type BadgeSpec = { label: string; cls: string; title: string | undefined };

	const spec = $derived.by<BadgeSpec>(() => {
		const s = effectiveStatus(status, requestFailed);
		if (s === 'classified')
			return {
				label: 'Classified',
				cls: 'border-success bg-success/10 text-success',
				title: undefined
			};
		if (s === 'failed')
			return {
				label: 'ID failed',
				cls: 'border-danger bg-danger/10 text-danger',
				title: 'The identification request failed (network/transport error) — never identified'
			};
		if (s === 'unknown' || s === 'not_found')
			return {
				label: 'Unidentified',
				cls: 'border-warning/60 bg-warning/10 text-warning-dark',
				title: 'Identification returned no usable match for this piece'
			};
		if (s === 'multi_drop_fail')
			return {
				label: 'Multi drop',
				cls: 'border-danger bg-danger/10 text-danger',
				title: 'Multiple pieces dropped together — rejected'
			};
		if (s === 'classifying')
			return {
				label: 'Classifying',
				cls: 'border-primary bg-primary/10 text-primary',
				title: undefined
			};
		if (s === 'pending')
			return {
				label: 'Pending',
				cls: 'border-primary bg-primary/10 text-primary',
				title: undefined
			};
		return {
			label: s ? s.replace(/_/g, ' ') : 'No status',
			cls: 'border-text-muted bg-text-muted/10 text-text-muted',
			title: undefined
		};
	});
</script>

<span
	class="inline-flex items-center border px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider {spec.cls}"
	title={spec.title}
>
	{spec.label}
</span>
{#if dead}
	<span
		class="inline-flex items-center border border-warning bg-warning/10 px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-warning-dark"
		title="Reaped — went silent without ever reaching the distributed stage"
	>
		Timed out
	</span>
{/if}
