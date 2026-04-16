<script lang="ts">
	import type { Snippet } from 'svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';
	type Size = 'sm' | 'md';

	let {
		variant = 'primary',
		size = 'md',
		type = 'button',
		disabled = false,
		loading = false,
		class: className = '',
		onclick,
		children
	}: {
		variant?: Variant;
		size?: Size;
		type?: 'button' | 'submit' | 'reset';
		disabled?: boolean;
		loading?: boolean;
		class?: string;
		onclick?: (event: MouseEvent) => void;
		children: Snippet;
	} = $props();

	const variantClasses: Record<Variant, string> = {
		primary:
			'border border-primary bg-primary text-primary-contrast hover:border-primary-hover hover:bg-primary-hover',
		secondary:
			'border border-border bg-surface text-text hover:bg-bg',
		danger:
			'border border-danger bg-danger text-primary-contrast hover:border-danger-hover hover:bg-danger-hover',
		ghost:
			'border border-transparent bg-transparent text-text hover:bg-border'
	};

	const sizeClasses: Record<Size, string> = {
		sm: 'px-2.5 py-1 text-xs',
		md: 'px-3 py-1.5 text-sm'
	};

	const isDisabled = $derived(disabled || loading);
</script>

<button
	{type}
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
