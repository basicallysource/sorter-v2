<script lang="ts">
	import FileText from '@lucide/svelte/icons/file-text';

	let { title, lead, doc }: { title: string; lead?: string; doc?: string } = $props();
</script>

<header class="mb-10">
	<h1 class="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
	{#if lead}<p class="mt-2 max-w-2xl text-base text-ink-muted">{lead}</p>{/if}
	{#if doc}
		<a
			href="/docs/{doc}"
			class="mt-3 inline-flex items-center gap-1.5 text-sm text-primary-ink hover:underline"
		>
			<FileText size={14} />docs/{doc}.md
		</a>
	{/if}
</header>
