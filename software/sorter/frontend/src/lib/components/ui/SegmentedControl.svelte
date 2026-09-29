<!--
	docs/components.md#segmented-control. Two to five choices that apply at
	once (Light / Dark, Duration / Degrees). A track, and a thumb on the
	chosen one told apart by its fill: no borders, so it never adds a line to
	the panel it sits in. More than five choices, or long labels, is a Select.
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
	class="{full ? 'flex w-full' : 'inline-flex'} gap-0.5 rounded-button bg-track p-0.5"
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
			class="inline-flex items-center justify-center gap-1.5 rounded-button-inner text-sm whitespace-nowrap transition-colors
				{full ? 'flex-1' : ''} {size === 'sm'
				? 'h-[calc(var(--size-control-sm)-4px)] px-(--pad-control-sm)'
				: 'h-[calc(var(--size-control)-4px)] px-(--pad-control)'}
				{on ? 'bg-thumb font-medium text-ink' : 'text-ink-muted hover:bg-hover hover:text-ink'}"
		>
			{#if option.icon}<option.icon size={14} />{/if}
			<span class={labelClass}>{option.label}</span>
		</button>
	{/each}
</div>
