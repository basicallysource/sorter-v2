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
		success: 'border-success/40 bg-success-soft text-ink',
		warning: 'border-warning/50 bg-warning-soft text-ink',
		danger: 'border-danger/40 bg-danger-soft text-ink',
		info: 'border-info/40 bg-info-soft text-ink'
	};
</script>

<div class="border px-3 py-2 text-sm leading-relaxed {variantClasses[variant]} {className}">
	{@render children()}
</div>
