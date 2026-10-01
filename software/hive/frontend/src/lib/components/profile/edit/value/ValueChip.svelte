<!--
	One chosen value in a condition: its name (or whatever `children` draws, a
	color's swatch and name) and a button to take it out. The chip is the same
	small tint ConditionList shows a value in, with a remove control at its end.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import X from '@lucide/svelte/icons/x';

	let {
		label,
		onremove,
		children
	}: {
		// The value's name; the remove button is named for it.
		label: string;
		onremove?: () => void;
		children?: Snippet;
	} = $props();
</script>

<span
	class="inline-flex min-h-7 max-w-full min-w-0 items-center gap-1.5 rounded-badge bg-hover pl-2 text-sm text-ink {onremove
		? 'pr-0.5'
		: 'pr-2'}"
>
	{#if children}
		{@render children()}
	{:else}
		<span class="truncate" title={label}>{label}</span>
	{/if}
	{#if onremove}
		<button
			type="button"
			aria-label="Remove {label}"
			onclick={onremove}
			class="inline-flex size-6 shrink-0 items-center justify-center rounded-badge text-ink-muted transition-colors hover:bg-hover hover:text-ink active:bg-pressed"
		>
			<X size={14} />
		</button>
	{/if}
</span>
