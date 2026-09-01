<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { ChangePriority } from '$lib/filament';

	let {
		priority,
		as = 'span',
		class: cls = '',
		children,
		...rest
	}: {
		priority: ChangePriority;
		as?: 'span' | 'button';
		class?: string;
		children?: Snippet;
	} & Record<string, unknown> = $props();

	const number = $derived(Number.parseInt(priority.slice(1), 10) || 0);
	const fixedHues = [2, 38, 215, 278];
	const hue = $derived(fixedHues[number] ?? Math.round((number * 137.508 + 2) % 360));
</script>

{#snippet content()}{#if children}{@render children()}{:else}{priority}{/if}{/snippet}

{#if as === 'button'}
	<button type="button" class="priority-badge {cls}" style:--priority-hue={hue} {...rest}>{@render content()}</button>
{:else}
	<span class="priority-badge {cls}" style:--priority-hue={hue} {...rest}>{@render content()}</span>
{/if}

<style>
	.priority-badge {
		display: inline-flex;
		align-items: center;
		gap: 0.125rem;
		border: 1px solid hsl(var(--priority-hue) 72% 42% / 0.58);
		background: hsl(var(--priority-hue) 88% 50% / 0.1);
		padding: 0 0.25rem;
		color: hsl(var(--priority-hue) 72% 29%);
		font-size: 0.75rem;
		font-weight: 700;
	}
	:global(.dark) .priority-badge {
		border-color: hsl(var(--priority-hue) 70% 64% / 0.62);
		background: hsl(var(--priority-hue) 70% 55% / 0.14);
		color: hsl(var(--priority-hue) 76% 72%);
	}
</style>
