<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type AuthOptions } from '$lib/api';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import OAuthButtons from '$lib/components/OAuthButtons.svelte';

	let email = $state('');
	let password = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);
	let authOptions = $state<AuthOptions | null>(null);
	let lastMethod = $state<string | null>(null);

	onMount(async () => {
		try {
			lastMethod = localStorage.getItem('hive:last-login-method');
		} catch {
			lastMethod = null;
		}
		try {
			authOptions = await api.authOptions();
		} catch {
			authOptions = null;
		}
	});

	function safeNextPath(): string {
		const next = page.url.searchParams.get('next');
		if (next && next.startsWith('/') && !next.startsWith('//')) return next;
		return '/';
	}

	function nextQueryString(): string {
		const next = safeNextPath();
		return next === '/' ? '' : `?${new URLSearchParams({ next }).toString()}`;
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		const result = await auth.login(email, password);
		submitting = false;
		if (result) {
			error = result;
		} else {
			try {
				localStorage.setItem('hive:last-login-method', 'password');
			} catch {
				/* cosmetic */
			}
			goto(safeNextPath());
		}
	}

	function currentError(): string | null {
		return error ?? page.url.searchParams.get('error');
	}
</script>

<svelte:head>
	<title>Login - Hive</title>
</svelte:head>

<div class="flex min-h-[80vh] items-center justify-center">
	<div class="w-full max-w-sm border border-border bg-surface p-8">
		<h1 class="mb-6 text-center text-2xl font-bold text-text">Sign in to Hive</h1>

		{#if currentError()}
			<div class="mb-4 bg-primary-light p-3 text-sm text-danger">{currentError()}</div>
		{/if}

		<form onsubmit={handleSubmit} class="space-y-4">
			<div>
				<label for="email" class="mb-1 block text-sm font-medium text-text">Email</label>
				<input
					id="email"
					type="email"
					bind:value={email}
					required
					class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
				/>
			</div>
			<div>
				<label for="password" class="mb-1 block text-sm font-medium text-text">Password</label>
				<input
					id="password"
					type="password"
					bind:value={password}
					required
					class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
				/>
			</div>
			<button
				type="submit"
				disabled={submitting}
				class="relative w-full bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
			>
				{submitting ? 'Signing in...' : 'Sign in'}
				{#if lastMethod === 'password'}
					<span class="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-white/20 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white">Last used</span>
				{/if}
			</button>
		</form>

		<OAuthButtons options={authOptions} next={safeNextPath()} lastUsed={lastMethod} />

		<p class="mt-4 text-center text-sm text-text-muted">
			Don't have an account?
			<a href={`/register${nextQueryString()}`} class="text-primary hover:underline">Register</a>
		</p>
	</div>
</div>
