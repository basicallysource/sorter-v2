<script lang="ts">
	import { ExternalLink } from 'lucide-svelte';

	// Opens a published STL straight in Bambu Studio through its URL handler.
	let { href }: { href: string } = $props();
</script>

<a
	href="bambustudio://open?url={href}"
	title="Open this STL in Bambu Studio (needs Bambu Studio installed)"
	class="setup-button-secondary inline-flex h-8 items-center gap-1.5 whitespace-nowrap px-3 text-xs font-semibold"
>
	<ExternalLink size={14} /><span>Open in Bambu Studio</span>
</a>
