<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { onMount } from 'svelte';

	type StatusPayload = {
		enabled: boolean;
		install_id: string;
		created_at: number | null;
		endpoint: string;
		sample_payload: Record<string, unknown>;
	};

	let status = $state<StatusPayload | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(true);
	let copied = $state(false);

	const FORGET_URL = 'https://hive.basically.website/forget';

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/status-ping/status`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			status = (await res.json()) as StatusPayload;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load status';
		} finally {
			loading = false;
		}
	}

	async function copyId() {
		if (!status) return;
		try {
			await navigator.clipboard.writeText(status.install_id);
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch {
			copied = false;
		}
	}

	function fmtDate(ts: number | null): string {
		if (!ts) return 'unknown';
		return new Date(ts * 1000).toLocaleString();
	}

	onMount(load);
</script>

<svelte:head>
	<title>Telemetry · Sorter</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<AppHeader />

<main class="page">
	<h1>Anonymous status ping</h1>
	<p class="lede">
		Once an hour, this machine sends a small anonymous report so we know how many machines are out
		there, what software they run, and roughly how much they sort. It carries a random install ID —
		never your Hive account. Full field list is in the docs under
		<em>Sorter → Under the hood → What leaves the machine</em>.
	</p>

	{#if loading}
		<p>Loading…</p>
	{:else if error}
		<p class="error">Couldn't load status: {error}</p>
	{:else if status}
		<section class="card">
			<div class="row">
				<span class="label">Status</span>
				<span class="value">
					{#if status.enabled}
						<span class="on">On</span>
					{:else}
						<span class="off">Off</span> — disabled via SORTER_BASE_REPORTING_OFF
					{/if}
				</span>
			</div>
			<div class="row">
				<span class="label">Install ID</span>
				<span class="value mono">
					{status.install_id}
					<button class="copy" onclick={copyId}>{copied ? 'Copied' : 'Copy'}</button>
				</span>
			</div>
			<div class="row">
				<span class="label">First seen</span>
				<span class="value">{fmtDate(status.created_at)}</span>
			</div>
			<div class="row">
				<span class="label">Sends to</span>
				<span class="value mono">{status.endpoint}</span>
			</div>
		</section>

		<h2>Delete this data</h2>
		<p>
			To have everything tied to this install ID erased, paste the ID above into the deletion form:
			<a href={FORGET_URL} target="_blank" rel="noreferrer">{FORGET_URL}</a>. To stop future pings,
			set <code>SORTER_BASE_REPORTING_OFF=1</code> in the machine environment and restart the
			backend.
		</p>

		<h2>Exactly what gets sent</h2>
		<pre class="payload">{JSON.stringify(status.sample_payload, null, 2)}</pre>
	{/if}
</main>

<style>
	.page {
		max-width: 720px;
		margin: 0 auto;
		padding: 1.5rem 1rem 3rem;
	}
	h1 {
		font-size: 1.4rem;
		margin: 0 0 0.5rem;
	}
	h2 {
		font-size: 1.05rem;
		margin: 1.75rem 0 0.5rem;
	}
	.lede {
		color: var(--color-text-muted, #666);
		font-size: 0.9rem;
		line-height: 1.5;
	}
	.card {
		border: 1px solid var(--color-border, #ddd);
		background: var(--color-surface, #fafafa);
		padding: 1rem;
		margin: 1rem 0;
	}
	.row {
		display: flex;
		gap: 1rem;
		padding: 0.4rem 0;
		border-bottom: 1px solid var(--color-border, #eee);
		font-size: 0.9rem;
	}
	.row:last-child {
		border-bottom: none;
	}
	.label {
		width: 8rem;
		flex: none;
		color: var(--color-text-muted, #666);
	}
	.value {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.mono {
		font-family: ui-monospace, monospace;
	}
	.on {
		color: var(--color-success, #2a7);
		font-weight: 600;
	}
	.off {
		color: var(--color-text-muted, #999);
		font-weight: 600;
	}
	.copy {
		font-size: 0.75rem;
		padding: 0.1rem 0.5rem;
		cursor: pointer;
		border: 1px solid var(--color-border, #ccc);
		background: transparent;
	}
	.error {
		color: var(--color-danger, #c33);
	}
	.payload {
		background: var(--color-surface, #f4f4f4);
		border: 1px solid var(--color-border, #ddd);
		padding: 1rem;
		overflow-x: auto;
		font-size: 0.8rem;
		line-height: 1.4;
	}
	code {
		font-family: ui-monospace, monospace;
		background: var(--color-surface, #f0f0f0);
		padding: 0.05rem 0.3rem;
	}
</style>
