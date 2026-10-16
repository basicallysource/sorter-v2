<script lang="ts">
	import { ExternalLink } from 'lucide-svelte';

	// Opens a published .3mf straight in Bambu Studio through its URL handler.
	// Bambu Studio rejects a bare .stl ("unknown file format"), so only pass plates.
	let { href, size = 'md' }: { href: string; size?: 'sm' | 'md' } = $props();

	const box = { sm: 'h-6 gap-1 px-1.5 text-xs', md: 'h-9 gap-2 px-3 text-sm' };
	const icon = { sm: 12, md: 14 };
</script>

<a
	href="bambustudio://open?file={encodeURIComponent(href)}"
	title="Open this plate in Bambu Studio (needs Bambu Studio installed)"
	class="setup-button-secondary inline-flex items-center whitespace-nowrap font-semibold {box[size]}"
>
	<ExternalLink size={icon[size]} /><span>{size === 'sm' ? 'Studio' : 'Open in Bambu Studio'}</span>
</a>
