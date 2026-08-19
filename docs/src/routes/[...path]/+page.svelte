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

	// Bills of materials on the WireViz page.
	//
	// The BOMs are build artifacts in the assets bucket, not files in this repo,
	// so they are fetched in the browser rather than baked in at build time. A
	// build-time fetch would race the harness render job: both start on the same
	// push, and a docs build that wins the race would bake in a missing or stale
	// table and keep serving it until something else triggers a deploy. Fetching
	// here cannot go silently stale, and the TSV download link above each table
	// is the fallback when this does not run.
	$effect(() => {
		p.url; // rerun per page — {@html} replaces the DOM on navigation
		if (!contentEl) return;
		for (const host of contentEl.querySelectorAll<HTMLElement>('[data-bom]')) {
			if (host.dataset.bomDone) continue;
			host.dataset.bomDone = '1';
			const url = host.dataset.bom!;
			const fail = (msg: string) => {
				host.innerHTML = '';
				const p = document.createElement('p');
				p.className = 'bom-status';
				p.textContent = msg;
				host.appendChild(p);
			};
			fetch(url)
				.then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
				.then((tsv) => {
					const rows = tsv
						.split('\n')
						.map((line) => line.replace(/\r$/, ''))
						.filter((line) => line.trim() !== '')
						.map((line) => line.split('\t'));
					if (rows.length < 2) return fail('This drawing has no bill of materials.');
					const [head, ...body] = rows;
					const width = Math.max(head.length, ...body.map((r) => r.length));
					const table = document.createElement('table');
					const thead = table.createTHead().insertRow();
					for (let i = 0; i < width; i++) {
						const th = document.createElement('th');
						th.textContent = head[i] ?? '';
						thead.appendChild(th);
					}
					const tbody = table.createTBody();
					for (const r of body) {
						const tr = tbody.insertRow();
						for (let i = 0; i < width; i++) tr.insertCell().textContent = r[i] ?? '';
					}
					host.innerHTML = '';
					host.appendChild(table);
				})
				.catch(() => fail('The bill of materials could not be loaded. Use the BOM (TSV) link above.'));
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

{#if p.authors?.length || p.contributors?.length}
	<div class="page-credits">
		{#if p.authors?.length}
			<p class="page-author">
				<span class="page-author-label">{p.authors.length === 1 ? 'Author' : 'Authors'}</span>
				{#each p.authors as author, i}
					{#if i > 0}{i === p.authors.length - 1 ? ' and ' : ', '}{/if}
					{#if author.url}
						<a href={author.url} target="_blank" rel="noopener">{author.name}</a>
					{:else}
						{author.name}
					{/if}
				{/each}
			</p>
		{/if}
		{#if p.contributors?.length}
			<p class="page-author">
				<span class="page-author-label">{p.contributors.length === 1 ? 'Contributor' : 'Contributors'}</span>
				{#each p.contributors as contributor, i}
					{#if i > 0}{i === p.contributors.length - 1 ? ' and ' : ', '}{/if}
					{#if contributor.url}
						<a href={contributor.url} target="_blank" rel="noopener">{contributor.name}</a>
					{:else}
						{contributor.name}
					{/if}
				{/each}
			</p>
		{/if}
	</div>
{/if}

<Requirements parts={p.parts} tools={p.tools} />

<div class="md-content" bind:this={contentEl}>
	{@html p.html}
</div>

<PageMeta {fm} />
