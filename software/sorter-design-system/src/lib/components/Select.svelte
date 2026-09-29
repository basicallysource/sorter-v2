<!--
	docs/components.md#forms. The browser's own select, drawn as a field, so
	the list it opens is the platform's (keyboard, touch and screen readers
	all work). For a list with icons, descriptions or actions, use Menu.
-->
<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';

	type Option = { value: string; label: string; disabled?: boolean };

	let {
		value = $bindable(),
		options,
		id,
		size = 'md',
		disabled = false,
		invalid = false,
		class: className = '',
		onchange
	}: {
		value?: string;
		options: Option[];
		id?: string;
		size?: 'sm' | 'md';
		disabled?: boolean;
		invalid?: boolean;
		class?: string;
		onchange?: (event: Event) => void;
	} = $props();
</script>

<div class="relative {disabled ? 'pointer-events-none opacity-45' : ''} {className}">
	<select
		{id}
		{disabled}
		bind:value
		{onchange}
		aria-invalid={invalid || undefined}
		class="w-full appearance-none border bg-field pr-9 text-sm text-ink transition-colors outline-none
			focus-visible:border-primary focus-visible:shadow-[inset_0_0_0_1px_var(--color-primary)]
			{invalid
			? 'border-danger shadow-[inset_0_0_0_1px_var(--color-danger)]'
			: 'border-line-strong hover:border-ink-faint'}
			{size === 'sm' ? 'h-7 pl-2' : 'h-9 pl-3'}"
	>
		{#each options as option (option.value)}
			<option value={option.value} disabled={option.disabled}>{option.label}</option>
		{/each}
	</select>
	<ChevronDown
		size={16}
		class="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-ink-muted"
	/>
</div>
