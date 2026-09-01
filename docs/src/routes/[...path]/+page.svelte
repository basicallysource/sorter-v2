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

	// A chain link, the conventional icon for "a link to this heading". Not the
	// two-rectangle copy glyph the code blocks use: that one means "copy this
	// text", which is a different thing, and zed0 said so when the first version
	// of this reused it.
	const LINK_ICON =
		'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>';

	// Copied-state feedback, shared by both buttons.
	function flashCopied(btn: HTMLElement) {
		btn.classList.add('is-copied');
		setTimeout(() => btn.classList.remove('is-copied'), 1500);
	}

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
				flashCopied(btn);
			});
			wrap.appendChild(btn);
		}
	});

	// Copy-link buttons beside article headings, so a section can be linked to
	// directly instead of "scroll down to the bit about heat inserts". Every
	// heading already carries an id (rehype-slug, in src/lib/server/content.ts),
	// so the id is the anchor, not something invented here.
	$effect(() => {
		p.url; // rerun per page — {@html} replaces the DOM on navigation
		if (!contentEl) return;
		for (const h of contentEl.querySelectorAll<HTMLElement>('h2[id], h3[id], h4[id]')) {
			if (h.dataset.headingLink) continue;
			h.dataset.headingLink = '1';
			const btn = document.createElement('button');
			btn.type = 'button';
			btn.className = 'heading-link-button';
			// A step heading (`{% include step.html %}`) is a column flex of "Step N"
			// over the title, so the button goes inside the title span; appending it
			// to the heading itself would stack it underneath as a third row.
			const target = h.querySelector<HTMLElement>('.step-title') ?? h;
			const label = target.textContent?.replace(/\s+/g, ' ').trim() ?? '';
			btn.setAttribute('aria-label', label ? `Copy link to "${label}"` : 'Copy link to this section');
			btn.title = 'Copy link to this section';
			btn.innerHTML = LINK_ICON;
			btn.addEventListener('click', async () => {
				// Absolute, and built from the current page rather than the address
				// bar as it stands, so a link copied off a page you arrived at via
				// another anchor still points at this heading and nothing else.
				const url = `${location.origin}${location.pathname}#${h.id}`;
				try {
					await navigator.clipboard.writeText(url);
				} catch {
					// No clipboard (insecure context, or the user refused): put the
					// anchor in the address bar instead so it can still be copied.
					location.hash = h.id;
					return;
				}
				flashCopied(btn);
			});
			target.appendChild(btn);
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

<!-- A caveat about the whole page (frontmatter `warning:`) goes above the parts
     block, so it is read before the contents rather than after them. -->
{#if p.warning}
	<div class="callout callout-warning page-warning">
		<span class="callout-icon" aria-hidden="true">⚠</span>
		<div class="page-warning-body">{@html p.warning}</div>
	</div>
{/if}

<Requirements parts={p.parts} tools={p.tools} />

<div class="md-content" bind:this={contentEl}>
	{@html p.html}
</div>

<PageMeta {fm} />
