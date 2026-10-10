<!--
	docs/components.md#forms. A label over its control, and one sentence under
	it: help in muted ink, or the error in danger ink (which replaces the help).
	Give the control the same `id` as `for`, and `aria-invalid` when `error`.
	`info` is what a setting means when its name cannot say it all: an ⓘ beside
	the label opens it in a Popover.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Info from '@lucide/svelte/icons/info';
	import Popover from './Popover.svelte';

	let {
		label,
		for: forId,
		help,
		error,
		info,
		children,
		class: className = ''
	}: {
		label: string;
		for: string;
		help?: string;
		error?: string;
		info?: string;
		children: Snippet;
		class?: string;
	} = $props();
</script>

<div class="flex flex-col gap-1.5 {className}">
	<div class="flex items-center gap-1">
		<label for={forId} class="text-sm font-medium text-ink">{label}</label>
		{#if info}
			<Popover label={label} width="18rem">
				{#snippet trigger(props)}
					<button
						{...props}
						type="button"
						aria-label="What {label} means"
						class="flex size-5 items-center justify-center rounded-button text-ink-muted transition-colors hover:bg-hover hover:text-ink"
					>
						<Info size={14} />
					</button>
				{/snippet}
				<p class="text-sm text-ink">{info}</p>
			</Popover>
		{/if}
	</div>
	{@render children()}
	{#if error}
		<p class="text-sm text-danger-ink">{error}</p>
	{:else if help}
		<p class="text-sm text-ink-muted">{help}</p>
	{/if}
</div>
