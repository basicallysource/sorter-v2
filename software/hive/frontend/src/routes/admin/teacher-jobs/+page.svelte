<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth.svelte';
	import { api, type TeacherJobSummary } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	const REFRESH_MS = 3000;

	let jobs = $state<TeacherJobSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void load();
		// Keep refreshing so an admin parked on this page sees progress live.
		timer = setInterval(load, REFRESH_MS);
		return () => {
			if (timer) clearInterval(timer);
		};
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	async function load() {
		try {
			jobs = await api.listTeacherJobs();
			error = null;
		} catch (e: unknown) {
			error =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Failed to load jobs';
		} finally {
			loading = false;
		}
	}

	async function cancel(jobId: string) {
		try {
			const updated = await api.cancelTeacherJob(jobId);
			jobs = jobs.map((j) => (j.id === updated.id ? updated : j));
		} catch {
			// ignore — next refresh will reconcile
		}
	}

	function statusClass(status: string): string {
		// Tinted background by status so the eye can skim the list for "what's live now".
		switch (status) {
			case 'running':
				return 'bg-primary text-white';
			case 'pending':
				return 'bg-info text-white';
			case 'done':
				return 'bg-success text-white';
			case 'cancelled':
				return 'bg-border text-text';
			default:
				return 'bg-bg text-text';
		}
	}

	function pct(job: TeacherJobSummary): number {
		if (job.total <= 0) return 0;
		return Math.round((job.processed / job.total) * 100);
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('de-DE', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function filterChips(filter: Record<string, unknown> | null): [string, string][] {
		if (!filter) return [];
		return Object.entries(filter)
			.filter(([, v]) => v !== null && v !== undefined && v !== '')
			.map(([k, v]) => [k, String(v)] as [string, string]);
	}

	function formatUsd(value: number | null | undefined): string {
		if (value == null) return '—';
		if (value === 0) return '$0.00';
		// Sub-cent costs are common for single Gemini calls; show 4 decimals so $0.0008
		// isn't displayed as "$0.00".
		if (Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
		return `$${value.toFixed(2)}`;
	}

	const activeJobs = $derived(
		jobs.filter((j) => j.status === 'pending' || j.status === 'running')
	);
	const historyJobs = $derived(
		jobs.filter((j) => j.status === 'done' || j.status === 'cancelled')
	);
</script>

<svelte:head>
	<title>Teacher Jobs - Hive</title>
</svelte:head>

<div class="mb-6 flex items-end justify-between gap-3">
	<div>
		<div class="mb-1 text-xs text-text-muted">
			<a href="/samples" class="hover:underline">Samples</a>
			<span class="mx-1">/</span>
			<span>Admin</span>
			<span class="mx-1">/</span>
			<span>Teacher Jobs</span>
		</div>
		<h1 class="text-2xl font-bold text-text">Teacher Jobs</h1>
		<p class="mt-1 text-sm text-text-muted">
			Gemini re-detection jobs queued from the samples list. Refreshes every {REFRESH_MS / 1000}s.
		</p>
	</div>
	<div class="text-xs text-text-muted">
		{jobs.length} job{jobs.length === 1 ? '' : 's'} (most recent first)
	</div>
</div>

{#if loading && jobs.length === 0}
	<Spinner />
{:else if error && jobs.length === 0}
	<div class="border border-border bg-surface px-6 py-12 text-center text-sm text-text-muted">
		{error}
	</div>
{:else if jobs.length === 0}
	<div class="border border-border bg-surface px-6 py-12 text-center text-sm text-text-muted">
		No teacher jobs yet. Start one from the samples page.
	</div>
{:else}
	<!-- ACTIVE section: big cards so an admin opening this page immediately sees the live state. -->
	<section class="mb-8">
		<div class="mb-3 flex items-baseline justify-between gap-3">
			<h2 class="text-lg font-semibold text-text">
				Active
				<span class="ml-1 text-sm font-normal text-text-muted">
					({activeJobs.length} {activeJobs.length === 1 ? 'job' : 'jobs'})
				</span>
			</h2>
			<span class="text-[11px] text-text-muted">Auto-refresh every {REFRESH_MS / 1000}s</span>
		</div>
		{#if activeJobs.length === 0}
			<div class="border border-border bg-surface px-6 py-10 text-center text-sm text-text-muted">
				No active jobs. Start one from the samples page.
			</div>
		{:else}
			<div class="space-y-4">
				{#each activeJobs as job (job.id)}
					<div class="border-2 border-primary bg-surface">
						<div class="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
							<span class="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider {statusClass(job.status)}">
								{job.status}
							</span>
							<a
								href={`/admin/teacher-jobs/${job.id}`}
								class="text-lg font-semibold text-text hover:text-primary hover:underline"
							>
								Job {job.id.slice(0, 8)}
							</a>
							<span class="text-xs text-text-muted">{job.openrouter_model}</span>
							<div class="ml-auto flex items-center gap-2">
								<a href={`/admin/teacher-jobs/${job.id}`} class="text-xs text-primary hover:underline">View detail →</a>
								<Button variant="secondary" size="sm" onclick={() => cancel(job.id)}>Cancel</Button>
							</div>
						</div>
						<div class="grid gap-4 px-5 py-4 sm:grid-cols-3 xl:grid-cols-5">
							<div>
								<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Processed</div>
								<div class="tabular-nums text-2xl font-bold text-text">{job.processed}<span class="text-base font-normal text-text-muted"> / {job.total}</span></div>
								<div class="text-[11px] text-text-muted">{pct(job)}%</div>
							</div>
							<div>
								<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Succeeded</div>
								<div class="tabular-nums text-2xl font-bold text-success">{job.succeeded}</div>
							</div>
							<div>
								<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Failed</div>
								<div class="tabular-nums text-2xl font-bold {job.failed > 0 ? 'text-warning-strong' : 'text-text-muted'}">{job.failed}</div>
							</div>
							<div>
								<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Remaining</div>
								<div class="tabular-nums text-2xl font-bold text-text">{Math.max(0, job.total - job.processed)}</div>
							</div>
							<div title="Real billed cost from OpenRouter so far · projected total based on running average per sample.">
								<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Cost</div>
								<div class="tabular-nums text-2xl font-bold text-text">{formatUsd(job.cost_usd)}</div>
								<div class="text-[11px] text-text-muted">
									{#if job.cost_usd_estimated_total != null}
										est. total {formatUsd(job.cost_usd_estimated_total)}
									{:else}
										est. total —
									{/if}
								</div>
							</div>
						</div>
						<div class="h-2 bg-bg">
							<div class="h-full bg-primary transition-[width] duration-300" style="width: {pct(job)}%"></div>
						</div>
						<div class="flex flex-wrap items-center gap-2 px-5 py-2 text-[11px]">
							{#each filterChips(job.filter as Record<string, unknown> | null) as [key, value] (key)}
								<span class="border border-border bg-bg px-1.5 py-0.5 text-text-muted">
									{key}=<span class="text-text">{value}</span>
								</span>
							{:else}
								<span class="text-text-muted">no filter (all samples)</span>
							{/each}
							<span class="ml-auto text-text-muted">
								started {formatDate(job.started_at ?? job.created_at)}
							</span>
						</div>
						{#if job.last_error}
							<div class="border-t border-border bg-warning-bg px-5 py-2 text-[11px] text-warning-strong">
								Last error: {job.last_error}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</section>

	<!-- HISTORY section: compact rows. -->
	<section>
		<div class="mb-3 flex items-baseline justify-between gap-3">
			<h2 class="text-sm font-semibold uppercase tracking-wider text-text-muted">
				History
				<span class="ml-1 normal-case text-text-muted">({historyJobs.length})</span>
			</h2>
		</div>
		{#if historyJobs.length === 0}
			<div class="border border-border bg-surface px-6 py-6 text-center text-xs text-text-muted">
				No finished jobs yet.
			</div>
		{:else}
			<div class="divide-y divide-border border border-border bg-surface">
				{#each historyJobs as job (job.id)}
					<div class="flex flex-wrap items-center gap-3 px-4 py-2.5">
						<span class="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider {statusClass(job.status)}">
							{job.status}
						</span>
						<a href={`/admin/teacher-jobs/${job.id}`} class="font-mono text-xs text-text-muted hover:text-primary hover:underline">
							{job.id.slice(0, 8)}
						</a>
						<span class="text-xs text-text-muted">{job.openrouter_model}</span>
						<span class="tabular-nums text-xs text-text">
							{job.processed}/{job.total}
							<span class="text-text-muted">
								· {job.succeeded} ok{job.failed > 0 ? ` · ${job.failed} failed` : ''}
							</span>
						</span>
						<span class="tabular-nums text-xs text-text-muted" title="Billed by OpenRouter">
							{formatUsd(job.cost_usd)}
						</span>
						<span class="ml-auto text-[11px] text-text-muted">
							{formatDate(job.finished_at ?? job.created_at)}
						</span>
						<a href={`/admin/teacher-jobs/${job.id}`} class="text-xs text-primary hover:underline">Details</a>
					</div>
				{/each}
			</div>
		{/if}
	</section>
{/if}
