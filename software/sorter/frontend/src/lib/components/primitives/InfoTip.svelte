<script lang="ts">
	import Popover from './Popover.svelte';

	// Small "(i)" info icon that reveals an explanatory popover on hover/focus.
	// The popover is viewport-aware (see Popover.svelte), so the explanation is
	// never clipped at a screen edge. Shared by every tuning page so the param
	// help looks and behaves identically everywhere.
	let { text, class: className = '' }: { text: string; class?: string } = $props();
</script>

<Popover class={className} panelClass="w-72">
	{#snippet trigger()}
		<button
			type="button"
			class="inline-flex shrink-0 cursor-help border-0 bg-transparent p-0 text-text-muted hover:text-text"
			aria-label={text}
		>
			<svg
				class="h-4 w-4"
				viewBox="0 0 16 16"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				aria-hidden="true"
			>
				<circle cx="8" cy="8" r="6.5" />
				<path d="M8 7.25v3.75" stroke-linecap="round" />
				<circle cx="8" cy="5" r="0.6" fill="currentColor" stroke="none" />
			</svg>
		</button>
	{/snippet}
	{text}
</Popover>
