<!--
	docs/components.md#badge. A short status or count next to what it
	describes. A tint and the tone's ink, never a border. `dot` puts a
	status dot before the text: always round, whatever the corners.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	type Tone = 'neutral' | 'primary' | 'info' | 'success' | 'warning' | 'danger';

	let {
		tone = 'neutral',
		dot = false,
		children
	}: { tone?: Tone; dot?: boolean; children: Snippet } = $props();

	const tones: Record<Tone, { box: string; dot: string }> = {
		neutral: { box: 'bg-hover text-ink-muted', dot: 'bg-ink-faint' },
		primary: { box: 'bg-primary-soft text-primary-ink', dot: 'bg-primary' },
		info: { box: 'bg-info-soft text-info-ink', dot: 'bg-info' },
		success: { box: 'bg-success-soft text-success-ink', dot: 'bg-success' },
		warning: { box: 'bg-warning-soft text-warning-ink', dot: 'bg-warning' },
		danger: { box: 'bg-danger-soft text-danger-ink', dot: 'bg-danger' }
	};
</script>

<span
	class="inline-flex h-(--size-badge) shrink-0 items-center gap-1.5 rounded-badge px-(--pad-badge) text-xs font-medium whitespace-nowrap {tones[
		tone
	].box}"
>
	{#if dot}<span class="size-1.5 rounded-full {tones[tone].dot}"></span>{/if}
	{@render children()}
</span>
