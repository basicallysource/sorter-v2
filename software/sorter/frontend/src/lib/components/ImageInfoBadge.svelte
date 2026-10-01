<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import Button from '$lib/components/ui/Button.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';

	// A small info button that opens a popover of facts about an image. The
	// caller supplies the label/value rows; this component additionally
	// measures and prepends the image's natural pixel resolution from `src`.
	let {
		src,
		rows = [],
		class: className = ''
	}: {
		src: string;
		rows?: { label: string; value: string }[];
		// Where it sits (over a picture's corner).
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

<span class="inline-flex {className}">
	<Popover label="Image info" width="16rem" placement="bottom-start">
		{#snippet trigger(props)}
			<Button {...props} size="sm" variant="ghost" icon={Info} label="Image info" />
		{/snippet}
		<KeyValue items={allRows} />
	</Popover>
</span>
