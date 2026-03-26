<script>
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl } from '$lib/backend';
	import { Eye, EyeOff } from 'lucide-svelte';

	let { camera } = $props();

	const SPLIT_FEEDER_ROLES = ['c_channel_2', 'c_channel_3', 'carousel'];

	const ctx = getMachineContext();

	let show_annotated = $state(false);

	const frame = $derived(ctx.frames.get(camera));
	const image_src = $derived(() => {
		if (!frame) return null;
		const data = show_annotated && frame.annotated ? frame.annotated : frame.raw;
		return `data:image/jpeg;base64,${data}`;
	});

	const mjpeg_src = $derived(
		SPLIT_FEEDER_ROLES.includes(camera) ? `${backendHttpBaseUrl}/api/cameras/feed/${camera}` : null
	);
</script>

<div
	class="dark:border-border-dark dark:bg-bg-dark flex h-full flex-col border border-border bg-bg"
>
	<div
		class="dark:bg-surface-dark flex flex-shrink-0 items-center justify-between bg-surface px-2 py-1 text-xs"
	>
		<span class="dark:text-text-muted-dark text-text-muted">{camera}</span>
		{#if frame}
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
		{/if}
	</div>
	<div class="dark:bg-surface-dark relative flex-1 overflow-hidden bg-surface">
		{#if image_src()}
			<img src={image_src()} alt={camera} class="absolute inset-0 h-full w-full object-contain" />
		{:else if mjpeg_src}
			<img src={mjpeg_src} alt={camera} class="absolute inset-0 h-full w-full object-contain" />
		{:else}
			<div
				class="dark:text-text-muted-dark flex h-full items-center justify-center text-text-muted"
			>
				No frame
			</div>
		{/if}
	</div>
</div>
