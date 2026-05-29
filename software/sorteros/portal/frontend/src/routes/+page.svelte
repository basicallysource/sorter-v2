<script lang="ts">
	import { onMount } from 'svelte';
	import { connect, fetchStatus, scanNetworks, type StatusResponse, type WifiNetwork } from '$lib/api';
	import { createRendezvous, lookupUrl, type Rendezvous } from '$lib/rendezvous';
	import SignalBars from '$lib/components/SignalBars.svelte';
	import HandoffPanel from '$lib/components/HandoffPanel.svelte';

	// Where the encrypted LAN-IP rendezvous is relayed. Kept in lock-step with
	// the portal backend's DEFAULT_HIVE_URL and the sorter's DEFAULT_HIVE_URL.
	const HIVE_URL = 'https://hive.basically.website';

	type Stage = 'loading' | 'pick' | 'auth' | 'submitting' | 'handoff' | 'error';

	let stage = $state<Stage>('loading');
	let status = $state<StatusResponse | null>(null);
	let networks = $state<WifiNetwork[]>([]);
	let scanning = $state(false);
	let scanError = $state<string | null>(null);

	let selected = $state<WifiNetwork | null>(null);
	let hiddenSsid = $state('');
	let password = $state('');
	let showPassword = $state(false);
	let hostnameDraft = $state('');
	let sshKeyDraft = $state('');
	let showAdvanced = $state(false);

	let submitError = $state<string | null>(null);
	let handoff = $state<{
		ssid: string;
		nextUrl: string;
		lookupUrl: string | null;
		teardownInS?: number;
	} | null>(null);

	// Generated once on mount; the public half is sent to the Pi, the private
	// half is folded into the Hive lookup URL on handoff.
	let rendezvous: Rendezvous | null = null;

	const selectedIsOpen = $derived(selected !== null && (selected.security || '').trim() === '');

	async function refreshStatus() {
		try {
			status = await fetchStatus();
		} catch (err: any) {
			scanError = err?.message ?? 'status fetch failed';
		}
	}

	async function rescan() {
		scanning = true;
		scanError = null;
		try {
			const res = await scanNetworks(true);
			networks = res.networks;
		} catch (err: any) {
			scanError = err?.message ?? 'scan failed';
		} finally {
			scanning = false;
		}
	}

	function chooseHidden() {
		selected = null;
		stage = 'auth';
	}

	function choose(n: WifiNetwork) {
		selected = n;
		hiddenSsid = '';
		password = '';
		submitError = null;
		stage = 'auth';
	}

	function back() {
		stage = 'pick';
		submitError = null;
	}

	async function submit(event: Event) {
		event.preventDefault();
		submitError = null;

		const ssid = (selected?.ssid ?? hiddenSsid).trim();
		if (!ssid) {
			submitError = 'Pick a network or type a hidden SSID.';
			return;
		}

		stage = 'submitting';
		try {
			const res = await connect({
				ssid,
				password: selectedIsOpen ? '' : password,
				hidden: selected === null,
				hostname: hostnameDraft.trim() || null,
				sshKey: sshKeyDraft.trim() || null,
				rendezvousId: rendezvous?.id ?? null,
				publicKey: rendezvous?.publicKeyB64 ?? null
			});
			handoff = {
				ssid,
				nextUrl: res.next_url,
				lookupUrl: rendezvous ? lookupUrl(HIVE_URL, rendezvous) : null,
				teardownInS: res.teardown_in_s ?? 5
			};
			stage = 'handoff';
		} catch (err: any) {
			submitError = err?.message ?? 'connect failed';
			stage = 'auth';
		}
	}

	onMount(async () => {
		// Kick off keypair generation immediately — it's ready long before the
		// user finishes picking a network. Failure (e.g. no WebCrypto on a
		// plain-http origin) just drops us to the .local-only handoff.
		void createRendezvous().then((r) => {
			rendezvous = r;
		});
		await refreshStatus();
		await rescan();
		if (stage === 'loading') {
			stage = 'pick';
		}
	});
</script>

<svelte:head>
	<title>SorterOS Setup</title>
</svelte:head>

<main class="mx-auto flex min-h-screen w-full max-w-lg flex-col px-5 py-6">
	<header class="mb-6 flex items-baseline justify-between">
		<div>
			<h1 class="text-xl font-semibold tracking-tight">SorterOS Setup</h1>
			<div class="text-sm text-[var(--color-text-muted)]">
				{#if status}
					{status.hostname}{status.mode === 'mock' ? ' · mock' : ''}
				{:else}
					&nbsp;
				{/if}
			</div>
		</div>
		{#if stage === 'pick' || stage === 'auth'}
			<button
				type="button"
				onclick={rescan}
				class="border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs uppercase tracking-wider text-[var(--color-text-muted)] hover:text-[var(--color-text)] disabled:opacity-50"
				disabled={scanning}
			>
				{scanning ? 'Scanning…' : 'Rescan'}
			</button>
		{/if}
	</header>

	{#if stage === 'loading'}
		<div class="flex flex-1 items-center justify-center text-[var(--color-text-muted)]">
			Loading…
		</div>
	{:else if stage === 'pick'}
		<section class="flex flex-1 flex-col gap-2">
			<p class="mb-2 text-sm text-[var(--color-text-muted)]">
				Pick the Wi-Fi the sorter should join. Signal strength shown on the right.
			</p>

			{#if scanError}
				<div class="border border-[var(--color-danger)] bg-[color:var(--color-danger)]/10 px-3 py-2 text-sm text-[var(--color-danger)]">
					{scanError}
				</div>
			{/if}

			{#if scanning && networks.length === 0}
				<div class="border border-[var(--color-border)] px-4 py-6 text-center text-sm text-[var(--color-text-muted)]">
					Scanning the 2.4 / 5 GHz bands…
				</div>
			{:else if networks.length === 0}
				<div class="border border-[var(--color-border)] px-4 py-6 text-center text-sm text-[var(--color-text-muted)]">
					No networks visible. Try the Rescan button.
				</div>
			{/if}

			<ul class="flex flex-col">
				{#each networks as net (net.ssid)}
					<li>
						<button
							type="button"
							class="flex w-full items-center justify-between border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-left hover:bg-[#1d1d1d]"
							onclick={() => choose(net)}
						>
							<div class="min-w-0">
								<div class="truncate text-base text-[var(--color-text)]">{net.ssid}</div>
								<div class="text-xs text-[var(--color-text-muted)]">
									{net.security || 'open'}
									{#if net.in_use} · current{/if}
								</div>
							</div>
							<div class="flex items-center gap-3 text-[var(--color-text-muted)]">
								<span class="font-mono text-xs">{net.signal}%</span>
								<SignalBars signal={net.signal} />
							</div>
						</button>
					</li>
				{/each}
			</ul>

			<button
				type="button"
				class="mt-3 self-start text-sm text-[var(--color-text-muted)] underline-offset-2 hover:text-[var(--color-text)] hover:underline"
				onclick={chooseHidden}
			>
				+ Add a hidden network manually
			</button>
		</section>
	{:else if stage === 'auth' || stage === 'submitting'}
		<form class="flex flex-1 flex-col gap-4" onsubmit={submit}>
			<button
				type="button"
				class="-mt-2 self-start text-xs uppercase tracking-wider text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
				onclick={back}
				disabled={stage === 'submitting'}
			>
				← Back
			</button>

			<div>
				<div class="text-xs uppercase tracking-wider text-[var(--color-text-muted)]">Network</div>
				{#if selected}
					<div class="mt-1 text-base text-[var(--color-text)]">{selected.ssid}</div>
					<div class="text-xs text-[var(--color-text-muted)]">{selected.security || 'open'}</div>
				{:else}
					<label class="mt-1 block">
						<input
							type="text"
							bind:value={hiddenSsid}
							placeholder="hidden SSID"
							class="w-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-base"
							autocomplete="off"
							autocapitalize="none"
							spellcheck="false"
						/>
					</label>
				{/if}
			</div>

			{#if !selectedIsOpen}
				<label class="block">
					<div class="text-xs uppercase tracking-wider text-[var(--color-text-muted)]">Password</div>
					<div class="mt-1 flex">
						<input
							type={showPassword ? 'text' : 'password'}
							bind:value={password}
							autocomplete="new-password"
							autocapitalize="none"
							spellcheck="false"
							class="w-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-base"
							placeholder="Wi-Fi password"
						/>
						<button
							type="button"
							class="border border-l-0 border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs uppercase tracking-wider text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
							onclick={() => (showPassword = !showPassword)}
						>
							{showPassword ? 'Hide' : 'Show'}
						</button>
					</div>
				</label>
			{/if}

			<button
				type="button"
				class="-mt-2 self-start text-xs uppercase tracking-wider text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
				onclick={() => (showAdvanced = !showAdvanced)}
			>
				{showAdvanced ? '− Hide advanced' : '+ Advanced (optional)'}
			</button>

			{#if showAdvanced}
				<label class="block">
					<div class="text-xs uppercase tracking-wider text-[var(--color-text-muted)]">
						Hostname override
					</div>
					<input
						type="text"
						bind:value={hostnameDraft}
						placeholder={status?.hostname ?? 'sorter-…'}
						autocomplete="off"
						autocapitalize="none"
						spellcheck="false"
						class="mt-1 w-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-base"
					/>
				</label>

				<label class="block">
					<div class="text-xs uppercase tracking-wider text-[var(--color-text-muted)]">
						SSH public key
					</div>
					<textarea
						bind:value={sshKeyDraft}
						rows="3"
						placeholder="ssh-ed25519 AAAA… you@laptop"
						autocomplete="off"
						autocapitalize="none"
						spellcheck="false"
						class="mt-1 w-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 font-mono text-xs"
					></textarea>
				</label>
			{/if}

			{#if submitError}
				<div class="border border-[var(--color-danger)] bg-[color:var(--color-danger)]/10 px-3 py-2 text-sm text-[var(--color-danger)]">
					{submitError}
				</div>
			{/if}

			<button
				type="submit"
				class="mt-2 border border-[var(--color-accent)] bg-[var(--color-accent)] px-4 py-3 text-base font-medium text-black hover:bg-[var(--color-accent-dark)] disabled:opacity-60"
				disabled={stage === 'submitting'}
			>
				{stage === 'submitting' ? 'Connecting…' : 'Connect'}
			</button>
		</form>
	{:else if stage === 'handoff' && handoff}
		<HandoffPanel
			ssid={handoff.ssid}
			nextUrl={handoff.nextUrl}
			lookupUrl={handoff.lookupUrl}
			teardownInS={handoff.teardownInS ?? 5}
		/>
	{/if}

	<footer class="mt-auto pt-8 text-center text-xs text-[var(--color-text-muted)]/70">
		SorterOS · captive portal
	</footer>
</main>
