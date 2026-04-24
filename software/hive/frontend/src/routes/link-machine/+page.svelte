<script lang="ts">
	import { page } from '$app/state';
	import { api, getApiBaseUrl, type ApiError } from '$lib/api';
	import { auth } from '$lib/auth.svelte';

	let machineName = $state(page.url.searchParams.get('suggested_machine_name') || 'Lego Sorter');
	let description = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);

	function returnToUrl(): URL | null {
		const raw = page.url.searchParams.get('return_to');
		if (!raw) return null;
		try {
			const parsed = new URL(raw);
			if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
			return parsed;
		} catch {
			return null;
		}
	}

	function stateToken(): string {
		return page.url.searchParams.get('state') ?? '';
	}

	function targetName(): string {
		return page.url.searchParams.get('target_name') || 'Hive';
	}

	function sorterOrigin(): string | null {
		const raw = page.url.searchParams.get('sorter_origin');
		if (!raw) return null;
		try {
			const parsed = new URL(raw);
			if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
			return parsed.origin;
		} catch {
			return null;
		}
	}

	function destinationLabel(): string {
		const callback = returnToUrl();
		return callback ? callback.host : 'Unknown Sorter';
	}

	function canSubmit(): boolean {
		return Boolean(returnToUrl() && stateToken() && machineName.trim());
	}

	function hiveApiBaseUrl(): string {
		const apiBaseUrl = getApiBaseUrl();
		if (apiBaseUrl) return apiBaseUrl;
		return window.location.origin;
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		error = null;
		if (!canSubmit()) {
			error = 'The Sorter link request is incomplete. Please start the Hive link again from Sorter.';
			return;
		}

		submitting = true;
		try {
			const machine = await api.createMachine(
				machineName.trim(),
				description.trim() || undefined
			);
			const callback = returnToUrl();
			if (!callback) throw new Error('The Sorter callback URL is invalid.');

			callback.hash = new URLSearchParams({
				hive_link: '1',
				state: stateToken(),
				api_token: machine.raw_token,
				machine_id: machine.id,
				machine_name: machine.name,
				target_name: targetName(),
				token_prefix: machine.token_prefix,
				api_base_url: hiveApiBaseUrl()
			}).toString();
			window.location.href = callback.toString();
		} catch (e) {
			const apiError = e as Partial<ApiError>;
			error = apiError.error ?? (e instanceof Error ? e.message : 'Machine link failed.');
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Link Sorter - Hive</title>
</svelte:head>

<div class="mx-auto grid min-h-[70vh] max-w-2xl place-items-center">
	<div class="w-full border border-border bg-white p-6 shadow-sm dark:bg-[var(--color-surface)]">
		<div class="flex items-start gap-3">
			<div class="flex h-10 w-10 shrink-0 items-center justify-center bg-primary-light text-primary">
				<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3 5 6v5c0 4.1 2.9 7.9 7 9 4.1-1.1 7-4.9 7-9V6l-7-3Z" />
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m9 12 2 2 4-5" />
				</svg>
			</div>
			<div class="min-w-0">
				<p class="text-xs font-semibold tracking-wider text-text-muted uppercase">Machine link</p>
				<h1 class="mt-1 text-2xl font-semibold tracking-tight text-text">Connect this sorter to Hive</h1>
				<p class="mt-2 text-sm leading-relaxed text-text-muted">
					Hive creates a machine token for your account and sends it directly back to the
					Sorter. The token is not shown on this page.
				</p>
			</div>
		</div>

		{#if !returnToUrl() || !stateToken()}
			<div class="mt-5 border border-danger/40 bg-danger/[0.06] px-4 py-3 text-sm text-danger">
				This link request is incomplete. Please go back to Sorter and start the Hive link again.
			</div>
		{:else}
			<div class="mt-5 grid gap-3 border border-border bg-bg px-4 py-3 text-sm">
				<div class="grid gap-1">
					<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">Signed in as</span>
					<span class="text-text">{auth.user?.display_name || auth.user?.email}</span>
				</div>
				<div class="grid gap-1">
					<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">Return target</span>
					<span class="font-mono text-text">{destinationLabel()}</span>
				</div>
				{#if sorterOrigin()}
					<div class="grid gap-1">
						<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">Started from</span>
						<span class="font-mono text-text">{sorterOrigin()}</span>
					</div>
				{/if}
			</div>

			<form onsubmit={handleSubmit} class="mt-5 grid gap-4">
				<label class="grid gap-1">
					<span class="text-sm font-medium text-text">Machine name in Hive</span>
					<input
						bind:value={machineName}
						type="text"
						required
						disabled={submitting}
						class="border border-border bg-white px-3 py-2 text-sm text-text focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none disabled:opacity-60 dark:bg-[var(--color-bg)]"
					/>
				</label>

				<label class="grid gap-1">
					<span class="text-sm font-medium text-text">Description <span class="text-text-muted">(optional)</span></span>
					<textarea
						bind:value={description}
						rows="3"
						disabled={submitting}
						placeholder="Where this sorter lives, who maintains it, or what it is used for."
						class="resize-y border border-border bg-white px-3 py-2 text-sm text-text focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none disabled:opacity-60 dark:bg-[var(--color-bg)]"
					></textarea>
				</label>

				{#if error}
					<div class="border border-danger/40 bg-danger/[0.06] px-3 py-2 text-sm text-danger">
						{error}
					</div>
				{/if}

				<div class="flex flex-wrap items-center justify-between gap-3">
					<p class="text-xs leading-relaxed text-text-muted">
						Only confirm this if you trust <span class="font-mono text-text">{destinationLabel()}</span>.
					</p>
					<button
						type="submit"
						disabled={submitting || !canSubmit()}
						class="inline-flex min-h-10 items-center justify-center gap-2 bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
					>
						{#if submitting}
							<span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>
							Linking...
						{:else}
							<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
								<path d="M11 3a1 1 0 1 0 0 2h2.59L8.3 10.29a1 1 0 1 0 1.41 1.42L15 6.41V9a1 1 0 1 0 2 0V4a1 1 0 0 0-1-1h-5Z" />
								<path d="M5 5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-3a1 1 0 1 0-2 0v3H5V7h3a1 1 0 0 0 0-2H5Z" />
							</svg>
							Link machine
						{/if}
					</button>
				</div>
			</form>
		{/if}
	</div>
</div>
