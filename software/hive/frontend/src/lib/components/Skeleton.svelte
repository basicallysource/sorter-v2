<!--
	docs/loading.md#skeleton. A placeholder the shape of content that is on
	its way, when that shape is known: the rows of a list, a picture, a
	number. It fades gently and never spins. Put `aria-busy="true"` on the
	region that is loading. Anything whose shape is not known shows the
	Spinner instead.

	<Skeleton class="h-4 w-40" />
-->
<script lang="ts">
	let { class: className = '' }: { class?: string } = $props();
</script>

<div aria-hidden="true" class="animate-pulse rounded-item bg-pressed {className}"></div>
