<script lang="ts">
	import type { Snippet } from 'svelte';
	import { tip } from '$lib/popover';

	// Generic inline status badge. Reuse for any tone: neutral, info, success,
	// warning, danger. Renders as a <span>, or a <button> (`as="button"`) when it
	// needs to be an interactive trigger (e.g. a popover). Extra props (onclick,
	// aria-*) are forwarded to the element.
	//
	// `tipText` is the hover label. It goes through the popover family's `tip`
	// action rather than a native `title`, which cannot be styled and renders
	// above every layer on the page, including an open popover.
	type Variant = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
	let {
		variant = 'neutral',
		as = 'span',
		class: cls = '',
		tipText,
		children,
		...rest
	}: {
		variant?: Variant;
		as?: 'span' | 'button';
		class?: string;
		tipText?: string;
		children: Snippet;
	} & Record<string, unknown> = $props();

	const base = 'inline-flex items-center gap-0.5 border px-1 text-xs font-semibold';
	const styles: Record<Variant, string> = {
		neutral: 'border-border text-text-muted',
		info: 'border-info/50 text-info',
		success: 'border-success/50 text-success',
		warning: 'border-warning/60 bg-warning/[0.10] text-warning-dark',
		danger: 'border-danger/50 bg-danger/[0.08] text-danger'
	};
</script>

{#if as === 'button'}
	<button type="button" class="{base} {styles[variant]} {cls}" use:tip={tipText} {...rest}>{@render children()}</button>
{:else}
	<span class="{base} {styles[variant]} {cls}" use:tip={tipText} {...rest}>{@render children()}</span>
{/if}
