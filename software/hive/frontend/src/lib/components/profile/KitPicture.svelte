<!--
	A kit's picture: its own, its set's, or its first part's, shown whole on
	the plane it sits on. A kit with none shows a quiet tile with the kit
	mark, so a list of kits does not have blank squares among its pictures.
	`class` gives it its size (`size-16`).
-->
<script lang="ts">
	import Boxes from '@lucide/svelte/icons/boxes';
	import PartImage from '../PartImage.svelte';

	let { src = null, class: className = '' }: { src?: string | null; class?: string } = $props();
</script>

{#if src}
	<PartImage {src} class={className} />
{:else}
	<span
		aria-hidden="true"
		class="flex items-center justify-center rounded-control bg-hover text-ink-faint {className}"
	>
		<Boxes size={24} />
	</span>
{/if}
