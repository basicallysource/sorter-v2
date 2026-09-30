<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type AuthOptions } from '$lib/api';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import OAuthButtons from '$lib/components/OAuthButtons.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';

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
		if (submitting) return;
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
	<title>Sign in - Hive</title>
</svelte:head>

<div class="flex min-h-[80vh] items-center justify-center">
	<div class="flex w-full max-w-sm flex-col gap-(--gap-panels)">
		<div class="flex justify-center"><Wordmark name="Hive" /></div>
		<Panel title="Sign in to Hive">
			<form onsubmit={handleSubmit} class="flex flex-col gap-4">
				{#if currentError()}<Alert tone="danger">{currentError()}</Alert>{/if}
				<Field label="Email" for="email">
					<Input id="email" type="email" bind:value={email} required autocomplete="email" />
				</Field>
				<Field label="Password" for="password">
					<Input id="password" type="password" bind:value={password} required autocomplete="current-password" />
				</Field>
				<Button type="submit" variant="primary" loading={submitting} class="relative w-full">
					Sign in
					{#if lastMethod === 'password'}<span class="absolute right-2"><Badge>Last used</Badge></span>{/if}
				</Button>
			</form>
			<OAuthButtons options={authOptions} next={safeNextPath()} lastUsed={lastMethod} />
			<p class="mt-4 text-center text-sm text-ink-muted">
				No account yet? <a href={`/register${nextQueryString()}`} class="font-medium text-primary-ink hover:underline">Create one</a>
			</p>
		</Panel>
	</div>
</div>
