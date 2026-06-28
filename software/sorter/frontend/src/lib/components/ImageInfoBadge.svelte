<script lang="ts">
	import { Info } from 'lucide-svelte';

	// A small info icon that reveals a metadata popover on hover/focus. The
	// caller supplies arbitrary label/value rows; this component additionally
	// measures and prepends the image's natural pixel resolution from `src`.
	// Uses a span trigger (not a button) so it nests safely inside clickable
	// tiles without invalid nested-interactive markup.
	let {
		src,
		rows = [],
		class: className = ''
	}: {
		src: string;
		rows?: { label: string; value: string }[];
		class?: string;
	} = $props();

	let resolution = $state<string | null>(null);

	$effect(() => {
		resolution = null;
		const s = src;
		if (!s) return;
		let cancelled = false;
		const img = new Image();
		img.onload = () => {
			if (!cancelled) resolution = `${img.naturalWidth}×${img.naturalHeight}`;
		};
		img.src = s;
		return () => {
			cancelled = true;
		};
	});

	const allRows = $derived(
		resolution ? [{ label: 'Resolution', value: resolution }, ...rows] : rows
	);
</script>

<span class="group relative inline-flex {className}" role="presentation">
	<span
		class="flex items-center justify-center border border-border bg-surface/90 p-0.5 text-text-muted hover:text-text"
		aria-label="Image info"
		title="Image info"
	>
		<Info size={13} />
	</span>
	<span
		class="pointer-events-none absolute right-0 top-full z-50 mt-1 hidden min-w-[9.5rem] flex-col gap-1 border border-border bg-surface p-2 shadow-md group-hover:flex"
		role="tooltip"
	>
		{#each allRows as row (row.label)}
			<span class="flex items-center justify-between gap-3">
				<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">
					{row.label}
				</span>
				<span class="text-sm tabular-nums text-text">{row.value}</span>
			</span>
		{/each}
	</span>
</span>
