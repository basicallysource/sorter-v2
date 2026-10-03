<!-- One of docs/*.md, rendered, with the other docs listed after it. -->
<script lang="ts">
	import FileText from '@lucide/svelte/icons/file-text';
	import { docs, render, type Doc } from '$lib/site/docs';

	let { doc }: { doc: Doc } = $props();
	const html = $derived(render(doc.source));
</script>

<svelte:head><title>{doc.title} · Sorter design system</title></svelte:head>

<div class="mb-6 flex items-center gap-1.5 text-sm text-ink-muted">
	<FileText size={14} />
	<a href="/docs" class="hover:text-ink">docs</a>/<span class="text-ink">{doc.slug}.md</span>
</div>

<article class="doc max-w-3xl">
	{@html html}
</article>

<nav aria-label="Docs" class="mt-16 max-w-3xl">
	<div class="label mb-2">All docs</div>
	<ul class="grid gap-px overflow-hidden rounded-panel bg-line sm:grid-cols-2">
		{#each docs as other (other.slug)}
			<li class="bg-surface">
				<a
					href={other.slug === 'README' ? '/docs' : `/docs/${other.slug}`}
					aria-current={other.slug === doc.slug ? 'page' : undefined}
					class="flex items-baseline justify-between gap-3 px-4 py-2.5 text-sm transition-colors hover:bg-hover
						{other.slug === doc.slug ? 'bg-primary-soft font-medium text-primary-ink' : 'text-ink'}"
				>
					<span class="truncate">{other.title}</span>
					<span class="shrink-0 font-mono text-xs text-ink-muted">{other.slug}.md</span>
				</a>
			</li>
		{/each}
		{#if docs.length % 2}<li class="hidden bg-surface sm:block" aria-hidden="true"></li>{/if}
	</ul>
</nav>

<style>
	.doc :global(h1) {
		font-size: 1.5rem;
		line-height: 2rem;
		font-weight: 600;
		letter-spacing: -0.025em;
		margin-bottom: 1rem;
	}
	.doc :global(h2) {
		font-size: 1.25rem;
		line-height: 1.75rem;
		font-weight: 600;
		letter-spacing: -0.025em;
		margin: 2.5rem 0 0.75rem;
		scroll-margin-top: 4rem;
	}
	.doc :global(h3) {
		font-size: 1rem;
		line-height: 1.5rem;
		font-weight: 600;
		margin: 1.75rem 0 0.5rem;
		scroll-margin-top: 4rem;
	}
	.doc :global(p),
	.doc :global(li),
	.doc :global(td),
	.doc :global(th) {
		font-size: 0.875rem;
		line-height: 1.5rem;
	}
	.doc :global(p),
	.doc :global(ul),
	.doc :global(ol),
	.doc :global(pre),
	.doc :global(table),
	.doc :global(blockquote) {
		margin: 0 0 1rem;
	}
	.doc :global(ul),
	.doc :global(ol) {
		padding-left: 1.25rem;
	}
	.doc :global(ul) {
		list-style: square;
	}
	.doc :global(ol) {
		list-style: decimal;
	}
	.doc :global(li + li) {
		margin-top: 0.25rem;
	}
	.doc :global(li > ul),
	.doc :global(li > ol) {
		margin: 0.25rem 0 0;
	}
	.doc :global(strong) {
		font-weight: 600;
	}
	.doc :global(a) {
		color: var(--primary-ink);
		text-underline-offset: 2px;
	}
	.doc :global(a:hover) {
		text-decoration: underline;
	}
	.doc :global(code) {
		font-family: var(--font-mono);
		font-size: 0.8125rem;
		background: var(--well);
		padding: 0.0625rem 0.25rem;
	}
	.doc :global(pre) {
		background: var(--well);
		padding: 1rem 1.25rem;
		overflow-x: auto;
	}
	.doc :global(pre code) {
		background: none;
		padding: 0;
		font-size: 0.875rem;
		line-height: 1.5rem;
	}
	.doc :global(table) {
		display: block;
		overflow-x: auto;
		border-collapse: collapse;
		background: var(--surface);
	}
	.doc :global(th) {
		background: var(--well);
		padding: 0.5rem 1rem;
		text-align: left;
		font-weight: 600;
		color: var(--ink-muted);
		white-space: nowrap;
	}
	.doc :global(td) {
		padding: 0.5rem 1rem;
		vertical-align: top;
	}
	.doc :global(tbody tr + tr td) {
		border-top: 1px solid var(--line);
	}
	.doc :global(blockquote) {
		background: var(--well);
		padding: 0.75rem 1rem;
		color: var(--ink-muted);
	}
	.doc :global(hr) {
		border-top: 1px solid var(--line);
		margin: 2rem 0;
	}
</style>
