<!--
	docs/components.md#button. Four variants, two sizes. With `href` it is a
	link that looks like a button. With an `icon` and no children it is an
	icon button, and `label` becomes its accessible name (and its tooltip).
	`loading` swaps the icon for the Spinner and keeps the width.
-->
<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import Spinner from './Spinner.svelte';

	type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
	type Size = 'sm' | 'md';

	let {
		variant = 'secondary',
		size = 'md',
		type = 'button',
		href,
		icon: Icon,
		label,
		loading = false,
		disabled = false,
		class: className = '',
		onclick,
		children,
		...rest
	}: {
		variant?: Variant;
		size?: Size;
		type?: 'button' | 'submit' | 'reset';
		href?: string;
		// A Lucide icon component, e.g. `import Plus from '@lucide/svelte/icons/plus'`.
		icon?: Component<{ size?: number; class?: string }>;
		label?: string;
		loading?: boolean;
		disabled?: boolean;
		class?: string;
		onclick?: (event: MouseEvent) => void;
		children?: Snippet;
		// Anything else goes on the element: aria-*, popovertarget, data-*.
		[attribute: string]: unknown;
	} = $props();

	const variants: Record<Variant, string> = {
		primary: 'bg-primary text-on-primary hover:bg-primary-hover',
		secondary: 'border border-line-strong text-ink hover:bg-hover active:bg-pressed',
		ghost: 'text-ink hover:bg-hover active:bg-pressed',
		danger: 'bg-danger text-white hover:bg-danger-hover'
	};

	const iconOnly = $derived(!children);
	const sizes = $derived(
		iconOnly
			? { sm: 'size-7', md: 'size-9' }[size]
			: { sm: 'h-7 gap-1.5 px-2.5', md: 'h-9 gap-2 px-3.5' }[size]
	);
	const iconSize = $derived(size === 'sm' ? 14 : 16);
	const classes = $derived(
		`inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap text-sm font-medium transition-colors ${variants[variant]} ${sizes} ${className}`
	);
	const inert = $derived(disabled || loading);
</script>

{#snippet content()}
	{#if loading}
		<Spinner size={iconSize} />
	{:else if Icon}
		<Icon size={iconSize} class="shrink-0" />
	{/if}
	{#if children}
		{@render children()}
	{/if}
{/snippet}

{#if href && !inert}
	<a
		{href}
		{...rest}
		class={classes}
		aria-label={iconOnly ? label : undefined}
		title={iconOnly ? label : undefined}
	>
		{@render content()}
	</a>
{:else}
	<!-- Loading keeps the button at full strength (it is busy, not unavailable); disabled fades it. -->
	<button
		{...rest}
		{type}
		onclick={loading ? undefined : onclick}
		{disabled}
		aria-busy={loading || undefined}
		aria-disabled={loading || undefined}
		aria-label={iconOnly ? label : undefined}
		title={iconOnly ? label : undefined}
		class="{classes} {loading
			? 'pointer-events-none'
			: ''} disabled:pointer-events-none disabled:opacity-45"
	>
		{@render content()}
	</button>
{/if}
