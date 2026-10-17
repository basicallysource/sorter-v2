<!--
	docs/layout.md#the-shell. The first level of an app's navigation: the
	mark, the app's pages, and on the right what applies everywhere (the
	machine, its status, the profile). Light or dark is a setting, never a
	control here. It is a surface and owns the one line under it; nothing
	below it draws a line at its top. The current page's primary mark (as
	wide as the link, --indicator thick) sits on that line, replacing it.

	A page that has views of its own (Records: Overview, Runs, Pieces) lists
	them as `children`: the page's name stays a link to its first view, and
	a chevron beside it opens a menu of the views, the current one checked, so
	a view is one click from anywhere. The same views are the page's Tabs.
	Folded, the page is a group in the menu, its views listed under its name.

	Where the links and the right side no longer fit side by side, the links
	fold into one menu, its button named for the current page. `collapse` is
	that point, as the bar's own width (the window's, in an app): `md` (768px)
	by default, wider for more pages or a busy right side. It is a container
	query, so the bar folds the same on the server and in the browser, and a
	bar shown inside a page folds by its own width. The links are never a
	scrolling box: one would clip the mark off the line and show a scroll bar.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { page } from '$app/state';
	import Button from './Button.svelte';
	import Menu from './Menu.svelte';

	type Child = { href: string; label: string };
	type Item = { href: string; label: string; children?: Child[] };

	let {
		items,
		brand,
		end,
		sticky = true,
		collapse = 'md'
	}: {
		items: Item[];
		brand: Snippet;
		end?: Snippet;
		// False where it is shown inside a page rather than at its top.
		sticky?: boolean;
		// Below this width the links fold into the menu: 640, 768, 1024, 1280px.
		collapse?: 'sm' | 'md' | 'lg' | 'xl';
	} = $props();

	const current = $derived(
		items
			.filter((i) =>
				i.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(i.href)
			)
			.sort((a, b) => b.href.length - a.href.length)[0]?.href
	);

	// The view of the current page that the address is on. A page's first view
	// has the page's own address, so it is the one only that exact address names.
	function currentView(item: Item): string | undefined {
		return (item.children ?? [])
			.filter((c) =>
				c.href === item.href
					? page.url.pathname === c.href
					: page.url.pathname === c.href || page.url.pathname.startsWith(c.href + '/')
			)
			.sort((a, b) => b.href.length - a.href.length)[0]?.href;
	}

	function views(item: Item) {
		const here = item.href === current ? currentView(item) : undefined;
		return (item.children ?? []).map((c) => ({
			label: c.label,
			href: c.href,
			checked: c.href === here
		}));
	}

	// Whole class names, so Tailwind sees them.
	const wide = $derived(
		{
			sm: '@max-[40rem]:hidden',
			md: '@max-[48rem]:hidden',
			lg: '@max-[64rem]:hidden',
			xl: '@max-[80rem]:hidden'
		}[collapse]
	);
	const narrow = $derived(
		{
			sm: '@min-[40rem]:hidden',
			md: '@min-[48rem]:hidden',
			lg: '@min-[64rem]:hidden',
			xl: '@min-[80rem]:hidden'
		}[collapse]
	);

	function mark(on: boolean) {
		return on
			? 'font-medium text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-(--indicator) after:bg-primary'
			: 'text-ink-muted hover:text-ink';
	}
</script>

<header class="@container {sticky ? 'sticky top-0 z-30' : ''} border-b border-line bg-surface">
	<div class="flex h-(--size-topbar) items-center gap-6 px-4 sm:px-6">
		<div class="flex shrink-0 items-center">{@render brand()}</div>
		{#if items.length}
			<nav aria-label="Main" class="flex h-full min-w-0 items-stretch">
				<div class="flex h-full min-w-0 items-stretch gap-1 {wide}">
					{#each items as item (item.href)}
						{@const on = item.href === current}
						{#if item.children?.length}
							<div class="relative -mb-px flex items-center pr-1 transition-colors {mark(on)}">
								<a
									href={item.href}
									aria-current={on ? 'page' : undefined}
									class="flex h-full items-center pr-1 pl-3 text-sm whitespace-nowrap"
								>
									{item.label}
								</a>
								<Menu
									label="{item.label} views"
									placement="bottom-start"
									width="12rem"
									items={views(item)}
								>
									{#snippet trigger(props)}
										<Button
											{...props}
											variant="ghost"
											size="sm"
											icon={ChevronDown}
											label="{item.label} views"
										/>
									{/snippet}
								</Menu>
							</div>
						{:else}
							<a
								href={item.href}
								aria-current={on ? 'page' : undefined}
								class="relative -mb-px flex items-center px-3 text-sm whitespace-nowrap transition-colors {mark(
									on
								)}"
							>
								{item.label}
							</a>
						{/if}
					{/each}
				</div>
				<div class="-ml-3 flex min-w-0 items-center {narrow}">
					<Menu
						label="Pages"
						placement="bottom-start"
						width="14rem"
						items={items.map((i) =>
							i.children?.length
								? { group: i.label, items: views(i) }
								: { label: i.label, href: i.href, checked: i.href === current }
						)}
					>
						{#snippet trigger(props)}
							<Button {...props} variant="ghost" size="sm">
								{items.find((i) => i.href === current)?.label ?? 'Pages'}
								<ChevronDown size={14} class="text-ink-muted" />
							</Button>
						{/snippet}
					</Menu>
				</div>
			</nav>
		{/if}
		{#if end}<div class="ml-auto flex shrink-0 items-center gap-2">{@render end()}</div>{/if}
	</div>
</header>
