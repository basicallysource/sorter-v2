<script lang="ts">
	import { goto } from '$app/navigation';
	import { Search, X } from 'lucide-svelte';
	import Kbd from './Kbd.svelte';
	import SearchResult from './SearchResult.svelte';
	import { palette } from '$lib/search.svelte';
	import {
		CATALOG_INDEX,
		SCOPES,
		itemByKey,
		readScopePrefix,
		searchCatalog,
		type Hit,
		type Ranked,
		type SearchItem,
		type SearchScope
	} from '$lib/search';

	// The palette. One instance for the whole site, mounted by the layout.
	//
	// Everything is recomputed on every keystroke against the in-memory index —
	// a few hundred entries, so there is no debounce and no loading state, which
	// is the entire feel of the thing: the list moves under your fingers as fast
	// as you can type four characters off a print.

	const open = $derived(palette.open);

	// `#s1qc` / `id:s1qc` force the id scope from the keyboard, so the chips are
	// a convenience rather than the only way in.
	const parsed = $derived(readScopePrefix(palette.query));
	const scope = $derived<SearchScope>(parsed.scope ?? palette.scope);
	const query = $derived(parsed.query);
	const typing = $derived(query.trim().length > 0);

	const results = $derived<Ranked<SearchItem>[]>(typing ? searchCatalog(query, scope) : []);

	// With nothing typed the palette is a launcher, not a filter: where you were,
	// then where you can go.
	const recents = $derived(palette.recent.map(itemByKey).filter((i): i is SearchItem => !!i));
	const pages = $derived(CATALOG_INDEX.filter((i) => i.kind === 'page'));
	const idle = $derived<SearchItem[]>([...recents, ...pages.filter((p) => !recents.some((r) => r.key === p.key))]);
	/** What the list renders — a ranked hit while typing, a bare item when idle. */
	type Row = { item: SearchItem; hit: Hit | null };
	const rows = $derived<Row[]>(typing ? results : idle.map((item) => ({ item, hit: null })));

	let active = $state(0);
	let input = $state<HTMLInputElement | null>(null);
	let listEl = $state<HTMLDivElement | null>(null);

	// Any change to what is on screen puts the cursor back on the first row —
	// the top result is the answer often enough that Enter should mean it.
	$effect(() => {
		rows.length;
		query;
		scope;
		active = 0;
	});

	$effect(() => {
		if (!open) return;
		// Focus after the element exists; selecting the text means an opener that
		// passed a starting query (a list filter widening its search) can be typed
		// straight over.
		input?.focus();
		input?.select();
	});

	// Keep the cursor visible when it is driven by the keyboard rather than the
	// mouse. `nearest` so a click-then-arrow doesn't yank the list around.
	$effect(() => {
		if (!open) return;
		const el = listEl?.querySelector<HTMLElement>(`#search-opt-${active}`);
		el?.scrollIntoView({ block: 'nearest' });
	});

	// The page behind a modal must not scroll under it.
	$effect(() => {
		if (!open) return;
		const prev = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = prev;
		};
	});

	function pick(item: SearchItem) {
		palette.remember(item.key);
		palette.hide();
		palette.query = '';
		goto(item.href);
	}

	function cycleScope(dir: 1 | -1) {
		const i = SCOPES.findIndex((s) => s.id === palette.scope);
		palette.scope = SCOPES[(i + dir + SCOPES.length) % SCOPES.length].id;
	}

	function onKey(e: KeyboardEvent) {
		if (!open) return;
		switch (e.key) {
			case 'Escape':
				e.preventDefault();
				palette.hide();
				return;
			case 'ArrowDown':
				e.preventDefault();
				active = rows.length ? (active + 1) % rows.length : 0;
				return;
			case 'ArrowUp':
				e.preventDefault();
				active = rows.length ? (active - 1 + rows.length) % rows.length : 0;
				return;
			case 'Enter': {
				const row = rows[active];
				if (!row) return;
				e.preventDefault();
				pick(row.item);
				return;
			}
			case 'Tab':
				// Nothing inside the palette wants tab-order — there is one input and
				// a list you drive with the arrows — so it is free to mean "next
				// filter", which is what it means in every palette people have used.
				e.preventDefault();
				cycleScope(e.shiftKey ? -1 : 1);
				return;
		}
	}

	// A 4-character query that found nothing is almost certainly an id read off a
	// print, so say so in those terms rather than shrugging.
	const looksLikeUid = $derived(/^[a-z0-9]{4}$/i.test(query.trim()));
</script>

<svelte:window onkeydown={onKey} />

{#if open}
	<div class="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[8vh] sm:pt-[12vh]">
		<!-- click-away; a sibling of the panel so a click inside never reaches it -->
		<button class="absolute inset-0 cursor-default" aria-label="Close search" onclick={() => palette.hide()}
		></button>

		<div
			class="setup-card-shell relative flex max-h-[76vh] w-full max-w-2xl flex-col border"
			role="dialog"
			aria-modal="true"
			aria-label="Search the catalog"
		>
			<!-- ---------------------------------------------------------- the input -->
			<div class="flex items-center gap-2 border-b border-border px-3">
				<Search size={17} class="shrink-0 text-text-muted" />
				<input
					bind:this={input}
					bind:value={palette.query}
					type="text"
					spellcheck="false"
					autocomplete="off"
					autocapitalize="off"
					placeholder="Search parts, assemblies, hardware — or type the id on a print"
					aria-label="Search the catalog"
					aria-autocomplete="list"
					aria-controls="search-results"
					aria-activedescendant={rows.length ? `search-opt-${active}` : undefined}
					class="h-12 min-w-0 flex-1 bg-transparent text-[0.9375rem] text-text placeholder:text-text-muted focus:outline-none"
				/>
				{#if palette.query}
					<button
						type="button"
						class="shrink-0 text-text-muted hover:text-text"
						onclick={() => {
							palette.query = '';
							input?.focus();
						}}
						aria-label="Clear"><X size={15} /></button>
				{/if}
				<button
					type="button"
					class="setup-button-secondary hidden h-7 items-center px-2 text-xs font-semibold text-text-muted sm:inline-flex"
					onclick={() => palette.hide()}>Esc</button>
			</div>

			<!-- --------------------------------------------------------- the scopes -->
			<div class="flex flex-wrap items-center gap-1 border-b border-border px-2.5 py-1.5">
				{#each SCOPES as s (s.id)}
					<button
						type="button"
						class="border px-2 py-1 text-xs font-semibold transition-colors {scope === s.id
							? 'border-primary bg-primary/[0.08] text-primary'
							: 'border-transparent text-text-muted hover:border-border hover:text-text'}"
						aria-pressed={scope === s.id}
						title={s.hint}
						onclick={() => {
							// Picking a chip overrides a typed `#` prefix, which would
							// otherwise silently win and make the chip look broken.
							if (parsed.scope) palette.query = query;
							palette.scope = s.id;
							input?.focus();
						}}>{s.label}</button>
				{/each}
				<span class="ml-auto hidden items-center gap-1 pr-1 text-[0.6875rem] text-text-muted sm:flex">
					<Kbd>Tab</Kbd> to switch
				</span>
			</div>

			<!-- --------------------------------------------------------- the results -->
			<div bind:this={listEl} id="search-results" role="listbox" aria-label="Results" class="min-h-0 flex-1 overflow-y-auto py-1">
				{#if !typing}
					<p class="px-3 pb-1 pt-2 text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
						{recents.length ? 'Recent and pages' : 'Jump to'}
					</p>
				{/if}

				{#each rows as row, i (row.item.key)}
					<SearchResult
						id="search-opt-{i}"
						item={row.item}
						hit={row.hit}
						active={i === active}
						onpick={() => pick(row.item)}
						onhover={() => (active = i)}
					/>
				{/each}

				{#if typing && !rows.length}
					<div class="px-4 py-8 text-center">
						<p class="text-sm text-text">
							{#if looksLikeUid}
								Nothing in the catalog carries the id
								<span class="font-mono font-bold tracking-wider text-text">{query.trim().toUpperCase()}</span>.
							{:else}
								No match for <span class="font-semibold">{query.trim()}</span>.
							{/if}
						</p>
						<p class="mt-1.5 text-xs text-text-muted">
							{#if scope !== 'all'}
								Only <b>{SCOPES.find((s) => s.id === scope)?.label}</b> is being searched —
								<button class="font-semibold text-primary hover:text-primary-hover" onclick={() => {
									if (parsed.scope) palette.query = query;
									palette.scope = 'all';
								}}>search everything</button>.
							{:else if looksLikeUid}
								Ids are stamped on parts printed with "engrave version ids" on. Check for a
								0/O or 1/l mix-up.
							{:else}
								Try fewer words, or part of the name.
							{/if}
						</p>
					</div>
				{/if}

				{#if !typing}
					<p class="border-t border-border px-3 py-2.5 text-xs text-text-muted">
						Holding a printed part? Type the four characters engraved on it to land on exactly
						the revision you are holding — including superseded ones.
					</p>
				{/if}
			</div>

			<!-- ---------------------------------------------------------- the hints -->
			<div
				class="hidden items-center gap-4 border-t border-border bg-[var(--color-bg)] px-3 py-1.5 text-[0.6875rem] text-text-muted sm:flex"
			>
				<span class="inline-flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> move</span>
				<span class="inline-flex items-center gap-1"><Kbd>↵</Kbd> open</span>
				<span class="inline-flex items-center gap-1"><Kbd>#</Kbd> id only</span>
				{#if typing}
					<span class="ml-auto">{results.length}{results.length === 40 ? '+' : ''} result{results.length === 1 ? '' : 's'}</span>
				{/if}
			</div>
		</div>
	</div>
{/if}
