<script lang="ts">
	import type { Snippet } from 'svelte';

	type Variant = 'success' | 'warning' | 'danger' | 'info';

	let {
		variant = 'info',
		class: className = '',
		children
	}: {
		variant?: Variant;
		class?: string;
		children: Snippet;
	} = $props();

	const variantClasses: Record<Variant, string> = {
		success: 'border-success/40 bg-success/[0.06] text-text',
		warning: 'border-warning/50 bg-warning/[0.07] text-text',
		danger: 'border-danger/40 bg-danger/[0.06] text-text',
		info: 'border-info/40 bg-info/[0.06] text-text'
	};
</script>

<div class="border px-3 py-2 text-sm leading-relaxed {variantClasses[variant]} {className}">
	{@render children()}
</div>
