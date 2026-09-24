<script lang="ts">
	// The Sorter app's Button primitive, sized for a thumb: every button is at
	// least 44px tall, and `wide` fills the column for a screen's main action.
	import type { Snippet } from 'svelte';
	import Spinner from './Spinner.svelte';

	type Variant = 'primary' | 'secondary';

	let {
		variant = 'secondary',
		type = 'button',
		wide = false,
		disabled = false,
		loading = false,
		onclick,
		children
	}: {
		variant?: Variant;
		type?: 'button' | 'submit';
		wide?: boolean;
		disabled?: boolean;
		loading?: boolean;
		onclick?: (event: MouseEvent) => void;
		children: Snippet;
	} = $props();

	const variantClasses: Record<Variant, string> = {
		primary: 'setup-button-primary',
		secondary: 'setup-button-secondary text-text'
	};
</script>

<button
	{type}
	disabled={disabled || loading}
	{onclick}
	class="inline-flex items-center justify-center gap-2 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 {variantClasses[
		variant
	]} {wide ? 'min-h-12 w-full px-4 text-base' : 'min-h-11 px-3 text-sm'}"
>
	{#if loading}
		<Spinner size={14} />
	{/if}
	{@render children()}
</button>
