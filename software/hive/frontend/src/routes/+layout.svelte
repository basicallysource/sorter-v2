<script lang="ts">
	import '../app.css';
	import '@fontsource-variable/geist';
	import '@fontsource-variable/geist-mono';
	import { auth } from '$lib/auth.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Spinner from '$lib/components/Spinner.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import Menu from '$lib/components/Menu.svelte';
	import Button from '$lib/components/Button.svelte';
	import { theme } from '$lib/stores/theme';
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';
	import ChartColumn from '@lucide/svelte/icons/chart-column';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Database from '@lucide/svelte/icons/database';
	import KeyRound from '@lucide/svelte/icons/key-round';
	import Link from '@lucide/svelte/icons/link';
	import List from '@lucide/svelte/icons/list';
	import Lock from '@lucide/svelte/icons/lock';
	import LogOut from '@lucide/svelte/icons/log-out';
	import Palette from '@lucide/svelte/icons/palette';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Server from '@lucide/svelte/icons/server';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import User from '@lucide/svelte/icons/user';
	import Users from '@lucide/svelte/icons/users';

	let { children }: { children: Snippet } = $props();

	// /machine-ip-lookup is an unlisted, login-free rendezvous page used by the
	// SorterOS onboarding flow: a fresh sorter has no Hive account yet.
	const publicRoutes = ['/login', '/register', '/machine-ip-lookup', '/forget'];

	const navLinks = [
		{ href: '/', label: 'Dashboard' },
		{ href: '/machines', label: 'My machines' },
		{ href: '/profiles', label: 'Profiles' },
		{ href: '/kits', label: 'Kits' },
		{ href: '/samples', label: 'Channel samples' },
		{ href: '/piece-bboxes', label: 'Piece samples' },
		{ href: '/models', label: 'Models' },
		{ href: '/leaderboard', label: 'Leaderboard' }
	];

	const adminLinks = [
		{ label: 'Users', icon: Users, href: '/admin/users' },
		{ label: 'All machines', icon: Server, href: '/admin/machines' },
		{ label: 'Control data', icon: Database, href: '/admin/control-data' },
		{ label: 'Server health', icon: ChartColumn, href: '/admin/server-health' },
		{ label: 'Teacher jobs', icon: Sparkles, href: '/admin/teacher-jobs' },
		{ label: 'Color models', icon: Palette, href: '/admin/color-models' },
		{ label: 'Link models', icon: Link, href: '/admin/link-models' },
		{ label: 'Parts database', icon: List, href: '/admin/parts' },
		{ label: 'Access windows', icon: Lock, href: '/admin/access-windows' },
		{ label: 'Catalog sync', icon: RefreshCw, href: '/settings/catalog-sync' }
	];

	const userMenu = $derived([
		{ label: 'Profile and settings', icon: User, href: '/settings' },
		{ label: 'Change password', icon: KeyRound, href: '/settings#password' },
		...(auth.isAdmin ? (['separator', { group: 'Admin', items: adminLinks }] as const) : []),
		'separator' as const,
		{ label: 'Log out', icon: LogOut, onselect: handleLogout }
	]);

	// Labeling a piece shows a reference column, the piece and the color
	// picker side by side, and the profile editor its rules, the rule being
	// edited and the result, so both take the whole width of the window.
	const fullWidth = $derived(
		page.url.pathname.startsWith('/piece-bboxes') || /^\/profiles\/[^/]+\/edit$/.test(page.url.pathname)
	);

	async function handleLogout() {
		await auth.logout();
		goto('/login');
	}

	onMount(() => {
		auth.init();
		theme.init();
	});

	$effect(() => {
		if (auth.initialized && !auth.isAuthenticated && !publicRoutes.includes(page.url.pathname)) {
			const next = `${page.url.pathname}${page.url.search}`;
			goto(`/login?${new URLSearchParams({ next }).toString()}`);
		}
	});

	$effect(() => {
		if (typeof document === 'undefined') return;
		document.documentElement.classList.toggle('dark', $theme === 'dark');
	});
</script>

{#if auth.loading && !auth.initialized}
	<div class="flex min-h-dvh items-center justify-center">
		<Spinner size={32} />
	</div>
{:else}
	{#if auth.isAuthenticated}
		<TopBar items={navLinks} collapse="lg">
			{#snippet brand()}<Wordmark name="Hive" />{/snippet}
			{#snippet end()}
				<Menu label="Account" items={userMenu}>
					{#snippet trigger(props)}
						<Button {...props} variant="ghost" size="sm" icon={User}>
							<span class="max-w-40 truncate max-sm:sr-only"
								>{auth.user?.display_name ?? auth.user?.email}</span
							>
							<ChevronDown size={14} class="shrink-0 text-ink-muted max-sm:hidden" />
						</Button>
					{/snippet}
				</Menu>
			{/snippet}
		</TopBar>
	{/if}

	<main class="mx-auto flex w-full flex-col gap-(--gap-panels) px-4 py-6 sm:px-6 {fullWidth ? '' : 'max-w-7xl'}">
		{@render children()}
	</main>
{/if}
