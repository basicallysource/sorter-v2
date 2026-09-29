<!--
	docs/components.md#forms. A text or number field. `unit` puts the unit
	inside the field's edge, after the value ("6 /min"), so the pair reads as
	one control; `end` puts a small control there instead (a Show button on
	a password). Focus draws the edge in the primary at 2px, over the field's
	own line rather than outside it, so a focused field never shows two lines.
	`element` binds the <input> itself, to focus it from code; any other
	attribute (autocomplete, enterkeyhint, spellcheck) goes on it too.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		value = $bindable(),
		element = $bindable(),
		id,
		type = 'text',
		placeholder,
		unit,
		end,
		size = 'md',
		invalid = false,
		disabled = false,
		readonly = false,
		min,
		max,
		step,
		class: className = '',
		oninput,
		onchange,
		...rest
	}: {
		value?: string | number | null;
		element?: HTMLInputElement;
		id?: string;
		type?: 'text' | 'number' | 'password' | 'email' | 'search' | 'url';
		placeholder?: string;
		unit?: string;
		// A small control inside the field's edge, after the value.
		end?: Snippet;
		// lg for a touch screen, where a field is a thumb's width tall.
		size?: 'sm' | 'md' | 'lg';
		invalid?: boolean;
		disabled?: boolean;
		readonly?: boolean;
		min?: number;
		max?: number;
		step?: number | 'any';
		class?: string;
		oninput?: (event: Event) => void;
		onchange?: (event: Event) => void;
		[attribute: string]: unknown;
	} = $props();

	const height = $derived(
		{ sm: 'h-(--size-control-sm)', md: 'h-(--size-control)', lg: 'h-(--size-control-lg)' }[size]
	);
	const pad = $derived(size === 'sm' ? 'px-(--pad-control-sm)' : 'px-(--pad-control)');
</script>

<div
	class="flex items-center rounded-control border bg-field transition-colors focus-within:border-primary focus-within:outline-2 focus-within:-outline-offset-1 focus-within:outline-primary
		{invalid
		? 'border-danger outline-2 -outline-offset-1 outline-danger'
		: 'border-line-strong hover:border-ink-faint'}
		{disabled ? 'pointer-events-none opacity-45' : ''}
		{height} {className}"
>
	<input
		{...rest}
		bind:this={element}
		{id}
		{type}
		{placeholder}
		{disabled}
		{readonly}
		{min}
		{max}
		{step}
		bind:value
		{oninput}
		{onchange}
		aria-invalid={invalid || undefined}
		class="h-full min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-ink-faint
			{size === 'lg' ? 'text-base' : 'text-sm'} {pad} {type === 'number' ? 'num text-right' : ''}"
	/>
	{#if unit}
		<span class="shrink-0 pr-(--pad-control) text-sm text-ink-muted select-none">{unit}</span>
	{/if}
	{#if end}
		<div class="flex shrink-0 items-center pr-1">{@render end()}</div>
	{/if}
</div>
