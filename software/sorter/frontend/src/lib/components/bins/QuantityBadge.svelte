<script lang="ts">
	let { count, size = 'lg' }: { count: number; size?: 'sm' | 'lg' } = $props();
</script>

<!-- A chip over a piece's picture, so it sits in a dark subtree (docs/surfaces.md, Media). -->
<span
	class="dark num absolute rounded-badge bg-scrim font-medium text-ink {size === 'sm'
		? 'top-1 right-1 px-1 text-xs'
		: 'top-2 right-2 px-2 py-0.5 text-sm'}"
>
	{size === 'sm' ? `×${count}` : count}
</span>
