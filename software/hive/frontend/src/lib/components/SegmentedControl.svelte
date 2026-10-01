<!--
	docs/components.md#choices. Two to five choices that apply at once (Light /
	Dark, Duration / Degrees), as one control: a single 1px outline, the
	segments divided by 1px lines with no gap or padding between them, and the
	chosen segment shown by a fill, the primary's tint with its ink. There is no
	track and no raised thumb: a padded well around segments reads as a thick
	border. More than five choices, or long labels, is a Select.
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
	class="{full
		? 'flex w-full'
		: 'inline-flex'} divide-x divide-line-strong overflow-hidden rounded-button border border-line-strong bg-field
		{size === 'sm' ? 'h-(--size-control-sm)' : 'h-(--size-control)'}"
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
			class="inline-flex h-full items-center justify-center gap-1.5 text-sm whitespace-nowrap transition-colors focus-visible:-outline-offset-2
				{full ? 'flex-1' : ''} {size === 'sm' ? 'px-(--pad-control-sm)' : 'px-(--pad-control)'}
				{on
				? 'bg-primary-soft font-medium text-primary-ink'
				: 'text-ink-muted hover:bg-hover hover:text-ink'}"
		>
			{#if option.icon}<option.icon size={14} />{/if}
			<span class={labelClass}>{option.label}</span>
		</button>
	{/each}
</div>
