<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getApiBaseUrl } from '$lib/api';
	import { Button, Alert } from '$lib/components/primitives';
	import Spinner from '$lib/components/Spinner.svelte';

	type Phase = 'waiting' | 'found' | 'invalid' | 'expired';

	type SorterInfo = {
		ip: string;
		hostname?: string;
		port?: number;
	};

	let phase = $state<Phase>('waiting');
	let info = $state<SorterInfo | null>(null);
	let elapsed = $state(0);

	let privKey: CryptoKey | null = null;
	let rendezvousId = '';
	let poll: ReturnType<typeof setInterval> | null = null;
	let clock: ReturnType<typeof setInterval> | null = null;

	// Give up polling after this long — matches the backend TTL window.
	const TIMEOUT_S = 600;
	const POLL_MS = 2000;

	function b64urlToBytes(s: string): Uint8Array {
		const b64 = s.replace(/-/g, '+').replace(/_/g, '/');
		const pad = b64.length % 4 ? '='.repeat(4 - (b64.length % 4)) : '';
		const bin = atob(b64 + pad);
		const out = new Uint8Array(bin.length);
		for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
		return out;
	}

	function b64ToBytes(s: string): Uint8Array {
		const bin = atob(s);
		const out = new Uint8Array(bin.length);
		for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
		return out;
	}

	function parseFragment(): { id: string; key: string } | null {
		const hash = window.location.hash.replace(/^#/, '');
		if (!hash) return null;
		const params = new URLSearchParams(hash);
		const id = params.get('id') ?? '';
		const key = params.get('k') ?? '';
		if (!id || !key) return null;
		return { id, key };
	}

	function sorterUrl(): string {
		if (!info) return '';
		const port = info.port && info.port !== 80 ? `:${info.port}` : '';
		return `http://${info.ip}${port}/`;
	}

	async function importPrivateKey(b64url: string): Promise<CryptoKey> {
		const der = b64urlToBytes(b64url);
		return crypto.subtle.importKey(
			'pkcs8',
			der as BufferSource,
			{ name: 'RSA-OAEP', hash: 'SHA-256' },
			false,
			['decrypt']
		);
	}

	async function tryDecrypt(ciphertextB64: string): Promise<SorterInfo | null> {
		if (!privKey) return null;
		try {
			const ct = b64ToBytes(ciphertextB64);
			const plain = await crypto.subtle.decrypt(
				{ name: 'RSA-OAEP' },
				privKey,
				ct as BufferSource
			);
			const obj = JSON.parse(new TextDecoder().decode(plain));
			if (obj && typeof obj.ip === 'string') {
				return { ip: obj.ip, hostname: obj.hostname, port: obj.port };
			}
		} catch {
			// Junk POST (or a key mismatch) — ignore and keep polling.
		}
		return null;
	}

	async function pollOnce() {
		const base = getApiBaseUrl();
		try {
			const res = await fetch(`${base}/api/machine-ip-lookup/${encodeURIComponent(rendezvousId)}`, {
				headers: { Accept: 'application/json' }
			});
			if (!res.ok) return;
			const data = await res.json();
			if (!data.ready || !data.ciphertext) return;
			const decoded = await tryDecrypt(data.ciphertext);
			if (decoded) {
				info = decoded;
				phase = 'found';
				stopTimers();
			}
		} catch {
			// transient network error — next tick retries
		}
	}

	function stopTimers() {
		if (poll) clearInterval(poll);
		if (clock) clearInterval(clock);
		poll = null;
		clock = null;
	}

	onMount(async () => {
		const frag = parseFragment();
		if (!frag) {
			phase = 'invalid';
			return;
		}
		rendezvousId = frag.id;
		try {
			privKey = await importPrivateKey(frag.key);
		} catch {
			phase = 'invalid';
			return;
		}

		void pollOnce();
		poll = setInterval(() => void pollOnce(), POLL_MS);
		clock = setInterval(() => {
			elapsed += 1;
			if (elapsed >= TIMEOUT_S && phase === 'waiting') {
				phase = 'expired';
				stopTimers();
			}
		}, 1000);
	});

	onDestroy(stopTimers);
</script>

<svelte:head>
	<title>Find your sorter · Hive</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="mx-auto flex min-h-screen w-full max-w-xl flex-col justify-center gap-6 px-5 py-10">
	<div class="text-center">
		<div class="font-mono text-sm tracking-wider text-[var(--color-text-muted)] uppercase">
			SorterOS onboarding
		</div>
		<h1 class="mt-1 text-2xl font-bold text-[var(--color-text)]">Find your sorter</h1>
	</div>

	{#if phase === 'invalid'}
		<Alert variant="danger" title="Link incomplete">
			This page needs the one-time key that the sorter's setup screen puts in the link. Re-open the
			"Find my sorter" link from the sorter's Wi-Fi setup page, or use the
			<span class="font-mono">.local</span> address it showed instead.
		</Alert>
	{:else if phase === 'waiting'}
		<div
			class="flex flex-col items-center gap-4 border border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-10 text-center"
		>
			<Spinner />
			<div class="text-[var(--color-text)]">Waiting for your sorter to come online…</div>
			<p class="max-w-sm text-sm text-[var(--color-text-muted)]">
				Make sure you've rejoined your normal Wi-Fi. As soon as the sorter connects to the same
				network it will report its address here — this stays private, the address is encrypted end
				to end and only your browser can read it.
			</p>
			<div class="font-mono text-xs text-[var(--color-text-muted)]">
				{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')} elapsed
			</div>
		</div>
	{:else if phase === 'found' && info}
		<div
			class="flex flex-col items-center gap-5 border border-[var(--color-success)]/40 bg-[var(--color-success)]/[0.06] px-6 py-10 text-center"
		>
			<div class="text-lg font-semibold text-[var(--color-text)]">Your sorter is online! 🎉</div>
			{#if info.hostname}
				<div class="font-mono text-sm text-[var(--color-text-muted)]">{info.hostname}</div>
			{/if}
			<div class="font-mono text-base break-all text-[var(--color-text)]">{sorterUrl()}</div>
			<a href={sorterUrl()} class="w-full max-w-xs">
				<Button variant="primary">Open the sorter →</Button>
			</a>
			<p class="max-w-sm text-xs text-[var(--color-text-muted)]">
				Bookmark this address — it's your sorter's dashboard on your local network.
			</p>
		</div>
	{:else if phase === 'expired'}
		<Alert variant="warning" title="No sorter reported in">
			Ten minutes passed without the sorter checking in. It may have failed to join Wi-Fi (wrong
			password?) or your network blocks the connection. Re-run Wi-Fi setup on the sorter, or try the
			<span class="font-mono">.local</span> address it showed.
		</Alert>
	{/if}
</div>
