<script lang="ts">
	import type { Snippet } from 'svelte';

	type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';
	type Size = 'sm' | 'md';

	interface Props {
		variant?: Variant;
		size?: Size;
		disabled?: boolean;
		loading?: boolean;
		type?: 'button' | 'submit' | 'reset';
		onclick?: (event: MouseEvent) => void;
		children: Snippet;
		class?: string;
	}

	let {
		variant = 'primary',
		size = 'md',
		disabled = false,
		loading = false,
		type = 'button',
		onclick,
		children,
		class: extra = '',
	}: Props = $props();

	const VARIANTS: Record<Variant, string> = {
		primary: 'bg-primary text-white hover:bg-primary-hover disabled:bg-primary/50',
		secondary: 'border border-border bg-surface text-text hover:bg-bg disabled:text-text-muted',
		danger: 'bg-danger text-white hover:bg-primary-hover disabled:bg-danger/50',
		ghost: 'text-text hover:bg-bg disabled:text-text-muted',
	};

	const SIZES: Record<Size, string> = {
		sm: 'px-2.5 py-1 text-xs',
		md: 'px-4 py-2 text-sm',
	};

	let isDisabled = $derived(disabled || loading);
</script>

<button
	{type}
	disabled={isDisabled}
	{onclick}
	class="inline-flex items-center justify-center gap-2 font-medium transition-colors disabled:cursor-not-allowed {VARIANTS[variant]} {SIZES[size]} {extra}"
>
	{#if loading}
		<span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
	{/if}
	{@render children()}
</button>
