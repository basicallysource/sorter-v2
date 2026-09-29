<!--
	docs/components.md#forms. A square box with its label after it. Use it
	for a choice that is saved with a form; a setting that applies the moment
	it changes is a Switch.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Check from '@lucide/svelte/icons/check';

	let {
		checked = $bindable(false),
		id,
		disabled = false,
		onchange,
		children
	}: {
		checked?: boolean;
		id?: string;
		disabled?: boolean;
		onchange?: (event: Event) => void;
		children?: Snippet;
	} = $props();
</script>

<label
	class="inline-flex items-center gap-2.5 text-sm text-ink {disabled
		? 'pointer-events-none opacity-45'
		: 'cursor-pointer'}"
>
	<span class="relative inline-flex size-4 shrink-0">
		<input
			type="checkbox"
			{id}
			{disabled}
			bind:checked
			{onchange}
			class="peer size-4 cursor-pointer appearance-none border border-line-strong bg-field transition-colors checked:border-primary checked:bg-primary hover:border-ink-faint checked:hover:border-primary-hover checked:hover:bg-primary-hover"
		/>
		<Check
			size={12}
			class="pointer-events-none absolute inset-0 m-auto text-on-primary opacity-0 peer-checked:opacity-100"
			strokeWidth={3}
		/>
	</span>
	{#if children}<span>{@render children()}</span>{/if}
</label>
