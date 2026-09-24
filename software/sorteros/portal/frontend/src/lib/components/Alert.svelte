<script lang="ts">
	// The Sorter app's Alert primitive: one flat 1px border on all four sides at
	// ~40% of the tone, a 6% tint behind, text in the normal text color.
	import type { Snippet } from 'svelte';

	type Variant = 'success' | 'warning' | 'danger' | 'info';

	let {
		variant = 'info',
		children
	}: {
		variant?: Variant;
		children: Snippet;
	} = $props();

	const variantClasses: Record<Variant, string> = {
		success: 'border-success/40 bg-success/[0.06]',
		warning: 'border-warning/50 bg-warning/[0.07]',
		danger: 'border-danger/40 bg-danger/[0.06]',
		info: 'border-info/40 bg-info/[0.06]'
	};
</script>

<div
	role={variant === 'danger' ? 'alert' : 'status'}
	class="border px-3 py-2.5 text-sm leading-relaxed text-text {variantClasses[variant]}"
>
	{@render children()}
</div>
