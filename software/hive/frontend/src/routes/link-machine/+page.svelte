<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		api,
		getApiBaseUrl,
		type ApiError,
		type Machine,
		type MachineConfigBackupSummary,
		type MachineWithToken
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';

	type LinkMode = 'existing' | 'new';

	let machineName = $state(page.url.searchParams.get('suggested_machine_name') || 'Lego Sorter');
	let description = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);
	let linkMode = $state<LinkMode>(page.url.searchParams.get('intent') === 'restore' ? 'existing' : 'new');
	let machines = $state<Machine[]>([]);
	let machineBackups = $state<Record<string, MachineConfigBackupSummary[]>>({});
	let selectedMachineId = $state('');
	let loadingMachines = $state(false);
	let machineLoadError = $state<string | null>(null);

	const restoreIntent = $derived(page.url.searchParams.get('intent') === 'restore');

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
		if (!returnToUrl() || !stateToken()) return false;
		if (linkMode === 'existing') return Boolean(selectedMachineId);
		return Boolean(machineName.trim());
	}

	function hiveApiBaseUrl(): string {
		const apiBaseUrl = getApiBaseUrl();
		if (apiBaseUrl) return apiBaseUrl;
		return window.location.origin;
	}

	function backupCount(machineId: string): number {
		return machineBackups[machineId]?.length ?? 0;
	}

	function selectedMachine(): Machine | null {
		return machines.find((machine) => machine.id === selectedMachineId) ?? null;
	}

	async function loadExistingMachines() {
		loadingMachines = true;
		machineLoadError = null;
		try {
			const list = await api.getMachines({ scope: 'mine' });
			machines = list;
			if (!selectedMachineId && list.length > 0) {
				selectedMachineId = list[0].id;
			}

			if (restoreIntent) {
				const backupEntries = await Promise.all(
					list.map(async (machine) => {
						try {
							const backups = await api.getMachineConfigBackups(machine.id);
							return [machine.id, backups] as const;
						} catch {
							return [machine.id, []] as const;
						}
					})
				);
				const nextBackups = Object.fromEntries(backupEntries);
				machineBackups = nextBackups;
				const firstWithBackups = list.find((machine) => (nextBackups[machine.id]?.length ?? 0) > 0);
				if (firstWithBackups && (!selectedMachineId || backupCount(selectedMachineId) === 0)) {
					selectedMachineId = firstWithBackups.id;
				}
			} else {
				machineBackups = {};
			}
			if (list.length === 0) {
				linkMode = 'new';
			}
		} catch (e) {
			const apiError = e as Partial<ApiError>;
			machineLoadError = apiError.error ?? (e instanceof Error ? e.message : 'Machines could not be loaded.');
			if (machines.length === 0) {
				linkMode = 'new';
			}
		} finally {
			loadingMachines = false;
		}
	}

	onMount(() => {
		void loadExistingMachines();
	});

	async function handleSubmit(e: Event) {
		e.preventDefault();
		error = null;
		if (!canSubmit()) {
			error = 'The Sorter link request is incomplete. Please start the Hive link again from Sorter.';
			return;
		}

		submitting = true;
		try {
			let machine: MachineWithToken;
			if (linkMode === 'existing') {
				const existing = selectedMachine();
				if (!existing) throw new Error('Choose an existing machine profile.');
				machine = await api.rotateToken(existing.id);
			} else {
				machine = await api.createMachine(
					machineName.trim(),
					description.trim() || undefined
				);
			}
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
	<div class="w-full border border-border bg-surface p-6 shadow-sm dark:bg-[var(--color-surface)]">
		<div class="flex items-start gap-3">
			<div class="flex h-10 w-10 shrink-0 items-center justify-center bg-primary-light text-primary">
				<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3 5 6v5c0 4.1 2.9 7.9 7 9 4.1-1.1 7-4.9 7-9V6l-7-3Z" />
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m9 12 2 2 4-5" />
				</svg>
			</div>
			<div class="min-w-0">
				<p class="text-xs font-semibold tracking-wider text-text-muted uppercase">Machine link</p>
				<h1 class="mt-1 text-2xl font-semibold tracking-tight text-text">
					{restoreIntent ? 'Restore this sorter from Hive' : 'Connect this sorter to Hive'}
				</h1>
				<p class="mt-2 text-sm leading-relaxed text-text-muted">
					{#if restoreIntent}
						Choose an existing machine profile or create a new one. Hive sends a machine
						token directly back to the Sorter.
					{:else}
						Choose an existing machine profile if this Sorter was already registered, or
						create a new one. Hive sends the machine token directly back to the Sorter.
					{/if}
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
				<div class="grid gap-3">
					<div class="grid gap-2 sm:grid-cols-2">
						<button
							type="button"
							onclick={() => { linkMode = 'existing'; }}
							disabled={submitting || loadingMachines || machines.length === 0}
							class={`border px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
								linkMode === 'existing'
									? 'border-primary bg-primary-light text-text'
									: 'border-border bg-surface text-text hover:border-primary'
							}`}
						>
							<div class="text-sm font-semibold">Use existing profile</div>
							<div class="mt-1 text-xs leading-relaxed text-text-muted">
								Reconnect this Sorter to a machine already in Hive.
							</div>
						</button>
						<button
							type="button"
							onclick={() => { linkMode = 'new'; }}
							disabled={submitting}
							class={`border px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
								linkMode === 'new'
									? 'border-primary bg-primary-light text-text'
									: 'border-border bg-surface text-text hover:border-primary'
							}`}
						>
							<div class="text-sm font-semibold">Create new profile</div>
							<div class="mt-1 text-xs leading-relaxed text-text-muted">
								Start fresh and let the Sorter create its first backup later.
							</div>
						</button>
					</div>

					{#if machineLoadError}
						<div class="border border-danger/40 bg-danger/[0.06] px-3 py-2 text-sm text-danger">
							{machineLoadError}
						</div>
					{/if}

					{#if linkMode === 'existing'}
						{#if loadingMachines}
							<div class="border border-border bg-bg px-4 py-3 text-sm text-text-muted">
								Loading your machines…
							</div>
						{:else if machines.length === 0}
							<div class="border border-border bg-bg px-4 py-3 text-sm text-text-muted">
								No existing machines found for this account.
							</div>
						{:else}
							<label class="grid gap-1">
								<span class="text-sm font-medium text-text">Machine profile</span>
								<select
									bind:value={selectedMachineId}
									disabled={submitting}
									class="border border-border bg-surface px-3 py-2 text-sm text-text focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none disabled:opacity-60 dark:bg-[var(--color-bg)]"
								>
									{#each machines as machine}
										<option value={machine.id}>
											{machine.name}{restoreIntent ? ` · ${backupCount(machine.id)} backup${backupCount(machine.id) === 1 ? '' : 's'}` : ''}
										</option>
									{/each}
								</select>
							</label>
							<p class="text-xs leading-relaxed text-text-muted">
								Hive will issue a fresh token for this machine. The previous token stops working.
							</p>
						{/if}
					{/if}
				</div>

				{#if linkMode === 'new'}
					<label class="grid gap-1">
						<span class="text-sm font-medium text-text">Machine name in Hive</span>
						<input
							bind:value={machineName}
							type="text"
							required
							disabled={submitting}
							class="border border-border bg-surface px-3 py-2 text-sm text-text focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none disabled:opacity-60 dark:bg-[var(--color-bg)]"
						/>
					</label>

					<label class="grid gap-1">
						<span class="text-sm font-medium text-text">Description <span class="text-text-muted">(optional)</span></span>
						<textarea
							bind:value={description}
							rows="3"
							disabled={submitting}
							placeholder="Where this sorter lives, who maintains it, or what it is used for."
							class="resize-y border border-border bg-surface px-3 py-2 text-sm text-text focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none disabled:opacity-60 dark:bg-[var(--color-bg)]"
						></textarea>
					</label>
				{/if}

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
							{linkMode === 'existing' ? 'Reconnect machine' : 'Link machine'}
						{/if}
					</button>
				</div>
			</form>
		{/if}
	</div>
</div>
