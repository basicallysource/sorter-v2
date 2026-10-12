<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/auth.svelte';
	import { api, type FleetMachine, type JobsSummary, type SwatchBackfillResult } from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Field from '$lib/components/Field.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';

	const REFRESH_MS = 5000;
	const RANGES = [
		{ value: '24', label: 'The last 24 hours' },
		{ value: '168', label: 'The last 7 days' },
		{ value: '720', label: 'The last 30 days' },
		{ value: 'all', label: 'All time' }
	];

	let summary = $state<JobsSummary | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let retrying = $state<string | null>(null);

	let machines = $state<FleetMachine[]>([]);
	let machineId = $state<string | undefined>(undefined);
	let range = $state<string>('24');
	let rerun = $state(false);
	let queueing = $state(false);
	let backfillError = $state<string | null>(null);
	let backfillResult = $state<SwatchBackfillResult | null>(null);

	const machineOptions = $derived(
		machines.filter((m) => !m.archived_at).map((m) => ({ value: m.id, label: m.name, hint: m.owner_display_name ?? m.owner_email ?? undefined }))
	);

	$effect(() => {
		if (!auth.initialized) return;
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void load();
		void api.getAllMachines().then((list) => (machines = list)).catch(() => {});
		const timer = setInterval(load, REFRESH_MS);
		return () => clearInterval(timer);
	});

	function message(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : fallback;
	}

	async function load() {
		try {
			summary = await api.getJobsSummary();
			error = null;
		} catch (e: unknown) {
			error = message(e, 'Failed to load the job queue');
		} finally {
			loading = false;
		}
	}

	async function retry(jobId: string) {
		retrying = jobId;
		try {
			await api.retryJob(jobId);
			await load();
		} catch (e: unknown) {
			error = message(e, 'Failed to retry the job');
		} finally {
			retrying = null;
		}
	}

	async function queueBackfill() {
		if (!machineId || queueing) return;
		queueing = true;
		backfillError = null;
		backfillResult = null;
		try {
			const since = range === 'all' ? null : new Date(Date.now() - Number(range) * 3600_000).toISOString();
			backfillResult = await api.backfillSwatches({ machine_id: machineId, since, rerun });
			await load();
		} catch (e: unknown) {
			backfillError = message(e, 'Failed to queue the samples');
		} finally {
			queueing = false;
		}
	}

	function when(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
	}

	function subjectHref(kind: string, subject: string | null): string | null {
		return kind === 'swatch_find' && subject ? `/samples/${subject}` : null;
	}
</script>

<svelte:head>
	<title>Background jobs - Hive</title>
</svelte:head>

<PageHeader
	title="Background jobs"
	description={`Work Hive does after something arrives, one job at a time beside the API: each kind of job, how many wait, run, finished and failed. The page refreshes every ${REFRESH_MS / 1000} seconds.`}
>
	{#snippet actions()}
		<Button href="/admin/swatch-models" variant="ghost" icon={ArrowRight}>Swatch models</Button>
	{/snippet}
</PageHeader>

{#if loading && !summary}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if !summary}
	<Alert tone="danger">{error ?? 'Failed to load the job queue'}</Alert>
{:else}
	{@const worker = summary.worker}
	<div class="flex flex-col gap-(--gap-panels)">
		{#if error}<Alert tone="danger">{error}</Alert>{/if}
		{#if !worker.enabled}
			<Alert tone="warning" title="The worker is off on this server">Jobs are queued but not run until it is turned on (JOB_WORKER_ENABLED).</Alert>
		{/if}

		<div class="grid gap-(--gap-panels) lg:grid-cols-[1fr_1fr]">
			<Panel title="Worker" flush>
				{#snippet actions()}
					<Badge tone={worker.running ? 'success' : 'neutral'} dot>{worker.running ? 'Running' : 'Off'}</Badge>
				{/snippet}
				<div class="px-(--pad-panel) pb-2">
					<KeyValue
						items={[
							{ label: 'Threads', value: worker.threads },
							{ label: 'Run since it started', value: `${worker.processed} (${worker.failed} failed for good)` },
							{ label: 'Last job', value: when(worker.last_job_at) },
							{ label: 'Running now', value: worker.current ? `${worker.current.kind} ${worker.current.subject ?? ''}` : '-', mono: !!worker.current },
							...(worker.last_error ? [{ label: 'Last error', value: worker.last_error }] : [])
						]}
					/>
				</div>
			</Panel>

			<Panel
				title="Find swatches in existing samples"
				description="Queues a machine's classification-camera samples for the active swatch model, newest first, behind new ones."
			>
				<div class="flex flex-col gap-3">
					<Field label="Machine" for="backfill-machine">
						<Select id="backfill-machine" bind:value={machineId} options={machineOptions} placeholder="Choose a machine" />
					</Field>
					<Field label="Captured in" for="backfill-range">
						<Select id="backfill-range" bind:value={range} options={RANGES} />
					</Field>
					<Checkbox bind:checked={rerun}>Read again the samples the active model has read</Checkbox>
					<div>
						<Button variant="primary" loading={queueing} disabled={!machineId} onclick={queueBackfill}>Queue samples</Button>
					</div>
					{#if backfillError}<Alert tone="danger">{backfillError}</Alert>{/if}
					{#if backfillResult}
						<Alert tone="success">
							Queued {backfillResult.queued} of {backfillResult.matched} samples for {backfillResult.model}{backfillResult.already_queued
								? `; ${backfillResult.already_queued} were queued already`
								: ''}{backfillResult.truncated ? '. That is as many as one go takes: queue again for the rest.' : '.'}
						</Alert>
					{/if}
				</div>
			</Panel>
		</div>

		<Panel title="By kind" flush>
			{#if summary.kinds.length === 0}
				<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">No jobs yet.</p>
			{:else}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th>Kind</th><th class="num">Waiting</th><th class="num">Running</th><th class="num">Done</th><th class="num">Failed</th><th
									>Oldest waiting</th
								>
							</tr>
						</thead>
						<tbody>
							{#each summary.kinds as k (k.kind)}
								<tr>
									<td class="whitespace-nowrap">
										<span class="font-mono">{k.kind}</span>
										{#if !k.registered}<Badge tone="warning">No handler here</Badge>{/if}
									</td>
									<td class="num">{k.queued}</td>
									<td class="num">{k.running}</td>
									<td class="num text-ink-muted">{k.done}</td>
									<td class="num {k.failed ? 'text-danger-ink' : 'text-ink-muted'}">{k.failed}</td>
									<td class="whitespace-nowrap text-ink-muted">{when(k.oldest_queued_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Panel>

		<Panel title="Latest failures" description="Failed after their last attempt. Retrying starts their attempts over." flush>
			{#if summary.recent_failures.length === 0}
				<EmptyState title="No failures">Every job that ran either finished or will be tried again.</EmptyState>
			{:else}
				<ul class="divide-y divide-line border-t border-line">
					{#each summary.recent_failures as job (job.id)}
						{@const href = subjectHref(job.kind, job.subject)}
						<li class="flex flex-wrap items-start gap-3 px-(--pad-panel) py-3">
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-center gap-2 text-sm">
									<span class="font-mono text-ink">{job.kind}</span>
									{#if href}
										<a {href} class="font-mono text-ink-muted hover:underline">{job.subject}</a>
									{:else if job.subject}
										<span class="font-mono text-ink-muted">{job.subject}</span>
									{/if}
									<span class="num text-ink-muted">{job.attempts} of {job.max_attempts} attempts, {when(job.finished_at)}</span>
								</div>
								<p class="mt-1 text-sm break-words text-ink">{job.error ?? 'No error recorded'}</p>
							</div>
							<Button size="sm" icon={RotateCcw} loading={retrying === job.id} onclick={() => retry(job.id)}>Retry</Button>
						</li>
					{/each}
				</ul>
			{/if}
		</Panel>
	</div>
{/if}
