<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type AuthOptions } from '$lib/api';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import OAuthButtons from '$lib/components/OAuthButtons.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Wordmark from '$lib/components/Wordmark.svelte';

	let email = $state('');
	let password = $state('');
	let displayName = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);
	let authOptions = $state<AuthOptions | null>(null);

	onMount(async () => {
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
		const result = await auth.register(email, password, displayName);
		submitting = false;
		if (result) {
			error = result;
		} else {
			goto(safeNextPath());
		}
	}
</script>

<svelte:head>
	<title>Create an account - Hive</title>
</svelte:head>

<div class="flex min-h-[80vh] items-center justify-center">
	<div class="flex w-full max-w-sm flex-col gap-(--gap-panels)">
		<div class="flex justify-center"><Wordmark name="Hive" /></div>
		<Panel title="Create an account">
			<form onsubmit={handleSubmit} class="flex flex-col gap-4">
				{#if error}<Alert tone="danger">{error}</Alert>{/if}
				<Field label="Display name" for="displayName">
					<Input id="displayName" bind:value={displayName} required autocomplete="nickname" />
				</Field>
				<Field label="Email" for="email">
					<Input id="email" type="email" bind:value={email} required autocomplete="email" />
				</Field>
				<Field label="Password" for="password" help="At least 8 characters.">
					<Input id="password" type="password" bind:value={password} required minlength={8} autocomplete="new-password" />
				</Field>
				<Button type="submit" variant="primary" loading={submitting} class="w-full">Create the account</Button>
			</form>
			<OAuthButtons options={authOptions} next={safeNextPath()} />
			<p class="mt-4 text-center text-sm text-ink-muted">
				Have an account? <a href={`/login${nextQueryString()}`} class="font-medium text-primary-ink hover:underline">Sign in</a>
			</p>
		</Panel>
	</div>
</div>
