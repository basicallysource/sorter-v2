<script lang="ts">
	import PageMeta from '$lib/components/PageMeta.svelte';
	import Requirements from '$lib/components/Requirements.svelte';

	let { data } = $props();

	const p = $derived(data.page);
	const fm = $derived(p.fm);
	const title = $derived(fm.title ? `${fm.title} | ${data.site.title}` : data.site.title);
	const description = $derived(fm.description ?? fm.lede ?? data.site.description);

	const BADGE_LABELS: Record<string, string> = {
		'how-to': 'How-to guide',
		installation: 'Installation',
		tutorial: 'Tutorial',
		reference: 'Reference',
		explanation: 'Explanation',
		troubleshooting: 'Troubleshooting',
		architecture: 'Architecture'
	};
	const badge = $derived(
		fm.type && fm.type !== 'landing' ? (BADGE_LABELS[fm.type] ?? fm.type) : null
	);

	let contentEl: HTMLElement | undefined = $state();

	// Copy buttons on code blocks (port of docs/assets/copy-code.js).
	$effect(() => {
		p.url; // rerun per page — {@html} replaces the DOM on navigation
		if (!contentEl) return;
		for (const pre of contentEl.querySelectorAll('pre')) {
			if (pre.parentElement?.classList.contains('code-block')) continue;
			const wrap = document.createElement('div');
			wrap.className = 'code-block';
			pre.replaceWith(wrap);
			wrap.appendChild(pre);
			const btn = document.createElement('button');
			btn.type = 'button';
			btn.className = 'copy-code-button';
			btn.setAttribute('aria-label', 'Copy code');
			btn.innerHTML =
				'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square"><rect x="9" y="9" width="12" height="12"></rect><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"></path></svg>';
			btn.addEventListener('click', async () => {
				await navigator.clipboard.writeText(pre.innerText.replace(/\n$/, ''));
				btn.classList.add('is-copied');
				setTimeout(() => btn.classList.remove('is-copied'), 1500);
			});
			wrap.appendChild(btn);
		}
	});
</script>

<svelte:head>
	<title>{title}</title>
	<meta name="description" content={description} />
	<meta property="og:site_name" content={data.site.title} />
	<meta property="og:type" content={fm.title ? 'article' : 'website'} />
	<meta property="og:title" content={fm.title ?? data.site.title} />
	<meta property="og:description" content={description} />
	<meta property="og:url" content={data.site.url + p.url} />
	{#if p.ogImage}
		<meta property="og:image" content={p.ogImage} />
		<meta name="twitter:card" content="summary_large_image" />
	{:else}
		<meta name="twitter:card" content="summary" />
	{/if}
</svelte:head>

{#if fm.kicker}
	<p class="kicker">{fm.kicker}</p>
{/if}

{#if fm.title}
	{#if badge}
		<div class="page-title-row">
			<h1>{fm.title}</h1>
			<span class="page-type-badge page-type-{fm.type}">{badge}</span>
		</div>
	{:else}
		<h1>{fm.title}</h1>
	{/if}
{/if}

{#if fm.lede}
	<p class="lede">{fm.lede}</p>
{/if}

{#if p.author}
	<p class="page-author">
		<span class="page-author-label">Author</span>
		{#if p.author.url}
			<a href={p.author.url} target="_blank" rel="noopener">{p.author.name}</a>
		{:else}
			{p.author.name}
		{/if}
	</p>
{/if}

<Requirements parts={p.parts} tools={p.tools} />

<div class="md-content" bind:this={contentEl}>
	{@html p.html}
</div>

<PageMeta {fm} />
