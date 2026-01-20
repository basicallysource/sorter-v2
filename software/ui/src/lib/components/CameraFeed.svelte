<script>
	import { getMachineContext } from '$lib/machines/context';
	import { Eye, EyeOff } from 'lucide-svelte';

	let { camera } = $props();

	const ctx = getMachineContext();

	let show_annotated = $state(false);

	const frame = $derived(ctx.frames.get(camera));
	const image_src = $derived(() => {
		if (!frame) return null;
		const data = show_annotated && frame.annotated ? frame.annotated : frame.raw;
		return `data:image/jpeg;base64,${data}`;
	});
</script>

<div class="dark:border-border-dark dark:bg-bg-dark flex flex-col border border-border bg-bg">
	<div class="dark:bg-surface-dark flex items-center justify-between bg-surface px-2 py-1 text-xs">
		<span class="dark:text-text-muted-dark text-text-muted">{camera}</span>
		<button
			onclick={() => (show_annotated = !show_annotated)}
			class="dark:hover:bg-border-dark dark:text-text-dark p-1 text-text transition-colors hover:bg-border"
			title={show_annotated ? 'Hide annotations' : 'Show annotations'}
		>
			{#if show_annotated}
				<Eye size={14} />
			{:else}
				<EyeOff size={14} />
			{/if}
		</button>
	</div>
	{#if image_src()}
		<img src={image_src()} alt={camera} class="block max-w-full" />
	{:else}
		<div class="dark:text-text-muted-dark p-5 text-center text-text-muted">No frame</div>
	{/if}
</div>
