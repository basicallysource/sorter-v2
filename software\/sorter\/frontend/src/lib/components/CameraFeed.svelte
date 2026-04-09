<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { Eye, EyeOff } from 'lucide-svelte';

	let { camera, label = '', baseUrl = '', showHeader = true, framed = true } = $props();

	const MJPEG_ROLES = [
		'c_channel_2',
		'c_channel_3',
		'carousel',
		'classification_top',
		'classification_bottom'
	];

	const ctx = getMachineContext();

	let show_annotated = $state(true);

	function effectiveBaseUrl(): string {
		if (baseUrl) return baseUrl;
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	const frame = $derived(ctx.frames.get(camera));
	const image_src = $derived(() => {
		if (!frame) return null;
		const data = show_annotated && frame.annotated ? frame.annotated : frame.raw;
		return `data:image/jpeg;base64,${data}`;
	});

	const mjpeg_src = $derived(
		MJPEG_ROLES.includes(camera)
			? `${effectiveBaseUrl()}/api/cameras/feed/${camera}`
			: null
	);

	const display_label = $derived(label || camera);

	function abortMjpeg(node: HTMLImageElement) {
		return { destroy() { node.src = ''; } };
	}
</script>

	<div class={`flex h-full flex-col bg-bg ${framed ? 'border border-border' : ''}`}>
	{#if showHeader}
		<div class="flex flex-shrink-0 items-center justify-between bg-surface px-3 py-1.5 text-sm">
			<span class="text-text-muted">{display_label}</span>
			{#if frame}
				<button
					onclick={() => (show_annotated = !show_annotated)}
					class="p-1 text-text transition-colors hover:bg-border"
					title={show_annotated ? 'Show raw' : 'Show annotations'}
				>
					{#if show_annotated}
						<Eye size={14} />
					{:else}
						<EyeOff size={14} />
					{/if}
				</button>
			{/if}
		</div>
	{/if}
	<div class="relative flex-1 overflow-hidden bg-surface">
		{#if image_src()}
			<img src={image_src()} alt={display_label} class="absolute inset-0 h-full w-full object-contain" />
		{:else if mjpeg_src}
			<img use:abortMjpeg src={mjpeg_src} alt={display_label} class="absolute inset-0 h-full w-full object-contain" />
		{:else}
			<div
				class="flex h-full items-center justify-center text-text-muted"
			>
				No frame
			</div>
		{/if}
	</div>
</div>
