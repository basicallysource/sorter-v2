<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
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
	<title>Telemetry - Sorter</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-3xl flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader
			title="Anonymous status ping"
			description="Once an hour this machine sends a small anonymous report, so we know how many machines are out there, what software they run and roughly how much they sort. It carries a random install ID, never your Hive account. The full field list is in the docs under Sorter, Under the hood, What leaves the machine."
		/>

		{#if loading}
			<Panel>
				<p class="flex items-center gap-2 text-sm text-ink-muted">
					<Spinner size={16} />
					Loading the status
				</p>
			</Panel>
		{:else if error}
			<Alert tone="danger" title="The status did not load">{error}</Alert>
		{:else if status}
			<Panel flush>
				<div class="divide-y divide-line">
					<SettingRow
						label="Status"
						help={status.enabled ? undefined : 'Turned off with SORTER_BASE_REPORTING_OFF.'}
					>
						<Badge tone={status.enabled ? 'success' : 'neutral'} dot>{status.enabled ? 'On' : 'Off'}</Badge>
					</SettingRow>
					<SettingRow label="Install ID">
						<span class="font-mono text-sm break-all text-ink">{status.install_id}</span>
						<Button size="sm" onclick={copyId}>{copied ? 'Copied' : 'Copy'}</Button>
					</SettingRow>
					<SettingRow label="First seen">
						<span class="text-sm text-ink">{fmtDate(status.created_at)}</span>
					</SettingRow>
					<SettingRow label="Sends to">
						<span class="font-mono text-sm break-all text-ink">{status.endpoint}</span>
					</SettingRow>
				</div>
			</Panel>

			<Panel title="Delete this data">
				<p class="text-sm text-ink-muted">
					To have everything tied to this install ID erased, paste the ID above into the deletion form:
					<a href={FORGET_URL} target="_blank" rel="noreferrer" class="text-primary-ink hover:underline">
						{FORGET_URL}
					</a>. To stop future pings, set
					<code class="rounded-badge bg-well px-1 font-mono text-ink">SORTER_BASE_REPORTING_OFF=1</code>
					in the machine environment and restart the backend.
				</p>
			</Panel>

			<Panel title="Exactly what gets sent">
				<pre class="overflow-x-auto rounded-control bg-well p-4 text-xs leading-5 text-ink">{JSON.stringify(
						status.sample_payload,
						null,
						2
					)}</pre>
			</Panel>
		{/if}
	</div>
</AppShell>
