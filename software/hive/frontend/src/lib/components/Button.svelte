<!--
	docs/components.md#button. Four variants, three sizes. What each variant is
	drawn with comes from the button style tokens in app.css, and its corners
	from rounded-button. With `href` it is a link that looks like a button.
	With an `icon` and no children it is an icon button, and `label` becomes
	its accessible name and its tooltip. `loading` swaps the icon for the
	Spinner and keeps the label.
-->
<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import Spinner from './Spinner.svelte';

	type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
	// lg is a touch screen's main action: a thumb's width tall.
	type Size = 'sm' | 'md' | 'lg';

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
		primary:
			'border-(--btn-primary-line) bg-(--btn-primary-bg) text-(--btn-primary-fg) hover:bg-(--btn-primary-hover)',
		secondary:
			'border-(--btn-secondary-line) bg-(--btn-secondary-bg) text-(--btn-secondary-fg) hover:bg-(--btn-secondary-hover)',
		ghost: 'border-transparent text-ink hover:bg-hover active:bg-pressed',
		danger:
			'border-(--btn-danger-line) bg-(--btn-danger-bg) text-(--btn-danger-fg) hover:bg-(--btn-danger-hover)'
	};

	const iconOnly = $derived(!children);
	const sizes = $derived(
		iconOnly
			? {
					sm: 'size-(--size-control-sm)',
					md: 'size-(--size-control)',
					lg: 'size-(--size-control-lg)'
				}[size]
			: {
					sm: 'h-(--size-control-sm) gap-1.5 px-(--pad-control-sm) text-sm',
					md: 'h-(--size-control) gap-2 px-(--pad-control) text-sm',
					lg: 'h-(--size-control-lg) gap-2 px-5 text-base'
				}[size]
	);
	const iconSize = $derived({ sm: 14, md: 16, lg: 18 }[size]);
	const classes = $derived(
		`inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-button border font-medium transition-colors ${variants[variant]} ${sizes} ${className}`
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
		{onclick}
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
