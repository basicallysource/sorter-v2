<!--
	docs/components.md#forms. A text or number field. `unit` puts the unit
	inside the field's edge, after the value ("6 /min"), so the pair reads as
	one control. Focus turns the edge primary and thickens it to 2px, inside,
	so a focused field never shows two lines.
-->
<script lang="ts">
	let {
		value = $bindable(),
		id,
		type = 'text',
		placeholder,
		unit,
		size = 'md',
		invalid = false,
		disabled = false,
		readonly = false,
		min,
		max,
		step,
		class: className = '',
		oninput,
		onchange
	}: {
		value?: string | number | null;
		id?: string;
		type?: 'text' | 'number' | 'password' | 'email' | 'search' | 'url';
		placeholder?: string;
		unit?: string;
		size?: 'sm' | 'md';
		invalid?: boolean;
		disabled?: boolean;
		readonly?: boolean;
		min?: number;
		max?: number;
		step?: number | 'any';
		class?: string;
		oninput?: (event: Event) => void;
		onchange?: (event: Event) => void;
	} = $props();
</script>

<div
	class="flex items-center border bg-field transition-colors focus-within:border-primary focus-within:shadow-[inset_0_0_0_1px_var(--color-primary)]
		{invalid
		? 'border-danger shadow-[inset_0_0_0_1px_var(--color-danger)]'
		: 'border-line-strong hover:border-ink-faint'}
		{disabled ? 'pointer-events-none opacity-45' : ''}
		{size === 'sm' ? 'h-7' : 'h-9'} {className}"
>
	<input
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
		class="h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint
			{size === 'sm' ? 'px-2' : 'px-3'} {type === 'number' ? 'num text-right' : ''}"
	/>
	{#if unit}
		<span class="shrink-0 pr-3 text-sm text-ink-muted select-none">{unit}</span>
	{/if}
</div>
