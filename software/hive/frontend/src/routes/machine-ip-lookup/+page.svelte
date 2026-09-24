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
		// The Wi-Fi network it joined; null when it came online on a cable.
		ssid?: string | null;
	};

	let phase = $state<Phase>('waiting');
	let info = $state<SorterInfo | null>(null);
	let elapsed = $state(0);

	let privKey: CryptoKey | null = null;
	let pubKeyB64 = '';
	let keyPostedAt = 0;
	let startedAt = 0;
	let rendezvousId = '';
	let poll: ReturnType<typeof setInterval> | null = null;
	let clock: ReturnType<typeof setInterval> | null = null;

	// Give up after this long: the sorter stops reporting 15 minutes after the
	// Wi-Fi was chosen on its setup page.
	const TIMEOUT_S = 900;
	const POLL_MS = 2000;
	// Hive keeps the key in memory for ten minutes from the last post and
	// forgets it if it restarts, so the page re-posts it while it waits. A
	// failed post is retried on the next poll.
	const KEY_REFRESH_MS = 30_000;

	function b64ToBytes(s: string): Uint8Array {
		const bin = atob(s);
		const out = new Uint8Array(bin.length);
		for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
		return out;
	}

	function bytesToB64(buf: ArrayBuffer): string {
		const arr = new Uint8Array(buf);
		let bin = '';
		for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
		return btoa(bin);
	}

	// Only the id travels in the fragment now. The keypair is generated here
	// (this page is https, so WebCrypto is available) — the portal runs on
	// plain http where crypto.subtle is disabled, so it can't make keys.
	function parseFragment(): { id: string } | null {
		const hash = window.location.hash.replace(/^#/, '');
		if (!hash) return null;
		const params = new URLSearchParams(hash);
		const id = params.get('id') ?? '';
		if (!id) return null;
		return { id };
	}

	function sorterUrl(): string {
		if (!info) return '';
		const port = info.port && info.port !== 80 ? `:${info.port}` : '';
		return `http://${info.ip}${port}/`;
	}

	// Generate the keypair here and keep the private half in memory only; the
	// public half goes to Hive for the sorter to encrypt its address with.
	async function generateKey(): Promise<void> {
		const pair = await crypto.subtle.generateKey(
			{
				name: 'RSA-OAEP',
				modulusLength: 2048,
				publicExponent: new Uint8Array([1, 0, 1]),
				hash: 'SHA-256'
			},
			true,
			['encrypt', 'decrypt']
		);
		privKey = pair.privateKey;
		pubKeyB64 = bytesToB64(await crypto.subtle.exportKey('spki', pair.publicKey));
	}

	async function postKey(): Promise<void> {
		try {
			const res = await fetch(
				`${getApiBaseUrl()}/api/machine-ip-lookup/${encodeURIComponent(rendezvousId)}/pubkey`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ pubkey: pubKeyB64 })
				}
			);
			if (res.ok) keyPostedAt = Date.now();
		} catch {
			// transient network error: the next poll retries
		}
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
				return { ip: obj.ip, hostname: obj.hostname, port: obj.port, ssid: obj.ssid };
			}
		} catch {
			// Junk POST (or a key mismatch) — ignore and keep polling.
		}
		return null;
	}

	async function pollOnce() {
		if (Date.now() - keyPostedAt > KEY_REFRESH_MS) await postKey();
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
			await generateKey();
		} catch {
			phase = 'invalid';
			return;
		}

		startedAt = Date.now();
		void pollOnce();
		poll = setInterval(() => void pollOnce(), POLL_MS);
		// From the wall clock: a phone throttles timers in a background tab.
		clock = setInterval(() => {
			elapsed = Math.floor((Date.now() - startedAt) / 1000);
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
		<div class="font-mono text-sm tracking-wider text-text-muted uppercase">
			SorterOS onboarding
		</div>
		<h1 class="mt-1 text-2xl font-bold text-text">Find your sorter</h1>
	</div>

	{#if phase === 'invalid'}
		<Alert variant="danger" title="Link incomplete">
			This page needs the one-time id the sorter's setup screen puts in the link. Open the
			"Find my sorter" link from the sorter's Wi-Fi setup page again.
		</Alert>
	{:else if phase === 'waiting'}
		<div
			class="flex flex-col items-center gap-4 border border-border bg-surface px-6 py-10 text-center"
		>
			<Spinner size={32} />
			<div class="text-text">Waiting for your sorter to come online…</div>
			<p class="max-w-sm text-sm text-text-muted">
				Make sure you've rejoined your normal Wi-Fi. The sorter restarts to join it, which takes
				about two minutes, then reports its address here. The address is encrypted end to end, so
				only this browser can read it.
			</p>
			<p class="max-w-sm text-sm text-text-muted">
				If the sorter's setup network (<span class="font-mono">SorterOS-Setup-…</span>) shows up in
				your Wi-Fi list again, it couldn't join. Connect to it again to see why and try again.
			</p>
			<div class="font-mono text-xs text-text-muted">
				{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')} elapsed
			</div>
		</div>
	{:else if phase === 'found' && info}
		<div
			class="flex flex-col items-center gap-5 border border-success/40 bg-success/[0.06] px-6 py-10 text-center"
		>
			<div class="text-lg font-semibold text-text">Your sorter is online! 🎉</div>
			{#if info.hostname}
				<div class="font-mono text-sm text-text-muted">{info.hostname}</div>
			{/if}
			<div class="text-sm text-text-muted">
				{info.ssid ? `On the Wi-Fi network ${info.ssid}` : 'Connected by cable'}
			</div>
			<div class="font-mono text-base break-all text-text">{sorterUrl()}</div>
			<a href={sorterUrl()} class="w-full max-w-xs">
				<Button variant="primary">Open the sorter →</Button>
			</a>
			<p class="max-w-sm text-xs text-text-muted">
				Bookmark this address — it's your sorter's dashboard on your local network.
			</p>
		</div>
	{:else if phase === 'expired'}
		<Alert variant="warning" title="No sorter reported in">
			Fifteen minutes passed without the sorter checking in. If its setup network
			(<span class="font-mono">SorterOS-Setup-…</span>) is back in your Wi-Fi list, it couldn't
			join: connect to it and try again. Otherwise it's online but can't reach Hive, so try the
			<span class="font-mono">.local</span> address its setup page showed.
		</Alert>
	{/if}
</div>
