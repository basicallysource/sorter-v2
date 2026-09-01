<script lang="ts">
	import type { Snippet } from 'svelte';

	// Generic inline status badge. Reuse for any tone: neutral, info, success,
	// warning, danger. Renders as a <span>, or a <button> (`as="button"`) when it
	// needs to be an interactive trigger (e.g. a popover). Extra props (onclick,
	// aria-*, title) are forwarded to the element.
	type Variant = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
	let {
		variant = 'neutral',
		as = 'span',
		class: cls = '',
		children,
		...rest
	}: {
		variant?: Variant;
		as?: 'span' | 'button';
		class?: string;
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
	<button type="button" class="{base} {styles[variant]} {cls}" {...rest}>{@render children()}</button>
{:else}
	<span class="{base} {styles[variant]} {cls}" {...rest}>{@render children()}</span>
{/if}
