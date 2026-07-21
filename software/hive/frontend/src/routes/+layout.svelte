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

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();

	let dropdownOpen = $state(false);

	// /machine-ip-lookup is an unlisted, login-free rendezvous page used by the
	// SorterOS onboarding flow — a fresh sorter has no Hive account yet.
	const publicRoutes = ['/login', '/register', '/machine-ip-lookup', '/forget'];

	function currentPathWithSearch(): string {
		return `${page.url.pathname}${page.url.search}`;
	}

	async function handleLogout() {
		dropdownOpen = false;
		await auth.logout();
		goto('/login');
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
</script>

{#if auth.loading && !auth.initialized}
	<div class="flex min-h-screen items-center justify-center">
		<Spinner />
	</div>
{:else}
	{#if auth.isAuthenticated}
		<nav class="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
			<div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
				<div class="flex items-center gap-6">
					<a href="/" class="text-xl font-bold font-mono uppercase tracking-tight text-[var(--color-text)]">Hive</a>
					<div class="flex gap-1">
						<a
							href="/"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname === '/' ? 'border-b-2 border-primary text-primary' : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg)]'}"
						>
							Dashboard
						</a>
						<a
							href="/machines"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname === '/machines' || page.url.pathname.startsWith('/machines/') ? 'border-b-2 border-primary text-primary' : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg)]'}"
						>
							My Machines
						</a>
						<a
							href="/profiles"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname.startsWith('/profiles') ? 'border-b-2 border-primary text-primary' : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg)]'}"
						>
							Profiles
						</a>
						<a
							href="/samples"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname.startsWith('/samples') || page.url.pathname === '/review' ? 'border-b-2 border-primary text-primary' : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg)]'}"
						>
							Channel Samples
						</a>
						<a
							href="/piece-bboxes"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname.startsWith('/piece-bboxes') ? 'border-b-2 border-primary text-primary' : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg)]'}"
						>
							Piece Samples
						</a>
						<a
							href="/models"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname.startsWith('/models') ? 'border-b-2 border-primary text-primary' : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg)]'}"
						>
							Models
						</a>
						<a
							href="/leaderboard"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname.startsWith('/leaderboard') ? 'border-b-2 border-primary text-primary' : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg)]'}"
						>
							Leaderboard
						</a>
					</div>
				</div>
				<div class="flex items-center gap-3">
					<ThemeToggle />
					<div class="relative">
						<button
							onclick={() => { dropdownOpen = !dropdownOpen; }}
							class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-[var(--color-text)] hover:bg-[var(--color-bg)]"
						>
							<span>{auth.user?.display_name ?? auth.user?.email}</span>
							<svg class="h-4 w-4 transition-transform {dropdownOpen ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
							</svg>
						</button>

						{#if dropdownOpen}
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<div
								class="fixed inset-0 z-40"
								onclick={() => { dropdownOpen = false; }}
								onkeydown={() => {}}
							></div>
							<div class="absolute right-0 z-50 mt-1 w-56 border border-[var(--color-border)] bg-[var(--color-surface)] py-1 shadow-lg">
								<div class="border-b border-[var(--color-border)] px-4 py-2">
									<p class="text-sm font-medium text-[var(--color-text)]">{auth.user?.display_name}</p>
									<p class="text-xs text-[var(--color-text-muted)]">{auth.user?.email}</p>
								</div>

								<a
									href="/settings"
									class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
									onclick={() => { dropdownOpen = false; }}
								>
									<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
									</svg>
									Profile & Settings
								</a>
								<a
									href="/settings#password"
									class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
									onclick={() => { dropdownOpen = false; }}
								>
									<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
									</svg>
									Change Password
								</a>

								{#if auth.isAdmin}
									<div class="border-t border-[var(--color-border)] my-1"></div>
									<div class="px-4 py-1">
										<p class="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">Admin</p>
									</div>
									<a
										href="/admin/users"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
										</svg>
										Manage Users
									</a>
									<a
										href="/admin/machines"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a3 3 0 0 1 3-3h13.5a3 3 0 0 1 3 3m-19.5 0a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7m0 0a3 3 0 0 1-3 3m0 0h.008v.008h-.008v-.008Zm-3 0h.008v.008h-.008v-.008Z" />
										</svg>
										All Machines
									</a>
									<a
										href="/admin/control-data"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
										</svg>
										Control Data
									</a>
									<a
										href="/admin/server-health"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
										</svg>
										Server Health
									</a>
									<a
										href="/admin/teacher-jobs"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
										</svg>
										Teacher Jobs
									</a>
									<a
										href="/admin/color-models"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M4.098 19.902a3.75 3.75 0 0 0 5.304 0l6.401-6.402M6.75 21A3.75 3.75 0 0 1 3 17.25V4.125C3 3.504 3.504 3 4.125 3h5.25c.621 0 1.125.504 1.125 1.125v4.072M6.75 21a3.75 3.75 0 0 0 3.75-3.75V8.197M6.75 21h13.125c.621 0 1.125-.504 1.125-1.125v-5.25c0-.621-.504-1.125-1.125-1.125h-4.072M10.5 8.197l2.88-2.88c.438-.439 1.15-.439 1.59 0l3.712 3.713c.44.44.44 1.152 0 1.59l-2.879 2.88M6.75 17.25h.008v.008H6.75v-.008Z" />
										</svg>
										Color Models
									</a>
									<a
										href="/admin/link-models"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
										</svg>
										Link Models
									</a>
									<a
										href="/admin/parts"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 5.25h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5" />
										</svg>
										Parts Database
									</a>
									<a
										href="/admin/access-windows"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
										</svg>
										Access Windows
									</a>
									<a
										href="/settings/catalog-sync"
										class="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text)] hover:bg-[var(--color-bg)]"
										onclick={() => { dropdownOpen = false; }}
									>
										<svg class="h-4 w-4 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
										</svg>
										Catalog Sync
									</a>
								{/if}

								<div class="border-t border-[var(--color-border)] my-1"></div>
								<button
									onclick={handleLogout}
									class="flex w-full items-center gap-2 px-4 py-2 text-sm text-primary hover:bg-primary-light"
								>
									<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
									</svg>
									Logout
								</button>
							</div>
						{/if}
					</div>
				</div>
			</div>
		</nav>
	{/if}

	<!-- The single-piece labeling view runs wider — it carries a reference column,
	     the piece, and the color picker side by side. -->
	<main
		class="mx-auto px-4 py-6 {/^\/piece-bboxes\/.+/.test(page.url.pathname) ? 'max-w-[120rem]' : 'max-w-7xl'}"
	>
		{@render children()}
	</main>
{/if}
