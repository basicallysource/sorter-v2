<!--
	docs/layout.md#the-shell. The first level of an app's navigation: the
	mark, the app's pages, and on the right what applies everywhere (the
	machine, its status, the profile). Light or dark is a setting, never a
	control here. It is a surface and owns the one line under it; nothing
	below it draws a line at its top. The current page's primary mark (as
	wide as the link, --indicator thick) sits on that line, replacing it.

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

	type Item = { href: string; label: string };

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
</script>

<header class="@container {sticky ? 'sticky top-0 z-30' : ''} border-b border-line bg-surface">
	<div class="flex h-(--size-topbar) items-center gap-6 px-4 sm:px-6">
		<div class="flex shrink-0 items-center">{@render brand()}</div>
		{#if items.length}
			<nav aria-label="Main" class="flex h-full min-w-0 items-stretch">
				<div class="flex h-full min-w-0 items-stretch gap-1 {wide}">
					{#each items as item (item.href)}
						{@const on = item.href === current}
						<a
							href={item.href}
							aria-current={on ? 'page' : undefined}
							class="relative -mb-px flex items-center px-3 text-sm whitespace-nowrap transition-colors
								{on
								? 'font-medium text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-(--indicator) after:bg-primary'
								: 'text-ink-muted hover:text-ink'}"
						>
							{item.label}
						</a>
					{/each}
				</div>
				<div class="-ml-3 flex min-w-0 items-center {narrow}">
					<Menu
						label="Pages"
						placement="bottom-start"
						width="14rem"
						items={items.map((i) => ({
							label: i.label,
							href: i.href,
							checked: i.href === current
						}))}
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
