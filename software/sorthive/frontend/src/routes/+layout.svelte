<script lang="ts">
	import '../app.css';
	import { auth } from '$lib/auth.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Spinner from '$lib/components/Spinner.svelte';
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();

	let dropdownOpen = $state(false);

	const publicRoutes = ['/login', '/register'];

	async function handleLogout() {
		dropdownOpen = false;
		await auth.logout();
		goto('/login');
	}

	onMount(() => {
		auth.init();
	});

	$effect(() => {
		if (auth.initialized && !auth.isAuthenticated && !publicRoutes.includes(page.url.pathname)) {
			goto('/login');
		}
	});
</script>

{#if auth.loading && !auth.initialized}
	<div class="flex min-h-screen items-center justify-center">
		<Spinner />
	</div>
{:else}
	{#if auth.isAuthenticated}
		<nav class="border-b border-gray-200 bg-white">
			<div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
				<div class="flex items-center gap-6">
					<a href="/" class="text-lg font-bold text-gray-900">SortHive</a>
					<div class="flex gap-1">
						<a
							href="/"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname === '/' ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'}"
						>
							Dashboard
						</a>
						<a
							href="/machines"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname === '/machines' ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'}"
						>
							Machines
						</a>
						<a
							href="/samples"
							class="px-3 py-1.5 text-sm font-medium {page.url.pathname.startsWith('/samples') ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'}"
						>
							Samples
						</a>
						{#if auth.isReviewer}
							<a
								href="/review"
								class="px-3 py-1.5 text-sm font-medium {page.url.pathname === '/review' ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'}"
							>
								Review
							</a>
						{/if}
					</div>
				</div>
				<div class="relative">
					<button
						onclick={() => { dropdownOpen = !dropdownOpen; }}
						class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
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
						<div class="absolute right-0 z-50 mt-1 w-56 border border-gray-200 bg-white py-1 shadow-lg">
							<div class="border-b border-gray-100 px-4 py-2">
								<p class="text-sm font-medium text-gray-900">{auth.user?.display_name}</p>
								<p class="text-xs text-gray-500">{auth.user?.email}</p>
							</div>

							<a
								href="/settings"
								class="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
								onclick={() => { dropdownOpen = false; }}
							>
								<svg class="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
								</svg>
								Profile & Settings
							</a>
							<a
								href="/settings#password"
								class="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
								onclick={() => { dropdownOpen = false; }}
							>
								<svg class="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
								</svg>
								Change Password
							</a>

							{#if auth.isAdmin}
								<div class="border-t border-gray-100 my-1"></div>
								<div class="px-4 py-1">
									<p class="text-xs font-semibold uppercase tracking-wider text-gray-400">Admin</p>
								</div>
								<a
									href="/admin/users"
									class="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
									onclick={() => { dropdownOpen = false; }}
								>
									<svg class="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
									</svg>
									Manage Users
								</a>
							{/if}

							<div class="border-t border-gray-100 my-1"></div>
							<button
								onclick={handleLogout}
								class="flex w-full items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50"
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
		</nav>
	{/if}

	<main class="mx-auto max-w-7xl px-4 py-6">
		{@render children()}
	</main>
{/if}
