<script lang="ts">
	import type { Snippet } from 'svelte';

	type Variant = 'success' | 'warning' | 'danger' | 'info';

	interface Props {
		variant?: Variant;
		title?: string;
		children: Snippet;
	}

	let { variant = 'info', title, children }: Props = $props();

	const VARIANTS: Record<Variant, string> = {
		success: 'border-success/30 bg-success/[0.06] text-success',
		warning: 'border-warning/40 bg-warning/[0.08] text-text',
		danger: 'border-danger/30 bg-danger/[0.06] text-danger',
		info: 'border-info/30 bg-info/[0.06] text-info',
	};
</script>

<div class="border px-3 py-2 text-sm {VARIANTS[variant]}">
	{#if title}
		<div class="font-semibold">{title}</div>
	{/if}
	<div class={title ? 'mt-0.5' : ''}>{@render children()}</div>
</div>
