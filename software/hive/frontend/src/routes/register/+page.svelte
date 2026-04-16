<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api } from '$lib/api';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	let email = $state('');
	let password = $state('');
	let displayName = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);
	let githubEnabled = $state(false);

	onMount(async () => {
		try {
			const options = await api.authOptions();
			githubEnabled = options.github_enabled;
		} catch {
			githubEnabled = false;
		}
	});

	async function handleSubmit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		const result = await auth.register(email, password, displayName);
		submitting = false;
		if (result) {
			error = result;
		} else {
			goto('/');
		}
	}
</script>

<svelte:head>
	<title>Register - Hive</title>
</svelte:head>

<div class="flex min-h-[80vh] items-center justify-center">
	<div class="w-full max-w-sm border border-border bg-white p-8">
		<h1 class="mb-6 text-center text-2xl font-bold text-text">Create an account</h1>

		{#if error}
			<div class="mb-4 bg-primary-light p-3 text-sm text-danger">{error}</div>
		{/if}

		<form onsubmit={handleSubmit} class="space-y-4">
			<div>
				<label for="displayName" class="mb-1 block text-sm font-medium text-text">Display Name</label>
				<input
					id="displayName"
					type="text"
					bind:value={displayName}
					required
					class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
				/>
			</div>
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
					minlength="8"
					class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
				/>
			</div>
			<button
				type="submit"
				disabled={submitting}
				class="w-full bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
			>
				{submitting ? 'Creating account...' : 'Register'}
			</button>
		</form>

		{#if githubEnabled}
			<div class="my-5 flex items-center gap-3">
				<div class="h-px flex-1 bg-border"></div>
				<span class="text-xs font-medium uppercase tracking-wide text-text-muted">or</span>
				<div class="h-px flex-1 bg-border"></div>
			</div>

			<a
				href={api.githubLoginUrl()}
				class="flex w-full items-center justify-center gap-3 border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg"
			>
				<svg viewBox="0 0 24 24" class="h-5 w-5 fill-current" aria-hidden="true">
					<path d="M12 .5C5.65.5.5 5.65.5 12A11.5 11.5 0 0 0 8.36 22.7c.58.1.79-.25.79-.56v-2.17c-3.18.69-3.85-1.35-3.85-1.35-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.69.08-.69 1.15.08 1.76 1.19 1.76 1.19 1.02 1.75 2.68 1.24 3.34.95.1-.74.4-1.24.73-1.53-2.54-.29-5.22-1.27-5.22-5.67 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11.03 11.03 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.08 0 4.41-2.68 5.38-5.24 5.66.41.35.78 1.04.78 2.09v3.1c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z"/>
				</svg>
				Continue with GitHub
			</a>
		{/if}

		<p class="mt-4 text-center text-sm text-text-muted">
			Already have an account?
			<a href="/login" class="text-primary hover:underline">Sign in</a>
		</p>
	</div>
</div>
