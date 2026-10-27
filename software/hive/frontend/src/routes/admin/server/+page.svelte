<script lang="ts">
	import { goto } from '$app/navigation';
	import { untrack } from 'svelte';
	import { auth } from '$lib/auth.svelte';
	import {
		api,
		type RouteTiming,
		type ServerDisk,
		type ServerHealth,
		type ServerJobs,
		type ServerPartError,
		type ServerPostgres,
		type ServerProcess,
		type ServerRequests,
		type ServerStatus,
		type ServerWorker
	} from '$lib/api';
	import { relativeTime } from '$lib/time';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';

	type Order = 'total' | 'p90' | 'count';
	type Tone = 'success' | 'warning' | 'danger' | undefined;

	const ORDERS: { value: Order; label: string }[] = [
		{ value: 'total', label: 'Total time' },
		{ value: 'p90', label: 'p90' },
		{ value: 'count', label: 'Count' }
	];
	const ORDER_KEY: Record<Order, (r: RouteTiming) => number> = {
		total: (r) => r.total_s,
		p90: (r) => r.p90_ms,
		count: (r) => r.count
	};

	let status = $state<ServerStatus | null>(null);
	let loading = $state(true);
	let refreshing = $state(false);
	let error = $state<string | null>(null);
	let order = $state<Order>('total');
	let walking = $state(false);
	let walkStarted = $state(false);

	$effect(() => {
		if (!auth.initialized) return;
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		// Once, when the page opens: load reads the state it sets, and tracked
		// here that would load again every time it finished.
		untrack(() => void load());
	});

	function message(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : fallback;
	}

	async function load() {
		refreshing = status !== null;
		try {
			status = await api.getServerStatus();
			error = null;
		} catch (e: unknown) {
			error = message(e, 'Failed to load the server');
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	async function walkStorage() {
		walking = true;
		try {
			await api.getServerHealth({ refreshStorage: true });
			walkStarted = true;
		} catch (e: unknown) {
			error = message(e, 'Failed to start the storage walk');
		} finally {
			walking = false;
		}
	}

	// A part the server could not read comes back as { error }.
	function failed(value: unknown): string | null {
		return value && typeof value === 'object' && !Array.isArray(value) && 'error' in value
			? String((value as ServerPartError).error)
			: null;
	}

	function part<T>(value: unknown): T | null {
		return value == null || failed(value) ? null : (value as T);
	}

	const requests = $derived(part<ServerRequests>(status?.requests));
	const proc = $derived(part<ServerProcess>(status?.process));
	const workers = $derived(part<ServerWorker[]>(status?.workers));
	const jobs = $derived(part<ServerJobs>(status?.jobs));
	const database = $derived(part<ServerPostgres | { dialect: string }>(status?.database));
	const postgres = $derived(database && 'connections' in database ? (database as ServerPostgres) : null);
	const disks = $derived(part<ServerDisk[]>(status?.disk));
	const memory = $derived(part<ServerHealth['memory']>(status?.memory));
	const storage = $derived(part<ServerHealth['storage']>(status?.storage));

	const routes = $derived([...(requests?.routes ?? [])].sort((a, b) => ORDER_KEY[order](b) - ORDER_KEY[order](a)));

	function num(n: number | null | undefined): string {
		return n != null ? Math.round(n).toLocaleString('en-US') : '-';
	}

	function bytes(n: number | null | undefined): string {
		if (n == null) return '-';
		if (n === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
		return `${(n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
	}

	function duration(ms: number | null | undefined): string {
		if (ms == null) return '-';
		if (ms < 1) return 'under 1 ms';
		if (ms < 1000) return `${Math.round(ms)} ms`;
		if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
		if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)} min`;
		return `${(ms / 3_600_000).toFixed(1)} h`;
	}

	// A span of time in words: "45 seconds", "12 minutes", "3 hours", "2 days".
	function span(s: number | null | undefined): string {
		if (s == null) return '-';
		const words = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'}`;
		if (s < 90) return words(Math.round(s), 'second');
		if (s < 5400) return words(Math.round(s / 60), 'minute');
		if (s < 172_800) return words(Math.round(s / 3600), 'hour');
		return words(Math.round(s / 86_400), 'day');
	}

	function percent(share: number | null | undefined, digits = 0): string {
		return share != null ? `${(share * 100).toFixed(digits)}%` : '-';
	}

	function when(iso: string | null | undefined): string {
		return iso ? relativeTime(iso) : '-';
	}

	// How slow a latency reads: past a second needs a look, past the slow line is slow.
	function latencyTone(ms: number): string {
		const slow = (requests?.slow_s ?? 2) * 1000;
		if (ms >= slow) return 'text-danger-ink';
		if (ms >= 1000) return 'text-warning-ink';
		return '';
	}

	function databaseShare(r: { total_s: number; db_s: number }): string {
		return r.total_s > 0 ? percent(Math.min(1, r.db_s / r.total_s)) : '-';
	}

	const freeShare = $derived(
		disks && disks.length > 0 ? disks[0].free_bytes / Math.max(1, disks[0].total_bytes) : null
	);
	const connectionsByState = $derived(
		postgres ? Object.fromEntries(postgres.connections.by_state.map((s) => [s.state, s.count])) : {}
	);

	const headline = $derived.by(() => {
		const totals = requests?.totals;
		const cpu = requests?.cpu;
		const stats: { label: string; value: string; unit?: string; hint?: string; tone?: Tone }[] = [
			{
				label: 'Requests',
				value: num(totals?.count),
				hint: totals ? `${totals.per_minute >= 10 ? num(totals.per_minute) : totals.per_minute.toFixed(1)} a minute` : undefined
			},
			{
				label: 'p90',
				value: duration(totals?.p90_ms),
				hint: totals ? `p50 ${duration(totals.p50_ms)}, p99 ${duration(totals.p99_ms)}` : undefined
			},
			{
				label: 'Server errors',
				value: num(totals?.errors),
				hint: '5xx answers',
				tone: totals && totals.errors > 0 ? 'danger' : undefined
			},
			{
				label: 'Slow requests',
				value: num(totals?.slow),
				hint: requests ? `${requests.slow_s} s or longer` : undefined,
				tone: totals && totals.slow > 0 ? 'warning' : undefined
			},
			{
				label: 'CPU, this process',
				value: cpu?.recent_cores != null ? percent(cpu.recent_cores) : '-',
				hint: cpu?.recent_s != null ? `of a core, last ${duration(cpu.recent_s * 1000)}` : undefined,
				tone: cpu?.recent_cores != null && cpu.recent_cores >= 0.8 ? 'warning' : undefined
			},
			{
				label: 'Connections',
				value: postgres ? num(postgres.connections.all_databases) : '-',
				unit: postgres ? `of ${postgres.connections.max}` : undefined,
				hint: postgres
					? `${connectionsByState['active'] ?? 0} active, ${connectionsByState['idle in transaction'] ?? 0} idle in a transaction`
					: undefined
			},
			{
				label: 'Cache hit',
				value: postgres ? percent(postgres.cache_hit_ratio, 1) : '-',
				hint: postgres?.stats_since ? `since ${when(postgres.stats_since)}` : undefined,
				tone: postgres?.cache_hit_ratio != null && postgres.cache_hit_ratio < 0.95 ? 'warning' : undefined
			},
			{
				label: 'Disk free',
				value: disks && disks.length > 0 ? bytes(disks[0].free_bytes) : '-',
				hint: freeShare != null ? `${percent(1 - freeShare)} used` : undefined,
				tone: freeShare == null ? undefined : freeShare < 0.05 ? 'danger' : freeShare < 0.15 ? 'warning' : undefined
			}
		];
		return stats;
	});

	const processItems = $derived.by(() => {
		if (!proc) return [];
		const cpu = requests?.cpu;
		const flight = requests?.in_flight;
		const oldest = flight?.oldest[0];
		return [
			{ label: 'Process', value: `${proc.pid}${proc.role ? `, role ${proc.role}` : ''}`, mono: true },
			{ label: 'Up for', value: span(proc.uptime_s) },
			{
				label: 'CPU',
				value:
					cpu?.recent_cores != null
						? `${percent(cpu.recent_cores)} of a core, last ${span(cpu.recent_s)}; ${percent(cpu.window_cores)} over ${span(requests?.window_s)}`
						: '-'
			},
			{
				label: 'Request threads',
				value: proc.threadpool
					? `${proc.threadpool.busy} of ${proc.threadpool.size} busy (one is this page), ${proc.threadpool.waiting} waiting`
					: '-'
			},
			{
				label: 'Database connections',
				value:
					proc.db_pool.checked_out != null
						? `${proc.db_pool.checked_out} in use${proc.db_pool.limit != null ? ` of ${proc.db_pool.limit}` : ''} (one is this page)`
						: '-'
			},
			{
				// The count includes the request for this page.
				label: 'Other requests running',
				value: flight
					? `${Math.max(0, flight.count - 1)}${oldest && oldest.running_s >= 1 ? `, the oldest ${oldest.method} ${oldest.path} for ${span(oldest.running_s)}` : ''}`
					: '-'
			},
			{ label: 'Threads', value: proc.threads },
			{ label: 'Load', value: proc.load ? `${proc.load.join(', ')} on ${proc.cpus ?? '?'} CPUs` : '-' }
		];
	});

	const memoryUsed = $derived(
		memory && memory.total_bytes && memory.used_bytes != null ? memory.used_bytes / memory.total_bytes : null
	);

	const storageParts = $derived(
		storage
			? [
					{ key: 'sample_images', label: 'Sample images', color: 'var(--primary)', ...storage.sample_images },
					{ key: 'piece_images', label: 'Piece images', color: 'var(--success)', ...storage.piece_images },
					{ key: 'model_files', label: 'Model files', color: 'var(--info)', ...storage.model_files }
				]
			: []
	);
</script>

<svelte:head>
	<title>Server - Hive</title>
</svelte:head>

<PageHeader
	title="Server"
	description="How Hive's server is doing: each kind of request over the last hour, this process, the job queue, the background workers, the database and the disk. Read when the page opens and when you refresh it."
>
	{#snippet actions()}
		<Button href="/admin/jobs" variant="ghost" icon={ArrowRight}>Background jobs</Button>
		<Button icon={RefreshCw} loading={refreshing} onclick={load}>Refresh</Button>
	{/snippet}
</PageHeader>

{#if loading && !status}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if !status}
	<Alert tone="danger">{error ?? 'Failed to load the server'}</Alert>
{:else}
	<div class="flex flex-col gap-(--gap-panels)">
		{#if error}<Alert tone="danger">{error}</Alert>{/if}

		<section aria-label="At a glance" class="overflow-hidden rounded-panel bg-surface">
			<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4">
				{#each headline as stat (stat.label)}
					<div class="border-t border-l border-line">
						<Stat label={stat.label} value={stat.value} unit={stat.unit} hint={stat.hint} tone={stat.tone} />
					</div>
				{/each}
			</div>
		</section>

		<Panel
			title="Requests"
			description={requests
				? `Each route over the last ${span(requests.window_s)}, kept in this process's memory. In the database is the share of the time its queries took.`
				: undefined}
			flush
		>
			{#snippet actions()}
				<SegmentedControl label="Order by" size="sm" bind:value={order} options={ORDERS} />
			{/snippet}
			{#if failed(status.requests)}
				<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{failed(status.requests)}</Alert></div>
			{:else if routes.length === 0}
				<div class="px-(--pad-panel) pb-(--pad-panel)">
					<EmptyState title="No requests yet">This process has answered none since it started.</EmptyState>
				</div>
			{:else}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th>Route</th><th class="num">Count</th><th class="num">p50</th><th class="num">p90</th><th class="num">p99</th><th
									class="num">Max</th
								><th class="num">5xx</th><th class="num">Total time</th><th class="num">In the database</th>
							</tr>
						</thead>
						<tbody>
							{#each routes as r (`${r.method} ${r.route}`)}
								<tr>
									<td class="whitespace-nowrap"><span class="text-ink-muted">{r.method}</span> <span class="font-mono">{r.route}</span></td>
									<td class="num">{num(r.count)}</td>
									<td class="num whitespace-nowrap {latencyTone(r.p50_ms)}">{duration(r.p50_ms)}</td>
									<td class="num whitespace-nowrap {latencyTone(r.p90_ms)}">{duration(r.p90_ms)}</td>
									<td class="num whitespace-nowrap {latencyTone(r.p99_ms)}">{duration(r.p99_ms)}</td>
									<td class="num whitespace-nowrap {latencyTone(r.max_ms)}">{duration(r.max_ms)}</td>
									<td class="num {r.errors ? 'text-danger-ink' : 'text-ink-muted'}">{num(r.errors)}</td>
									<td class="num whitespace-nowrap">{duration(r.total_s * 1000)}</td>
									<td class="num text-ink-muted">{databaseShare(r)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Panel>

		<div class="grid gap-(--gap-panels) lg:grid-cols-2">
			<Panel title="This process" description="The process that answered this page.">
				{#if failed(status.process)}
					<Alert tone="danger">{failed(status.process)}</Alert>
				{:else}
					<KeyValue items={processItems} />
				{/if}
			</Panel>

			<Panel title="Disk and memory" description="As this process sees them; in a container, the disk is the host's.">
				<div class="flex flex-col gap-4">
					{#if failed(status.disk)}
						<Alert tone="danger">{failed(status.disk)}</Alert>
					{:else}
						{#each disks ?? [] as disk (disk.path)}
							{@const used = 1 - disk.free_bytes / Math.max(1, disk.total_bytes)}
							<div>
								<div class="mb-2 flex items-baseline justify-between gap-4 text-sm">
									<span class="text-ink">{disk.label}</span>
									<span class="num text-ink-muted">{bytes(disk.free_bytes)} free of {bytes(disk.total_bytes)}</span>
								</div>
								<ProgressBar
									label={`${disk.label} used`}
									value={used * 100}
									tone={used >= 0.95 ? 'danger' : used >= 0.85 ? 'warning' : 'success'}
								/>
							</div>
						{/each}
					{/if}
					{#if failed(status.memory)}
						<Alert tone="danger">{failed(status.memory)}</Alert>
					{:else if memory && memory.total_bytes != null && memoryUsed != null}
						<div>
							<div class="mb-2 flex items-baseline justify-between gap-4 text-sm">
								<span class="text-ink">Memory</span>
								<span class="num text-ink-muted">{bytes(memory.used_bytes)} used of {bytes(memory.total_bytes)}</span>
							</div>
							<ProgressBar label="Memory used" value={memoryUsed * 100} tone={memoryUsed >= 0.9 ? 'danger' : 'success'} />
						</div>
						<KeyValue
							items={[
								{ label: 'Available', value: bytes(memory.available_bytes) },
								{ label: 'This process', value: bytes(memory.process_rss_bytes) }
							]}
						/>
					{:else}
						<p class="text-sm text-ink-muted">Memory is not available here: the server is not Linux, or it cannot read /proc.</p>
					{/if}
				</div>
			</Panel>
		</div>

		<Panel
			title="Job queue"
			description={jobs
				? `As the database has it, whichever process runs the jobs.${jobs.last_done_at ? ` The last job finished ${when(jobs.last_done_at)}.` : ''}`
				: undefined}
			flush
		>
			{#if failed(status.jobs)}
				<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{failed(status.jobs)}</Alert></div>
			{:else if jobs && jobs.kinds.length === 0}
				<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">No jobs yet.</p>
			{:else if jobs}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th>Kind</th><th class="num">Waiting</th><th class="num">Running</th><th class="num">Done, last hour</th><th class="num"
									>Failed, last hour</th
								><th class="num">Failed, kept</th><th>Oldest waiting</th>
							</tr>
						</thead>
						<tbody>
							{#each jobs.kinds as k (k.kind)}
								<tr>
									<td class="font-mono whitespace-nowrap">{k.kind}</td>
									<td class="num">{num(k.queued)}</td>
									<td class="num">{num(k.running)}</td>
									<td class="num">{num(k.done_last_hour)}</td>
									<td class="num {k.failed_last_hour ? 'text-danger-ink' : 'text-ink-muted'}">{num(k.failed_last_hour)}</td>
									<td class="num text-ink-muted">{num(k.failed)}</td>
									<td class="whitespace-nowrap text-ink-muted">{when(k.oldest_queued_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if jobs.running.length > 0}
					<div class="border-t border-line px-(--pad-panel) py-3">
						<h3 class="text-sm font-medium text-ink">Running now</h3>
						<ul class="mt-1 flex flex-col gap-1 text-sm">
							{#each jobs.running as job, i (i)}
								<li class="flex flex-wrap gap-x-3">
									<span class="font-mono text-ink">{job.kind}</span>
									{#if job.subject}<span class="font-mono text-ink-muted">{job.subject}</span>{/if}
									<span class="text-ink-muted">for {span(job.running_s)}{job.worker ? `, in ${job.worker}` : ''}</span>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
				{#if jobs.recent_failures.length > 0}
					<div class="border-t border-line px-(--pad-panel) py-3">
						<h3 class="text-sm font-medium text-ink">Latest failures</h3>
						<ul class="mt-1 flex flex-col gap-2 text-sm">
							{#each jobs.recent_failures as job (job.id)}
								<li>
									<span class="font-mono text-ink">{job.kind}</span>
									{#if job.subject}<span class="font-mono text-ink-muted"> {job.subject}</span>{/if}
									<span class="text-ink-muted">, {when(job.finished_at)}</span>
									<p class="break-words text-ink">{job.error ?? 'No error recorded'}</p>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
			{/if}
		</Panel>

		<Panel
			title="Background workers"
			description={proc?.role === 'web'
				? 'They run in the worker process; this is what it last reported: when each last ran and how long it took.'
				: 'When each last ran and how long it took.'}
			flush
		>
			{#if failed(status.workers)}
				<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{failed(status.workers)}</Alert></div>
			{:else}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr><th>Worker</th><th>State</th><th>Last run</th><th class="num">Took</th><th class="num">Every</th><th class="num">Runs</th></tr>
						</thead>
						<tbody>
							{#each workers ?? [] as w (w.name)}
								<tr>
									<td class="whitespace-nowrap">
										{w.name}
										{#if w.last_error}<p class="max-w-md text-sm break-words whitespace-normal text-danger-ink">{w.last_error}</p>{/if}
									</td>
									<td><Badge tone={w.running ? 'success' : 'neutral'} dot>{w.running ? 'Running' : 'Not running'}</Badge></td>
									<td class="whitespace-nowrap text-ink-muted">{when(w.last_run_at)}</td>
									<td class="num whitespace-nowrap">{w.last_run_s != null ? duration(w.last_run_s * 1000) : '-'}</td>
									<td class="num whitespace-nowrap text-ink-muted">{w.every_s != null ? span(w.every_s) : '-'}</td>
									<td class="num text-ink-muted">{num(w.runs)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Panel>

		{#if failed(status.database)}
			<Panel title="Database"><Alert tone="danger">{failed(status.database)}</Alert></Panel>
		{:else if !postgres}
			<Panel title="Database">
				<p class="text-sm text-ink-muted">Its health needs PostgreSQL; this server runs {database?.dialect ?? 'something else'}.</p>
			</Panel>
		{:else}
			<Panel
				title="Database"
				description={`PostgreSQL ${postgres.version}, up since ${when(postgres.started_at)}. Counts are since ${when(postgres.stats_since)}.`}
				flush
			>
				{#snippet actions()}<span class="num text-2xl font-medium text-ink">{bytes(postgres!.size_bytes)}</span>{/snippet}
				<div class="-ml-px grid grid-cols-2 sm:grid-cols-4">
					<div class="border-t border-l border-line">
						<Stat
							label="Connections"
							value={num(postgres.connections.all_databases)}
							unit={`of ${postgres.connections.max}`}
							hint={postgres.connections.by_state.map((s) => `${s.count} ${s.state}`).join(', ')}
						/>
					</div>
					<div class="border-t border-l border-line">
						<Stat label="Cache hit" value={percent(postgres.cache_hit_ratio, 2)} hint={`shared buffers ${postgres.shared_buffers}`} />
					</div>
					<div class="border-t border-l border-line">
						<Stat label="Temporary files" value={num(postgres.temp_files)} hint={bytes(postgres.temp_bytes)} />
					</div>
					<div class="border-t border-l border-line">
						<Stat
							label="Rollbacks"
							value={num(postgres.rollbacks)}
							hint={`of ${num(postgres.commits + postgres.rollbacks)} transactions; ${num(postgres.deadlocks)} deadlocks`}
							tone={postgres.deadlocks > 0 ? 'warning' : undefined}
						/>
					</div>
				</div>
				<div class="border-t border-line px-(--pad-panel) py-3">
					<h3 class="text-sm font-medium text-ink">Longest running</h3>
					{#if postgres.longest.length === 0}
						<p class="mt-1 text-sm text-ink-muted">Nothing else is running: every other connection is idle.</p>
					{:else}
						<ul class="mt-1 flex flex-col gap-3 text-sm">
							{#each postgres.longest as q (q.pid)}
								<li class="min-w-0">
									<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
										<Badge tone={q.state === 'active' ? 'info' : 'warning'}>{q.state}</Badge>
										<span class="num text-ink">
											{q.transaction_s != null ? `transaction ${duration(q.transaction_s * 1000)}` : ''}{q.query_s != null
												? `, query ${duration(q.query_s * 1000)}`
												: ''}
										</span>
										{#if q.waiting_on}<span class="text-ink-muted">waiting on {q.waiting_on}</span>{/if}
										<span class="font-mono text-ink-muted">pid {q.pid}{q.client ? `, ${q.client}` : ''}</span>
									</div>
									<p class="mt-1 line-clamp-3 font-mono break-all text-ink-muted">{q.query}</p>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			</Panel>

			<Panel title="Tables" description="The biggest, with how they are read: a big table read by sequential scans wants an index." flush>
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th>Table</th><th class="num">Size</th><th class="num">Of it indexes</th><th class="num">Rows, about</th><th class="num"
									>Dead rows</th
								><th class="num">Sequential scans</th><th class="num">Rows read by them</th><th class="num">Index scans</th><th
									>Last vacuum</th
								>
							</tr>
						</thead>
						<tbody>
							{#each postgres.tables as t (t.name)}
								<tr>
									<td class="font-mono whitespace-nowrap">{t.name}</td>
									<td class="num whitespace-nowrap">{bytes(t.total_bytes)}</td>
									<td class="num whitespace-nowrap text-ink-muted">{bytes(t.index_bytes)}</td>
									<td class="num">{num(t.rows)}</td>
									<td class="num text-ink-muted">{num(t.dead_rows)}</td>
									<td class="num">{num(t.seq_scans)}</td>
									<td class="num text-ink-muted">{num(t.seq_rows_read)}</td>
									<td class="num">{num(t.index_scans)}</td>
									<td class="whitespace-nowrap text-ink-muted">{when(t.last_vacuum)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</Panel>

			<Panel title="Indexes" description="The biggest. One never scanned costs space and every write, and helps no read." flush>
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead><tr><th>Index</th><th>Table</th><th class="num">Size</th><th class="num">Scans</th></tr></thead>
						<tbody>
							{#each postgres.indexes as ix (ix.name)}
								<tr>
									<td class="font-mono whitespace-nowrap">{ix.name}</td>
									<td class="font-mono whitespace-nowrap text-ink-muted">{ix.table}</td>
									<td class="num whitespace-nowrap">{bytes(ix.bytes)}</td>
									<td class="num {ix.scans === 0 ? 'text-warning-ink' : ''}">{num(ix.scans)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</Panel>
		{/if}

		{#if walkStarted}
			<Alert tone="info" title="Storage walk started">
				A walk of the object store is running in the background. Refresh in a few minutes for the new figures.
			</Alert>
		{/if}
		{#if failed(status.storage)}
			<Panel title="Stored files"><Alert tone="danger">{failed(status.storage)}</Alert></Panel>
		{:else if storage}
			<Panel
				title="Stored files"
				description={`${num(storage.total_files)} files, counted ${storage.computed_at != null ? when(new Date(storage.computed_at * 1000).toISOString()) : 'not yet'}${storage.pending ? '; the first walk is still running' : ''}.`}
				flush
			>
				{#snippet actions()}
					<!-- The walk is a background worker: a web process asks the worker process to run it. -->
					<Button size="sm" variant="ghost" icon={RefreshCw} loading={walking} onclick={walkStorage}>Count again</Button>
					<span class="num text-2xl font-medium text-ink">{bytes(storage!.total_bytes)}</span>
				{/snippet}
				{#if storage.total_bytes > 0}
					<div class="px-(--pad-panel) pb-4">
						<div class="flex h-3 w-full overflow-hidden rounded-badge bg-track">
							{#each storageParts as p (p.key)}
								{#if p.bytes > 0}
									<div style="width: {(p.bytes / storage.total_bytes) * 100}%; background: {p.color}"></div>
								{/if}
							{/each}
						</div>
					</div>
				{/if}
				<div class="-ml-px grid grid-cols-1 sm:grid-cols-3">
					{#each storageParts as p (p.key)}
						<div class="border-t border-l border-line p-4">
							<div class="flex items-center gap-2 text-sm">
								<span class="size-2.5 rounded-full" style="background: {p.color}"></span>
								<span class="text-ink">{p.label}</span>
							</div>
							<p class="num mt-1 text-xl font-medium text-ink">{bytes(p.bytes)}</p>
							<p class="num text-sm text-ink-muted">{num(p.files)} files</p>
						</div>
					{/each}
				</div>
			</Panel>
		{/if}
	</div>
{/if}
