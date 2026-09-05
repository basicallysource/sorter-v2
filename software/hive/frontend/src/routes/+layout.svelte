<script lang="ts">
	import '../app.css';
	import { auth } from '$lib/auth.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Spinner from '$lib/components/Spinner.svelte';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import { theme } from '$lib/stores/theme';
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import ChartColumn from 'lucide-svelte/icons/chart-column';
	import ChevronDown from 'lucide-svelte/icons/chevron-down';
	import Database from 'lucide-svelte/icons/database';
	import KeyRound from 'lucide-svelte/icons/key-round';
	import Link from 'lucide-svelte/icons/link';
	import List from 'lucide-svelte/icons/list';
	import Lock from 'lucide-svelte/icons/lock';
	import LogOut from 'lucide-svelte/icons/log-out';
	import Menu from 'lucide-svelte/icons/menu';
	import Palette from 'lucide-svelte/icons/palette';
	import RefreshCw from 'lucide-svelte/icons/refresh-cw';
	import Server from 'lucide-svelte/icons/server';
	import Sparkles from 'lucide-svelte/icons/sparkles';
	import User from 'lucide-svelte/icons/user';
	import Users from 'lucide-svelte/icons/users';
	import X from 'lucide-svelte/icons/x';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();

	let dropdownOpen = $state(false);
	let menuOpen = $state(false);

	// /machine-ip-lookup is an unlisted, login-free rendezvous page used by the
	// SorterOS onboarding flow — a fresh sorter has no Hive account yet.
	const publicRoutes = ['/login', '/register', '/machine-ip-lookup', '/forget'];

	// The eight primary destinations. Kept as data so the desktop bar and the
	// mobile drawer can't drift apart.
	const navLinks: { href: string; label: string; match: (path: string) => boolean }[] = [
		{ href: '/', label: 'Dashboard', match: (p) => p === '/' },
		{ href: '/machines', label: 'My Machines', match: (p) => p === '/machines' || p.startsWith('/machines/') },
		{ href: '/profiles', label: 'Profiles', match: (p) => p.startsWith('/profiles') },
		{ href: '/sets', label: 'My Sets', match: (p) => p.startsWith('/sets') },
		{ href: '/samples', label: 'Channel Samples', match: (p) => p.startsWith('/samples') || p === '/review' },
		{ href: '/piece-bboxes', label: 'Piece Samples', match: (p) => p.startsWith('/piece-bboxes') },
		{ href: '/models', label: 'Models', match: (p) => p.startsWith('/models') },
		{ href: '/leaderboard', label: 'Leaderboard', match: (p) => p.startsWith('/leaderboard') }
	];

	function currentPathWithSearch(): string {
		return `${page.url.pathname}${page.url.search}`;
	}

	async function handleLogout() {
		dropdownOpen = false;
		menuOpen = false;
		await auth.logout();
		goto('/login');
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape') return;
		menuOpen = false;
		dropdownOpen = false;
	}

	onMount(() => {
		auth.init();
		theme.init();
	});

	$effect(() => {
		if (auth.initialized && !auth.isAuthenticated && !publicRoutes.includes(page.url.pathname)) {
			goto(`/login?${new URLSearchParams({ next: currentPathWithSearch() }).toString()}`);
		}
	});

	$effect(() => {
		if (typeof document === 'undefined') return;
		document.documentElement.classList.toggle('dark', $theme === 'dark');
	});

	// Any navigation (link click, back button, redirect) dismisses the overlays.
	$effect(() => {
		page.url.pathname;
		menuOpen = false;
		dropdownOpen = false;
	});

	// The drawer is a full-viewport overlay; letting the page behind it scroll
	// under your finger is the classic mobile-drawer bug.
	$effect(() => {
		if (typeof document === 'undefined') return;
		if (!menuOpen) return;
		const previous = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = previous;
		};
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if auth.loading && !auth.initialized}
	<div class="flex min-h-screen items-center justify-center">
		<Spinner size={32} />
	</div>
{:else}
	{#if auth.isAuthenticated}
		<nav class="border-b border-border bg-surface">
			<div class="mx-auto flex max-w-7xl items-center justify-between gap-2 px-4 py-3">
				<div class="flex min-w-0 items-center gap-3 lg:gap-6">
					<!-- The seven nav links don't fit beside the wordmark and the user
					     menu until ~1024px, so the drawer covers phones and tablets. -->
					<button
						onclick={() => { menuOpen = true; }}
						class="-ml-1 p-1 text-text-muted hover:text-text lg:hidden"
						aria-label="Open navigation menu"
						aria-expanded={menuOpen}
					>
						<Menu size={22} />
					</button>
					<a href="/" class="text-xl font-bold font-mono uppercase tracking-tight text-text">Hive</a>
					<div class="hidden gap-1 lg:flex">
						{#each navLinks as link (link.href)}
							<a
								href={link.href}
								class="px-3 py-1.5 text-sm font-medium whitespace-nowrap {link.match(page.url.pathname) ? 'border-b-2 border-primary text-primary' : 'text-text-muted hover:text-text hover:bg-bg'}"
							>
								{link.label}
							</a>
						{/each}
					</div>
				</div>
				<div class="flex shrink-0 items-center gap-1 sm:gap-3">
					<ThemeToggle />
					<div class="relative">
						<button
							onclick={() => { dropdownOpen = !dropdownOpen; }}
							class="flex max-w-[9rem] items-center gap-1 px-2 py-1.5 text-sm font-medium text-text hover:bg-bg sm:max-w-[16rem] sm:gap-2 sm:px-3"
						>
							<span class="truncate">{auth.user?.display_name ?? auth.user?.email}</span>
							<ChevronDown size={16} class="shrink-0 transition-transform {dropdownOpen ? 'rotate-180' : ''}" />
						</button>

						{#if dropdownOpen}
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<div
								class="fixed inset-0 z-40"
								onclick={() => { dropdownOpen = false; }}
								onkeydown={() => {}}
							></div>
							<div class="absolute right-0 z-50 mt-1 max-h-[80vh] w-56 max-w-[calc(100vw-2rem)] overflow-y-auto border border-border bg-surface py-1 shadow-lg">
								<div class="border-b border-border px-4 py-2">
									<p class="truncate text-sm font-medium text-text">{auth.user?.display_name}</p>
									<p class="truncate text-xs text-text-muted">{auth.user?.email}</p>
								</div>

								<a
									href="/settings"
									class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
									onclick={() => { dropdownOpen = false; }}
								>
									<User size={16} class="shrink-0 text-text-muted" />
									Profile &amp; Settings
								</a>
								<a
									href="/settings#password"
									class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
									onclick={() => { dropdownOpen = false; }}
								>
									<KeyRound size={16} class="shrink-0 text-text-muted" />
									Change Password
								</a>

								{#if auth.isAdmin}
									<div class="my-1 border-t border-border"></div>
									<div class="px-4 py-1">
										<p class="text-xs font-semibold uppercase tracking-wider text-text-muted">Admin</p>
									</div>
									<a
										href="/admin/users"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<Users size={16} class="shrink-0 text-text-muted" />
										Manage Users
									</a>
									<a
										href="/admin/machines"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<Server size={16} class="shrink-0 text-text-muted" />
										All Machines
									</a>
									<a
										href="/admin/control-data"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<Database size={16} class="shrink-0 text-text-muted" />
										Control Data
									</a>
									<a
										href="/admin/server-health"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<ChartColumn size={16} class="shrink-0 text-text-muted" />
										Server Health
									</a>
									<a
										href="/admin/teacher-jobs"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<Sparkles size={16} class="shrink-0 text-text-muted" />
										Teacher Jobs
									</a>
									<a
										href="/admin/color-models"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<Palette size={16} class="shrink-0 text-text-muted" />
										Color Models
									</a>
									<a
										href="/admin/link-models"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<Link size={16} class="shrink-0 text-text-muted" />
										Link Models
									</a>
									<a
										href="/admin/parts"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<List size={16} class="shrink-0 text-text-muted" />
										Parts Database
									</a>
									<a
										href="/admin/access-windows"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<Lock size={16} class="shrink-0 text-text-muted" />
										Access Windows
									</a>
									<a
										href="/settings/catalog-sync"
										class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg"
										onclick={() => { dropdownOpen = false; }}
									>
										<RefreshCw size={16} class="shrink-0 text-text-muted" />
										Catalog Sync
									</a>
								{/if}

								<div class="my-1 border-t border-border"></div>
								<button
									onclick={handleLogout}
									class="flex w-full items-center gap-2 px-4 py-2 text-sm text-primary hover:bg-primary-light"
								>
									<LogOut size={16} class="shrink-0" />
									Logout
								</button>
							</div>
						{/if}
					</div>
				</div>
			</div>
		</nav>

		{#if menuOpen}
			<div class="fixed inset-0 z-50 lg:hidden">
				<button
					class="absolute inset-0 bg-black/50"
					aria-label="Close navigation menu"
					onclick={() => { menuOpen = false; }}
					transition:fade={{ duration: 120 }}
				></button>
				<div
					class="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-border bg-surface shadow-xl"
					transition:fly={{ x: -288, duration: 180 }}
				>
					<div class="flex items-center justify-between border-b border-border px-4 py-3">
						<span class="text-xl font-bold font-mono uppercase tracking-tight text-text">Hive</span>
						<button
							onclick={() => { menuOpen = false; }}
							class="-mr-1 p-1 text-text-muted hover:text-text"
							aria-label="Close navigation menu"
						>
							<X size={22} />
						</button>
					</div>
					<div class="flex-1 overflow-y-auto py-1">
						{#each navLinks as link (link.href)}
							<a
								href={link.href}
								onclick={() => { menuOpen = false; }}
								class="block border-l-2 px-4 py-3 text-sm font-medium {link.match(page.url.pathname) ? 'border-primary bg-primary-light/30 text-primary' : 'border-transparent text-text-muted hover:bg-bg hover:text-text'}"
							>
								{link.label}
							</a>
						{/each}
					</div>
				</div>
			</div>
		{/if}
	{/if}

	<!-- Piece labeling carries a reference column, the piece, and the color picker
	     side by side — let it use the full window width rather than capping it. -->
	<main
		class="mx-auto px-4 py-6 {page.url.pathname.startsWith('/piece-bboxes') ? 'w-full' : 'max-w-7xl'}"
	>
		{@render children()}
	</main>
{/if}
