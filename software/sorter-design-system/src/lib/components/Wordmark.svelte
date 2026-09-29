<!--
	docs/layout.md#top-bar. The app's name in the top bar: a primary square
	and the name in capitals. `name` is "Sorter" on a machine, "Hive" on Hive.
-->
<script lang="ts">
	let { name = 'Sorter', href = '/' }: { name?: string; href?: string } = $props();
</script>

<a {href} class="flex items-center gap-2.5 text-ink">
	<span class="size-4 bg-primary" aria-hidden="true"></span>
	<span class="text-base font-bold tracking-wider uppercase">{name}</span>
</a>
