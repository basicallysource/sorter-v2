<!--
	docs/components.md#segmented-control. Two to five choices that apply at
	once (Light / Dark, Duration / Degrees). A well for a track and a raised
	thumb on the chosen one: no borders, so it never adds a line to the
	panel it sits in. More than five choices, or long labels, is a Select.
-->
<script lang="ts" generics="T extends string">
	import type { Component } from 'svelte';

	type Option = { value: T; label: string; icon?: Component<{ size?: number; class?: string }> };

	let {
		value = $bindable(),
		options,
		label,
		size = 'md',
		full = false,
		labelClass = '',
		onchange
	}: {
		value: T;
		options: Option[];
		// The accessible name of the group.
		label: string;
		size?: 'sm' | 'md';
		// Stretch to the container's width, choices sharing it equally.
		full?: boolean;
		// Classes for each choice's text, e.g. 'max-sm:sr-only' to show only icons on a phone.
		labelClass?: string;
		onchange?: (value: T) => void;
	} = $props();

	function choose(next: T) {
		value = next;
		onchange?.(next);
	}

	function onkeydown(event: KeyboardEvent) {
		const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
		if (!step) return;
		event.preventDefault();
		const index = options.findIndex((o) => o.value === value);
		const next = options[(index + step + options.length) % options.length];
		choose(next.value);
		const group = event.currentTarget as HTMLElement;
		group.querySelector<HTMLElement>(`[data-value="${next.value}"]`)?.focus();
	}
</script>

<div
	role="radiogroup"
	aria-label={label}
	tabindex="-1"
	{onkeydown}
	class="{full ? 'flex w-full' : 'inline-flex'} gap-0.5 bg-well p-0.5"
>
	{#each options as option (option.value)}
		{@const on = option.value === value}
		<button
			type="button"
			role="radio"
			aria-checked={on}
			tabindex={on ? 0 : -1}
			data-value={option.value}
			onclick={() => choose(option.value)}
			class="inline-flex items-center justify-center gap-1.5 text-sm whitespace-nowrap transition-colors
				{full ? 'flex-1' : ''} {size === 'sm' ? 'h-6 px-2.5' : 'h-8 px-3.5'}
				{on
				? 'bg-raised font-medium text-ink shadow-(--shadow-thumb)'
				: 'text-ink-muted hover:bg-hover hover:text-ink'}"
		>
			{#if option.icon}<option.icon size={14} />{/if}
			<span class={labelClass}>{option.label}</span>
		</button>
	{/each}
</div>
