<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth.svelte';
	import { api, type TeacherJobSummary } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Button from '$lib/components/Button.svelte';

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

	function statusTone(status: string): 'primary' | 'info' | 'success' | 'warning' | 'neutral' {
		switch (status) {
			case 'running':
				return 'primary';
			case 'pending':
			case 'queued':
				return 'info';
			case 'done':
				return 'success';
			case 'error':
				return 'warning';
			default:
				return 'neutral';
		}
	}

	function pct(job: TeacherJobSummary): number {
		if (job.total <= 0) return 0;
		return Math.round((job.processed / job.total) * 100);
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('en-US', {
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
		if (value == null) return '-';
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
	<title>Teacher jobs - Hive</title>
</svelte:head>

<PageHeader
	title="Teacher jobs"
	description={`Re-detection jobs started from the samples list. The page refreshes every ${REFRESH_MS / 1000} seconds.`}
>
	{#snippet actions()}
		<span class="num text-sm text-ink-muted">{jobs.length} job{jobs.length === 1 ? '' : 's'}, newest first</span>
	{/snippet}
</PageHeader>

{#if loading && jobs.length === 0}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if error && jobs.length === 0}
	<Alert tone="danger">{error}</Alert>
{:else if jobs.length === 0}
	<Panel><EmptyState icon={Sparkles} title="No teacher jobs yet">Start one from the samples page.</EmptyState></Panel>
{:else}
	<div class="flex flex-col gap-(--gap-panels)">
		<section class="flex flex-col gap-(--gap-panels)">
			<h2 class="text-base font-semibold text-ink">
				Running <span class="num font-normal text-ink-muted">{activeJobs.length}</span>
			</h2>
			{#if activeJobs.length === 0}
				<Panel><EmptyState title="Nothing running">Start a job from the samples page.</EmptyState></Panel>
			{:else}
				{#each activeJobs as job (job.id)}
					<Panel flush>
						<div class="flex flex-wrap items-center gap-3 px-(--pad-panel) py-3">
							<Badge tone={statusTone(job.status)} dot>{sentence(job.status)}</Badge>
							<a href={`/admin/teacher-jobs/${job.id}`} class="text-base font-semibold text-ink hover:underline"
								>Job <span class="font-mono">{job.id.slice(0, 8)}</span></a
							>
							<span class="font-mono text-sm text-ink-muted">{job.openrouter_model}</span>
							<div class="ml-auto flex items-center gap-2">
								<Button size="sm" variant="ghost" href={`/admin/teacher-jobs/${job.id}`} icon={ArrowRight}>Details</Button>
								<Button size="sm" onclick={() => cancel(job.id)}>Cancel</Button>
							</div>
						</div>
						<div class="-ml-px grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5">
							<div class="border-t border-l border-line"><Stat label="Processed" value={job.processed} unit={`of ${job.total}`} hint={`${pct(job)}%`} /></div>
							<div class="border-t border-l border-line"><Stat label="Succeeded" value={job.succeeded} tone="success" /></div>
							<div class="border-t border-l border-line"><Stat label="Failed" value={job.failed} tone={job.failed > 0 ? 'warning' : undefined} /></div>
							<div class="border-t border-l border-line"><Stat label="Left" value={Math.max(0, job.total - job.processed)} /></div>
							<div class="border-t border-l border-line" title="What OpenRouter has billed so far, and the total at the average cost a sample.">
								<Stat
									label="Cost"
									value={formatUsd(job.cost_usd)}
									hint={job.cost_usd_estimated_total != null
										? `About ${formatUsd(job.cost_usd_estimated_total)} in all`
										: undefined}
								/>
							</div>
						</div>
						<div class="border-t border-line px-(--pad-panel) py-3">
							<ProgressBar label={`Job ${job.id.slice(0, 8)} progress`} value={pct(job)} />
							<div class="mt-3 flex flex-wrap items-center gap-2 text-sm">
								{#each filterChips(job.filter as Record<string, unknown> | null) as [key, value] (key)}
									<Badge>{key} <span class="text-ink">{value}</span></Badge>
								{:else}
									<span class="text-ink-muted">Every sample, no filter</span>
								{/each}
								<span class="ml-auto text-ink-muted">Started {formatDate(job.started_at ?? job.created_at)}</span>
							</div>
						</div>
						{#if job.last_error}
							<div class="px-(--pad-panel) pb-3"><Alert tone="warning" title="Last error">{job.last_error}</Alert></div>
						{/if}
					</Panel>
				{/each}
			{/if}
		</section>

		<Panel title="Finished" flush>
			{#snippet actions()}<span class="num text-sm text-ink-muted">{historyJobs.length}</span>{/snippet}
			{#if historyJobs.length === 0}
				<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">No finished jobs yet.</p>
			{:else}
				<ul class="divide-y divide-line border-t border-line">
					{#each historyJobs as job (job.id)}
						<li class="flex flex-wrap items-center gap-3 px-(--pad-panel) py-2.5 text-sm">
							<Badge tone={statusTone(job.status)}>{sentence(job.status)}</Badge>
							<a href={`/admin/teacher-jobs/${job.id}`} class="font-mono text-ink hover:underline">{job.id.slice(0, 8)}</a>
							<span class="font-mono text-ink-muted">{job.openrouter_model}</span>
							<span class="num text-ink"
								>{job.processed} of {job.total}<span class="text-ink-muted"
									>, {job.succeeded} succeeded{job.failed > 0 ? `, ${job.failed} failed` : ''}</span
								></span
							>
							<span class="num text-ink-muted" title="Billed by OpenRouter">{formatUsd(job.cost_usd)}</span>
							<span class="ml-auto text-ink-muted">{formatDate(job.finished_at ?? job.created_at)}</span>
						</li>
					{/each}
				</ul>
			{/if}
		</Panel>
	</div>
{/if}
