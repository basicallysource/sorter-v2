<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import {
		AlertTriangle,
		ArrowLeft,
		CheckCircle2,
		Clock3,
		ImageOff,
		RefreshCw,
		Sparkles,
		Trash2,
		UploadCloud
	} from 'lucide-svelte';

	const machine = getMachineContext();

	type QueueJob = {
		status?: string;
		operation?: string;
		target_id?: string | null;
		target_name?: string | null;
		session_id: string | null;
		session_name: string | null;
		sample_id: string | null;
		source_role: string | null;
		capture_reason: string | null;
		captured_at: number | null;
		queued_at?: number | null;
		age_s?: number | null;
		detection_algorithm: string | null;
		detection_bbox_count: number | null;
		detection_score?: number | null;
		teacher_state: string;
		teacher_label: string;
		teacher_reason: string;
		hive_uploads?: Record<string, { status?: string; uploaded_at?: number } | null> | null;
		message?: string | null;
		finished_at?: number | null;
	};

	type QueueTarget = {
		id: string;
		name: string;
		url: string;
		machine_id: string | null;
		enabled: boolean;
		server_reachable: boolean;
		queue_size: number;
		uploaded: number;
		failed: number;
		requeued: number;
		last_error: string | null;
		queued_jobs: QueueJob[];
		active_jobs: QueueJob[];
		recent_jobs: QueueJob[];
	};

	type TeacherSummary = {
		counts: {
			teacher_ready: number;
			needs_gemini: number;
			no_teacher_detection: number;
			bad_teacher_sample: number;
			not_teacher_sample: number;
			invalid: number;
		};
		recent_needs_gemini: QueueJob[];
		recent_ready: QueueJob[];
	};

	type QueuePayload = {
		ok: boolean;
		generated_at: number;
		targets: QueueTarget[];
		teacher: TeacherSummary;
		totals: {
			queued: number;
			uploading: number;
			recent_uploaded: number;
			recent_failed: number;
			recent_retrying: number;
			needs_gemini: number;
			no_teacher_detection: number;
			bad_teacher_sample: number;
			teacher_ready: number;
			other_samples: number;
		};
	};

	type QueueListItem = QueueJob & {
		list_id: string;
		list_status: string;
		list_label: string;
		list_detail: string;
		list_rank: number;
		sort_ts: number;
		image_url: string | null;
		problem: boolean;
	};

	type FilterId = 'all' | 'problem' | 'queue' | 'done';

	let payload = $state<QueuePayload | null>(null);
	let loading = $state(true);
	let refreshing = $state(false);
	let errorMsg = $state<string | null>(null);
	let actionMsg = $state<string | null>(null);
	let actionBusy = $state<string | null>(null);
	let filter = $state<FilterId>('all');

	const targetId = $derived(page.url.searchParams.get('target_id'));
	const targets = $derived(payload?.targets ?? []);
	const selectedTarget = $derived(targetId ? targets.find((target) => target.id === targetId) : null);
	const totals = $derived(
		payload?.totals ?? {
			queued: 0,
			uploading: 0,
			recent_uploaded: 0,
			recent_failed: 0,
			recent_retrying: 0,
			needs_gemini: 0,
			no_teacher_detection: 0,
			bad_teacher_sample: 0,
			teacher_ready: 0,
			other_samples: 0
		}
	);
	const blockedTotal = $derived(totals.needs_gemini + totals.no_teacher_detection + totals.bad_teacher_sample);
	const failedTotal = $derived(totals.recent_failed + totals.recent_retrying);
	const allItems = $derived.by(() => buildListItems(payload));
	const filteredItems = $derived.by(() => {
		if (filter === 'problem') return allItems.filter((item) => item.problem);
		if (filter === 'queue') {
			return allItems.filter((item) => item.list_status === 'queued' || item.list_status === 'uploading');
		}
		if (filter === 'done') return allItems.filter((item) => item.list_status === 'uploaded');
		return allItems;
	});

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	async function loadQueue(options: { silent?: boolean } = {}) {
		if (options.silent) {
			refreshing = true;
		} else {
			loading = true;
		}
		errorMsg = null;
		try {
			const params = new URLSearchParams({ limit: '160' });
			if (targetId) params.set('target_id', targetId);
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/queue?${params}`);
			if (!res.ok) throw new Error(await res.text());
			payload = (await res.json()) as QueuePayload;
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to load Hive queue.';
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	async function purgeQueue() {
		const scope = selectedTarget ? `for "${selectedTarget.name}"` : 'for all Hive targets';
		if (!confirm(`Purge the waiting upload queue ${scope}? In-flight uploads may still finish.`)) return;
		actionBusy = 'queue';
		errorMsg = null;
		actionMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/purge`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_ids: targetId ? [targetId] : null
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) throw new Error(data.error ?? 'Queue purge failed.');
			actionMsg = `Purged ${data.purged ?? 0} queued upload job${data.purged === 1 ? '' : 's'}.`;
			await loadQueue({ silent: true });
		} catch (e: any) {
			errorMsg = e?.message ?? 'Queue purge failed.';
		} finally {
			actionBusy = null;
		}
	}

	async function purgeBlockedSamples() {
		if (
			!confirm(
				`Delete ${blockedTotal} blocked local sample${blockedTotal === 1 ? '' : 's'} from this sorter? ` +
					'This removes samples that still need Gemini labels, have no usable Gemini box, or failed crop quality.'
			)
		) {
			return;
		}
		actionBusy = 'blocked-samples';
		errorMsg = null;
		actionMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/queue/purge-samples`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					states: ['needs_gemini', 'no_teacher_detection', 'bad_teacher_sample']
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			if (!data.ok) throw new Error(data.error ?? 'Sample purge failed.');
			actionMsg =
				`Purged ${data.purged_samples ?? 0} blocked sample` +
				`${data.purged_samples === 1 ? '' : 's'} from local storage.`;
			await loadQueue({ silent: true });
		} catch (e: any) {
			errorMsg = e?.message ?? 'Sample purge failed.';
		} finally {
			actionBusy = null;
		}
	}

	async function purgeAllSamples() {
		if (!payload) return;
		const total =
			payload.teacher.counts.teacher_ready +
			payload.teacher.counts.needs_gemini +
			payload.teacher.counts.no_teacher_detection +
			payload.teacher.counts.bad_teacher_sample +
			payload.teacher.counts.not_teacher_sample;
		if (
			!confirm(
				`Delete all ${total} local sample${total === 1 ? '' : 's'} from this sorter? ` +
					'This also purges the waiting Hive upload queue and cannot be undone.'
			)
		) {
			return;
		}
		actionBusy = 'all-samples';
		errorMsg = null;
		actionMsg = null;
		try {
			const queueRes = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/purge`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target_ids: null })
			});
			if (!queueRes.ok) throw new Error(await queueRes.text());
			const queueData = await queueRes.json();
			if (!queueData.ok) throw new Error(queueData.error ?? 'Queue purge failed.');
			const res = await fetch(`${currentBackendBaseUrl()}/api/samples/storage`, {
				method: 'DELETE'
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			actionMsg = data.message ?? 'Purged local samples.';
			await loadQueue({ silent: true });
		} catch (e: any) {
			errorMsg = e?.message ?? 'Sample purge failed.';
		} finally {
			actionBusy = null;
		}
	}

	function buildListItems(data: QueuePayload | null): QueueListItem[] {
		if (!data) return [];
		const uploadSampleKeys = new Set<string>();
		const items: QueueListItem[] = [];

		for (const target of data.targets) {
			for (const job of target.active_jobs) {
				const item = decorateJob(job, 'uploading');
				uploadSampleKeys.add(sampleKey(job));
				items.push(item);
			}
			for (const job of target.queued_jobs) {
				const item = decorateJob(job, 'queued');
				uploadSampleKeys.add(sampleKey(job));
				items.push(item);
			}
			for (const job of target.recent_jobs) {
				const item = decorateJob(job, job.status ?? 'finished');
				uploadSampleKeys.add(sampleKey(job));
				items.push(item);
			}
		}

		for (const job of data.teacher.recent_needs_gemini) {
			items.push(decorateJob(job, job.teacher_state));
		}
		for (const job of data.teacher.recent_ready) {
			if (!uploadSampleKeys.has(sampleKey(job))) {
				items.push(decorateJob(job, localReadyStatus(job)));
			}
		}

		return items.sort((a, b) => a.list_rank - b.list_rank || b.sort_ts - a.sort_ts).slice(0, 160);
	}

	function localReadyStatus(job: QueueJob): string {
		const uploads = job.hive_uploads;
		if (!uploads || typeof uploads !== 'object') return 'teacher_ready';
		if (targetId) {
			return uploads[targetId]?.status === 'uploaded' ? 'uploaded' : 'teacher_ready';
		}
		return Object.values(uploads).some((entry) => entry?.status === 'uploaded')
			? 'uploaded'
			: 'teacher_ready';
	}

	function decorateJob(job: QueueJob, status: string): QueueListItem {
		const sortTs = job.finished_at ?? job.queued_at ?? job.captured_at ?? 0;
		return {
			...job,
			list_id: `${status}-${job.target_id ?? 'local'}-${job.session_id ?? 'no-session'}-${job.sample_id ?? 'no-sample'}-${sortTs}`,
			list_status: status,
			list_label: statusLabel(status),
			list_detail: statusDetail(job, status),
			list_rank: statusRank(status),
			sort_ts: sortTs,
			image_url: sampleImageUrl(job),
			problem: isProblem(status)
		};
	}

	function sampleKey(job: QueueJob): string {
		return `${job.session_id ?? ''}/${job.sample_id ?? ''}`;
	}

	function sampleImageUrl(job: QueueJob): string | null {
		if (!job.session_id || !job.sample_id) return null;
		return `${currentBackendBaseUrl()}/api/samples/storage/${encodeURIComponent(job.session_id)}/${encodeURIComponent(job.sample_id)}/image`;
	}

	function statusLabel(status: string): string {
		if (status === 'uploading') return 'Uploading';
		if (status === 'queued') return 'Queued';
		if (status === 'uploaded') return 'Uploaded';
		if (status === 'retrying') return 'Retrying';
		if (status === 'failed') return 'Failed';
		if (status === 'skipped') return 'Skipped';
		if (status === 'needs_gemini') return 'Needs Gemini';
		if (status === 'no_teacher_detection') return 'No Box';
		if (status === 'bad_teacher_sample') return 'Bad Crop';
		if (status === 'teacher_ready') return 'Ready';
		return status;
	}

	function statusDetail(job: QueueJob, status: string): string {
		if (!isProblem(status)) return '';
		if (status === 'failed' || status === 'retrying') return job.message || job.teacher_reason || '';
		if (status === 'no_teacher_detection') return job.teacher_reason;
		if (status === 'bad_teacher_sample') return job.teacher_reason;
		return '';
	}

	function statusRank(status: string): number {
		if (status === 'uploading') return 0;
		if (status === 'queued') return 1;
		if (status === 'needs_gemini') return 2;
		if (status === 'no_teacher_detection' || status === 'bad_teacher_sample') return 3;
		if (status === 'retrying' || status === 'failed') return 4;
		if (status === 'teacher_ready') return 5;
		if (status === 'uploaded') return 6;
		return 7;
	}

	function isProblem(status: string): boolean {
		return (
			status === 'needs_gemini' ||
			status === 'no_teacher_detection' ||
			status === 'bad_teacher_sample' ||
			status === 'failed' ||
			status === 'retrying'
		);
	}

	function statusTone(status: string): string {
		if (status === 'uploaded' || status === 'teacher_ready') return 'border-success/30 bg-success/10 text-success';
		if (status === 'failed' || status === 'skipped' || status === 'no_teacher_detection' || status === 'bad_teacher_sample') {
			return 'border-danger/30 bg-danger/10 text-danger';
		}
		if (status === 'retrying' || status === 'needs_gemini') return 'border-amber-500/40 bg-amber-500/10 text-amber-700';
		if (status === 'uploading') return 'border-primary/30 bg-primary/10 text-primary';
		return 'border-border bg-bg text-text-muted';
	}

	function rowAccent(status: string): string {
		if (status === 'failed' || status === 'no_teacher_detection' || status === 'bad_teacher_sample') {
			return 'bg-danger/[0.04]';
		}
		if (status === 'retrying' || status === 'needs_gemini') return 'bg-amber-500/[0.04]';
		return '';
	}

	function roleLabel(value: string | null | undefined): string {
		if (!value) return '–';
		if (value === 'classification_channel') return 'C4';
		if (value === 'c_channel_2') return 'C2';
		if (value === 'c_channel_3') return 'C3';
		return value;
	}

	function formatTime(value: number | null | undefined): string {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '–';
		return new Intl.DateTimeFormat(undefined, {
			month: 'short',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		}).format(new Date(value * 1000));
	}

	function formatAge(value: number | null | undefined): string {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '–';
		if (value < 60) return `${Math.round(value)}s`;
		if (value < 3600) return `${Math.round(value / 60)}m`;
		if (value < 86400) return `${Math.round(value / 3600)}h`;
		return `${Math.round(value / 86400)}d`;
	}

	function shortSampleId(id: string | null): string {
		if (!id) return '–';
		return id.length > 22 ? `…${id.slice(-22)}` : id;
	}

	onMount(() => {
		void loadQueue();
		const timer = setInterval(() => void loadQueue({ silent: true }), 5000);
		return () => clearInterval(timer);
	});
</script>

<div class="flex flex-col gap-3">
	<header class="flex flex-wrap items-center gap-3">
		<a
			href="/settings/hive"
			class="inline-flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-text"
		>
			<ArrowLeft size={14} />
			Hive
		</a>
		<span class="text-text-muted">/</span>
		<h1 class="text-base font-semibold tracking-tight text-text">
			Queue
			{#if selectedTarget}
				<span class="text-text-muted">· {selectedTarget.name}</span>
			{/if}
		</h1>
		<div class="ml-auto flex flex-wrap items-center gap-1.5">
			<button
				type="button"
				onclick={() => void loadQueue({ silent: true })}
				class="inline-flex items-center gap-1.5 border border-border bg-bg px-2 py-1 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
				disabled={refreshing || actionBusy !== null}
				title="Refresh"
			>
				<RefreshCw size={12} class={refreshing ? 'animate-spin' : ''} />
				Refresh
			</button>
			<button
				type="button"
				onclick={() => void purgeQueue()}
				class="inline-flex items-center gap-1.5 border border-border bg-bg px-2 py-1 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
				disabled={actionBusy !== null || totals.queued <= 0}
				title="Drop waiting upload jobs"
			>
				<Trash2 size={12} />
				{actionBusy === 'queue' ? 'Purging…' : `Purge queue (${totals.queued})`}
			</button>
			<button
				type="button"
				onclick={() => void purgeBlockedSamples()}
				class="inline-flex items-center gap-1.5 border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-500/15 disabled:cursor-not-allowed disabled:opacity-60"
				disabled={actionBusy !== null || blockedTotal <= 0}
				title="Delete samples that still need Gemini, have no Gemini box, or failed crop"
			>
				<Trash2 size={12} />
				{actionBusy === 'blocked-samples' ? 'Purging…' : `Purge blocked (${blockedTotal})`}
			</button>
			<button
				type="button"
				onclick={() => void purgeAllSamples()}
				class="inline-flex items-center gap-1.5 border border-danger/40 bg-danger/10 px-2 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger/15 disabled:cursor-not-allowed disabled:opacity-60"
				disabled={actionBusy !== null || !payload}
				title="Wipe queue and all local samples"
			>
				<Trash2 size={12} />
				{actionBusy === 'all-samples' ? 'Purging…' : 'Purge all'}
			</button>
		</div>
	</header>

	{#if errorMsg}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger">{errorMsg}</div>
	{/if}
	{#if actionMsg}
		<div class="border border-success bg-success/10 px-3 py-2 text-sm text-success">{actionMsg}</div>
	{/if}

	{#if loading}
		<div class="border border-border bg-surface px-3 py-2 text-sm text-text-muted">Loading…</div>
	{:else if payload}
		<div class="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
			{@render statTile('Queued', totals.queued, Clock3, 'border-border')}
			{@render statTile('Uploading', totals.uploading, UploadCloud, 'border-primary/30 text-primary')}
			{@render statTile('Done', totals.recent_uploaded, CheckCircle2, 'border-success/30 text-success')}
			{@render statTile('Retry / failed', failedTotal, AlertTriangle, 'border-danger/30 text-danger')}
			{@render statTile('Needs work', blockedTotal, Sparkles, 'border-amber-500/40 text-amber-700')}
			{@render statTile('Ready local', totals.teacher_ready, CheckCircle2, 'border-border')}
		</div>

		<div class="flex flex-wrap items-center gap-1 border border-border bg-surface px-2 py-1.5">
			{@render filterChip('all', `All (${allItems.length})`)}
			{@render filterChip('problem', `Needs attention (${allItems.filter((i) => i.problem).length})`)}
			{@render filterChip('queue', `In flight (${totals.queued + totals.uploading})`)}
			{@render filterChip('done', `Uploaded (${totals.recent_uploaded})`)}
			<span class="ml-auto font-mono text-[11px] text-text-muted tabular-nums">
				{filteredItems.length}/{allItems.length} shown
			</span>
		</div>

		<section class="border border-border bg-surface">
			<div class="grid grid-cols-[44px_minmax(0,1fr)_92px_44px_56px_56px_88px] items-center gap-2 border-b border-border bg-bg px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
				<span></span>
				<span>Sample</span>
				<span>Status</span>
				<span class="text-center">Src</span>
				<span class="text-right">Boxes</span>
				<span class="text-right">Age</span>
				<span class="text-right">Time</span>
			</div>

			{#if filteredItems.length === 0}
				<div class="px-3 py-6 text-center text-sm text-text-muted">
					{#if allItems.length === 0}
						Queue is empty.
					{:else}
						Nothing matches this filter.
					{/if}
				</div>
			{:else}
				<ul class="divide-y divide-border">
					{#each filteredItems as item (item.list_id)}
						<li class={`grid grid-cols-[44px_minmax(0,1fr)_92px_44px_56px_56px_88px] items-center gap-2 px-3 py-1.5 transition-colors hover:bg-bg ${rowAccent(item.list_status)}`}>
							<div class="h-10 w-10 overflow-hidden border border-border bg-bg">
								{#if item.image_url}
									<img
										src={item.image_url}
										alt=""
										class="h-full w-full object-cover"
										loading="lazy"
									/>
								{:else}
									<div class="flex h-full items-center justify-center text-text-muted">
										<ImageOff size={14} />
									</div>
								{/if}
							</div>

							<div class="min-w-0">
								<div class="flex items-center gap-2 text-sm text-text">
									<span class="truncate font-mono text-xs">{shortSampleId(item.sample_id)}</span>
									{#if !targetId && item.target_name}
										<span class="shrink-0 truncate text-[11px] text-text-muted">→ {item.target_name}</span>
									{/if}
								</div>
								<div class="flex items-center gap-2 text-[11px] text-text-muted">
									<span>{item.detection_algorithm ?? 'no detector'}</span>
									{#if item.capture_reason}
										<span>·</span>
										<span>{item.capture_reason}</span>
									{/if}
									{#if item.list_detail}
										<span>·</span>
										<span class="truncate text-danger/80">{item.list_detail}</span>
									{/if}
								</div>
							</div>

							<span class={`inline-flex justify-center border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusTone(item.list_status)}`}>
								{item.list_label}
							</span>

							<span class="text-center font-mono text-[11px] text-text-muted">{roleLabel(item.source_role)}</span>

							<span class="text-right font-mono text-[11px] tabular-nums text-text-muted">
								{item.detection_bbox_count ?? '–'}
							</span>

							<span class="text-right font-mono text-[11px] tabular-nums text-text-muted">
								{formatAge(item.age_s)}
							</span>

							<span class="text-right font-mono text-[11px] tabular-nums text-text-muted">
								{formatTime(item.finished_at ?? item.queued_at ?? item.captured_at)}
							</span>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}
</div>

{#snippet statTile(label: string, value: number, Icon: any, accent: string)}
	<div class={`flex items-center justify-between border bg-surface px-2.5 py-1.5 ${accent}`}>
		<div class="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
			<Icon size={12} />
			{label}
		</div>
		<span class="font-mono text-base font-semibold tabular-nums">{value}</span>
	</div>
{/snippet}

{#snippet filterChip(id: FilterId, label: string)}
	{@const active = filter === id}
	<button
		type="button"
		onclick={() => (filter = id)}
		class={`border px-2 py-0.5 text-[11px] transition-colors ${active ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-bg text-text-muted hover:text-text'}`}
	>
		{label}
	</button>
{/snippet}
