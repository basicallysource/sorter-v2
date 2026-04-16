<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Trash2, HardDrive } from 'lucide-svelte';

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
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
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
	<div class="px-1 py-4 text-sm text-text-muted">Loading sample storage…</div>
{:else}
	<div class="flex flex-col gap-4">
		<!-- Summary bar -->
		<div class="flex items-center justify-between border border-border bg-surface px-4 py-3">
			<div class="flex items-center gap-3">
				<HardDrive size={16} class="text-text-muted" />
				<span class="text-sm text-text">
					<span class="font-semibold">{totalSamples.toLocaleString()}</span> samples across
					<span class="font-semibold">{sessions.length}</span>
					{sessions.length === 1 ? 'session' : 'sessions'}
					<span class="text-text-muted">({formatBytes(totalBytes)})</span>
				</span>
			</div>
			{#if sessions.length > 0}
				{#if confirmPurge}
					<div class="flex items-center gap-2">
						<span class="text-xs text-danger">Delete everything?</span>
						<button
							class="border border-danger/30 bg-danger/[0.06] px-3 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-danger/[0.12] disabled:opacity-50"
							disabled={purging}
							onclick={purgeAll}
						>
							{purging ? 'Purging…' : 'Yes, purge all'}
						</button>
						<button
							class="border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition-colors hover:bg-bg"
							onclick={() => (confirmPurge = false)}
						>
							Cancel
						</button>
					</div>
				{:else}
					<button
						class="flex items-center gap-1.5 border border-danger/30 bg-danger/[0.06] px-3 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-danger/[0.12]"
						onclick={() => (confirmPurge = true)}
					>
						<Trash2 size={12} />
						Purge all
					</button>
				{/if}
			{/if}
		</div>

		<!-- Session table -->
		{#if sessions.length > 0}
			<div class="overflow-x-auto border border-border">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-border bg-surface text-left text-xs uppercase tracking-wider text-text-muted">
							<th class="px-4 py-2 font-medium">Session</th>
							<th class="px-4 py-2 font-medium">Date</th>
							<th class="px-4 py-2 text-right font-medium">Samples</th>
							<th class="px-4 py-2 text-right font-medium">Size</th>
							<th class="px-4 py-2 text-right font-medium">Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each sessions as session}
							<tr class="border-b border-border last:border-b-0 hover:bg-surface/50">
								<td class="px-4 py-2.5">
									<div class="font-mono text-xs text-text">{session.session_id}</div>
									{#if session.session_name}
										<div class="text-xs text-text-muted">{session.session_name}</div>
									{/if}
								</td>
								<td class="px-4 py-2.5 text-xs text-text-muted">{formatDate(session.created_at)}</td>
								<td class="px-4 py-2.5 text-right tabular-nums">{session.sample_count.toLocaleString()}</td>
								<td class="px-4 py-2.5 text-right text-text-muted tabular-nums">{formatBytes(session.size_bytes)}</td>
								<td class="px-4 py-2.5 text-right">
									<button
										class="inline-flex items-center gap-1 border border-danger/30 bg-danger/[0.06] px-2 py-1 text-xs text-danger transition-colors hover:bg-danger/[0.12] disabled:opacity-50"
										disabled={deleting === session.session_id}
										onclick={() => deleteSession(session.session_id)}
									>
										<Trash2 size={11} />
										{deleting === session.session_id ? 'Deleting…' : 'Delete'}
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<div class="border border-border bg-surface px-4 py-6 text-center text-sm text-text-muted">
				No sample sessions on disk.
			</div>
		{/if}

		{#if errorMsg}
			<div class="border border-danger/30 bg-danger/[0.06] px-4 py-2.5 text-sm text-danger">
				{errorMsg}
			</div>
		{/if}
	</div>
{/if}
