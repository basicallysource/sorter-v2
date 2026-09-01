<script lang="ts">
	import { goto } from '$app/navigation';

	type NavItem = { title: string; url: string; lede?: string; children?: NavItem[] };
	type NavGroup = { title: string; pages: NavItem[] };
	type NavSection = {
		id: string;
		title: string;
		url: string;
		description?: string;
		pages: NavItem[];
		groups?: NavGroup[];
	};
	type SearchEntry = { title: string; url: string; lede?: string; section: string; crumb: string[] };

	let { nav, open = $bindable(false) }: { nav: NavSection[]; open: boolean } = $props();

	let dialog: HTMLDialogElement | undefined = $state();
	let inputEl: HTMLInputElement | undefined = $state();
	let query = $state('');
	let selected = $state(0);

	function flattenItems(items: NavItem[], crumb: string[]): SearchEntry[] {
		const out: SearchEntry[] = [];
		for (const item of items) {
			out.push({
				title: item.title,
				url: item.url,
				lede: item.lede,
				section: crumb[0] ?? '',
				crumb: crumb.slice(1)
			});
			if (item.children) out.push(...flattenItems(item.children, [...crumb, item.title]));
		}
		return out;
	}

	const index: SearchEntry[] = $derived.by(() => {
		const seen = new Set<string>();
		const all = nav.flatMap((section) => [
			{ title: section.title, url: section.url, lede: section.description, section: section.title, crumb: [] },
			...flattenItems(section.pages, [section.title]),
			...(section.groups ?? []).flatMap((g) => flattenItems(g.pages, [section.title, g.title]))
		]);
		return all.filter((e) => {
			if (seen.has(e.url)) return false;
			seen.add(e.url);
			return true;
		});
	});

	const results: SearchEntry[] = $derived(
		query.trim() === ''
			? index.slice(0, 8)
			: index
					.filter(
						(e) =>
							e.title.toLowerCase().includes(query.toLowerCase()) ||
							e.url.toLowerCase().includes(query.toLowerCase())
					)
					.slice(0, 12)
	);

	$effect(() => {
		if (open) {
			query = '';
			selected = 0;
			dialog?.showModal();
			requestAnimationFrame(() => inputEl?.focus());
		} else {
			dialog?.close();
		}
	});

	$effect(() => {
		// Reset selection whenever query changes
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		query;
		selected = 0;
	});

	function close() {
		open = false;
	}

	function navigate(url: string) {
		close();
		goto(url);
	}

	function onInputKeydown(e: KeyboardEvent) {
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selected = Math.min(selected + 1, results.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selected = Math.max(selected - 1, 0);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (results[selected]) navigate(results[selected].url);
		}
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<dialog
	class="search-dialog"
	bind:this={dialog}
	onclose={() => { open = false; }}
	onclick={(e) => { if (e.target === dialog) close(); }}
	onkeydown={(e) => { if (e.key === 'Escape') close(); }}
>
	<div class="search-panel" role="presentation">
		<div class="search-input-row">
			<svg class="search-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
				<circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.6"/>
				<path d="M13 13l3.5 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
			</svg>
			<input
				bind:this={inputEl}
				class="search-input"
				type="search"
				placeholder="Search docs..."
				autocomplete="off"
				spellcheck="false"
				bind:value={query}
				onkeydown={onInputKeydown}
			/>
			<button type="button" class="search-esc-hint" onclick={close}>esc</button>
		</div>

		{#if results.length > 0}
			<ul class="search-results" role="listbox" aria-label="Search results">
				{#each results as entry, i (entry.url)}
					<li
						class="search-result"
						class:search-result--selected={i === selected}
						role="option"
						aria-selected={i === selected}
						onmouseenter={() => { selected = i; }}
					>
						<a
							class="search-result-link"
							href={entry.url}
							onclick={(e) => { e.preventDefault(); navigate(entry.url); }}
							tabindex="-1"
						>
							<span class="search-result-row">
								<span class="search-result-title">{entry.title}</span>
								{#if entry.crumb.length > 0 || entry.section}
									<span class="search-result-crumb">
										{[entry.section, ...entry.crumb].filter(Boolean).join(' › ')}
									</span>
								{/if}
							</span>
							{#if entry.lede}
								<span class="search-result-lede">{entry.lede}</span>
							{/if}
						</a>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="search-empty">No results for <strong>"{query}"</strong></p>
		{/if}

		<div class="search-footer">
			<span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
			<span><kbd>↵</kbd> open</span>
			<span><kbd>esc</kbd> close</span>
		</div>
	</div>
</dialog>
