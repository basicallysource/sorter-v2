<script lang="ts">
	import type { Snippet } from 'svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	type Variant = 'primary' | 'secondary' | 'success' | 'danger' | 'ghost';
	type Size = 'sm' | 'md';

	let {
		variant = 'primary',
		size = 'md',
		type = 'button',
		title,
		disabled = false,
		loading = false,
		class: className = '',
		onclick,
		children
	}: {
		variant?: Variant;
		size?: Size;
		type?: 'button' | 'submit' | 'reset';
		title?: string;
		disabled?: boolean;
		loading?: boolean;
		class?: string;
		onclick?: (event: MouseEvent) => void;
		children: Snippet;
	} = $props();

	const variantClasses: Record<Variant, string> = {
		primary:
			'border border-primary bg-primary text-on-primary hover:border-primary-hover hover:bg-primary-hover',
		secondary:
			'border border-line bg-surface text-ink hover:bg-hover',
		success:
			'border border-success/50 bg-success-soft text-success-ink hover:bg-success-soft',
		danger:
			'border border-danger bg-danger text-on-primary hover:border-danger-hover hover:bg-danger-hover',
		ghost:
			'border border-transparent bg-transparent text-ink hover:bg-line'
	};

	const sizeClasses: Record<Size, string> = {
		sm: 'px-2.5 py-1 text-xs',
		md: 'px-3 py-1.5 text-sm'
	};

	const isDisabled = $derived(disabled || loading);
</script>

<button
	{type}
	{title}
	disabled={isDisabled}
	{onclick}
	class="inline-flex items-center justify-center gap-2 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 {variantClasses[
		variant
	]} {sizeClasses[size]} {className}"
>
	{#if loading}
		<Spinner />
	{/if}
	{@render children()}
</button>
