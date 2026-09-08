<script lang="ts">
	import { tip } from '$lib/popover';
	let { class: cls = '', label = 'No image' }: { class?: string; label?: string } = $props();
</script>

<div
	class="flex items-center justify-center border border-border bg-black/[0.035] {cls}"
	role="img"
	aria-label={label}
	use:tip={label}
>
	<img src="/basically-logo.svg" alt="" class="h-[44%] w-[44%] object-contain opacity-20 grayscale dark:invert" />
</div>
