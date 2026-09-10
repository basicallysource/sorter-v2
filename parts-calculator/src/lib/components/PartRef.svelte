<script lang="ts">
	// A printed part named in the middle of a sentence, as a link to its page.
	// The counterpart of HardwareRef, and coloured where that one is not: a
	// fastener carries its own head silhouette and thread colour, so it reads as
	// a thing already, while a part is just a name and needs to look clickable to
	// be found. This is how one part points at another — a cap that plugs the
	// hole an older revision of a rotor has.
	import type { Part } from '$lib/filament';

	let { part }: { part: Part } = $props();
</script>

<a
	class="text-primary hover:text-primary-hover hover:underline"
	href="/part/{part.id}"
	title="View {part.name} details">{part.name}</a
>
