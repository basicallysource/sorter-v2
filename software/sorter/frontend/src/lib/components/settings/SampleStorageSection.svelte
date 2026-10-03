<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Trash2 from '@lucide/svelte/icons/trash';
	import HardDrive from '@lucide/svelte/icons/hard-drive';
	import Button from '$lib/components/ui/Button.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	const machine = getMachineContext();

	type SessionInfo = {
		session_id: string;
		session_name: string | null;
		created_at: number | null;
		sample_count: number;
		size_bytes: number;
	};

	let sessions = $state<SessionInfo[]>([]);
	let totalSamples = $state(0);
	let totalBytes = $state(0);
	let loading = $state(true);
	let errorMsg = $state<string | null>(null);
	let deleting = $state<string | null>(null);
	let purging = $state(false);
	let confirmPurge = $state(false);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB'];
		const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
	}

	function formatDate(ts: number | null): string {
		if (!ts) return '—';
		return new Date(ts * 1000).toLocaleDateString('de-DE', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	async function loadStorage() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/samples/storage`);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			sessions = data.sessions ?? [];
			totalSamples = data.total_samples ?? 0;
			totalBytes = data.total_bytes ?? 0;
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load sample storage info';
		} finally {
			loading = false;
		}
	}

	async function deleteSession(sessionId: string) {
		deleting = sessionId;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/samples/storage/${sessionId}`, {
				method: 'DELETE'
			});
			if (!res.ok) throw new Error(await res.text());
			await loadStorage();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to delete session';
		} finally {
			deleting = null;
		}
	}

	async function purgeAll() {
		purging = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/samples/storage`, {
				method: 'DELETE'
			});
			if (!res.ok) throw new Error(await res.text());
			confirmPurge = false;
			await loadStorage();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to purge samples';
		} finally {
			purging = false;
		}
	}

	onMount(() => {
		loadStorage();
	});
</script>

{#if loading}
	<div class="flex items-center gap-2 px-(--pad-panel) py-4 text-sm text-ink-muted">
		<Spinner size={14} /> Loading the sample storage
	</div>
{:else}
	<div class="flex flex-wrap items-center justify-between gap-3 px-(--pad-panel) pb-4">
		<p class="text-sm text-ink">
			<span class="num font-medium">{totalSamples.toLocaleString()}</span> samples in
			<span class="num font-medium">{sessions.length}</span>
			{sessions.length === 1 ? 'session' : 'sessions'},
			<span class="num text-ink-muted">{formatBytes(totalBytes)}</span>
		</p>
		{#if sessions.length > 0}
			{#if confirmPurge}
				<div class="flex items-center gap-2">
					<span class="text-sm text-danger-ink">Delete every session?</span>
					<Button variant="ghost" size="sm" onclick={() => (confirmPurge = false)}>Cancel</Button>
					<Button variant="danger" size="sm" loading={purging} onclick={purgeAll}>Delete all</Button>
				</div>
			{:else}
				<Button variant="danger" size="sm" icon={Trash2} onclick={() => (confirmPurge = true)}>
					Delete all
				</Button>
			{/if}
		{/if}
	</div>

	{#if sessions.length > 0}
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>Session</th>
						<th>Date</th>
						<th class="num">Samples</th>
						<th class="num">Size</th>
						<th><span class="sr-only">Actions</span></th>
					</tr>
				</thead>
				<tbody>
					{#each sessions as session}
						<tr>
							<td>
								<div class="font-mono">{session.session_id}</div>
								{#if session.session_name}
									<div class="text-ink-muted">{session.session_name}</div>
								{/if}
							</td>
							<td class="text-ink-muted">{formatDate(session.created_at)}</td>
							<td class="num">{session.sample_count.toLocaleString()}</td>
							<td class="num text-ink-muted">{formatBytes(session.size_bytes)}</td>
							<td class="text-right">
								<Button
									variant="ghost"
									size="sm"
									icon={Trash2}
									loading={deleting === session.session_id}
									onclick={() => deleteSession(session.session_id)}
								>
									Delete
								</Button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<div class="px-(--pad-panel) pb-(--pad-panel)">
			<EmptyState icon={HardDrive} title="No sample sessions on disk">
				Sessions appear here as the machine saves samples.
			</EmptyState>
		</div>
	{/if}

	{#if errorMsg}
		<div class="px-(--pad-panel) pb-(--pad-panel)">
			<Alert tone="danger">{errorMsg}</Alert>
		</div>
	{/if}
{/if}
