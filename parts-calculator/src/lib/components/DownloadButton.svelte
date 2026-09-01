<script lang="ts">
	import { Download } from 'lucide-svelte';

	// Compact download link: a download arrow + label on a single line. `size` is
	// 'sm' (tight, e.g. a ".3mf" chip) or 'md' (a normal button).
	let {
		href,
		label = '',
		size = 'md',
		title
	}: { href: string; label?: string; size?: 'sm' | 'md'; title?: string } = $props();

	const box = { sm: 'h-6 gap-1 px-1.5 text-xs', md: 'h-8 gap-1.5 px-3 text-xs' };
	const icon = { sm: 12, md: 14 };
</script>

<a {href} download {title} class="setup-button-secondary inline-flex items-center whitespace-nowrap font-semibold {box[size]}">
	<Download size={icon[size]} />{#if label}<span>{label}</span>{/if}
</a>
