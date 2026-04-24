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
	};

	let payload = $state<QueuePayload | null>(null);
	let loading = $state(true);
	let refreshing = $state(false);
	let errorMsg = $state<string | null>(null);
	let actionMsg = $state<string | null>(null);
	let actionBusy = $state<string | null>(null);

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
	const listItems = $derived.by(() => buildListItems(payload));

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
				items.push(decorateJob(job, 'teacher_ready'));
			}
		}

		return items.sort((a, b) => a.list_rank - b.list_rank || b.sort_ts - a.sort_ts).slice(0, 160);
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
			image_url: sampleImageUrl(job)
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
		if (status === 'queued') return 'Waiting Queue';
		if (status === 'uploaded') return 'Uploaded';
		if (status === 'retrying') return 'Retrying';
		if (status === 'failed') return 'Failed';
		if (status === 'skipped') return 'Skipped';
		if (status === 'needs_gemini') return 'Needs Gemini';
		if (status === 'no_teacher_detection') return 'No Gemini Box';
		if (status === 'bad_teacher_sample') return 'Bad Crop';
		if (status === 'teacher_ready') return 'Ready';
		return status;
	}

	function statusDetail(job: QueueJob, status: string): string {
		if (job.message) return job.message;
		if (status === 'needs_gemini') return 'Waiting for Gemini-SAM labels before upload.';
		if (status === 'no_teacher_detection') return job.teacher_reason;
		if (status === 'bad_teacher_sample') return job.teacher_reason;
		if (status === 'teacher_ready') return 'Gemini labels are present; sample can be uploaded.';
		if (status === 'queued') return 'Queued for Hive upload.';
		if (status === 'uploading') return 'Upload is currently in flight.';
		if (status === 'uploaded') return 'Hive accepted this sample.';
		if (status === 'retrying') return 'Upload failed transiently and will be retried.';
		if (status === 'failed') return 'Upload failed after retry handling.';
		return job.teacher_reason || 'Sample pipeline state.';
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

	function statusTone(status: string): string {
		if (status === 'uploaded' || status === 'teacher_ready') return 'border-success/30 bg-success/10 text-success';
		if (status === 'failed' || status === 'skipped' || status === 'no_teacher_detection' || status === 'bad_teacher_sample') {
			return 'border-danger/30 bg-danger/10 text-danger';
		}
		if (status === 'retrying' || status === 'needs_gemini') return 'border-amber-500/40 bg-amber-500/10 text-amber-700';
		if (status === 'uploading') return 'border-primary/30 bg-primary/10 text-primary';
		return 'border-border bg-bg text-text-muted';
	}

	function roleLabel(value: string | null | undefined): string {
		if (!value) return 'unknown role';
		if (value === 'classification_channel') return 'C4';
		if (value === 'c_channel_2') return 'C2';
		if (value === 'c_channel_3') return 'C3';
		return value;
	}

	function formatTime(value: number | null | undefined): string {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
		return new Intl.DateTimeFormat(undefined, {
			month: 'short',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		}).format(new Date(value * 1000));
	}

	function formatAge(value: number | null | undefined): string {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
		if (value < 60) return `${Math.round(value)}s`;
		if (value < 3600) return `${Math.round(value / 60)}m`;
		return `${Math.round(value / 3600)}h`;
	}

	onMount(() => {
		void loadQueue();
		const timer = setInterval(() => void loadQueue({ silent: true }), 5000);
		return () => clearInterval(timer);
	});
</script>

<div class="flex flex-col gap-5">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<a
				href="/settings/hive"
				class="inline-flex min-h-10 items-center gap-2 text-sm text-text-muted transition-colors hover:text-text"
			>
				<ArrowLeft size={16} />
				Back to Hive
			</a>
			<h1 class="mt-2 text-2xl font-semibold tracking-tight text-text">Hive Queue</h1>
			<p class="mt-1 max-w-3xl text-sm leading-relaxed text-text-muted">
				{#if selectedTarget}
					One compact worklist for {selectedTarget.name}: every local sample, Gemini state, upload
					state, and final outcome in one flow.
				{:else}
					One compact worklist across all Hive targets: every local sample, Gemini state, upload
					state, and final outcome in one flow.
				{/if}
			</p>
		</div>

		<div class="flex flex-wrap justify-end gap-2">
			<button
				type="button"
				onclick={() => void purgeQueue()}
				class="inline-flex min-h-10 items-center gap-2 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-60"
				disabled={actionBusy !== null || totals.queued <= 0}
			>
				<Trash2 size={14} />
				{actionBusy === 'queue' ? 'Purging...' : 'Purge queue'}
			</button>
			<button
				type="button"
				onclick={() => void purgeBlockedSamples()}
				class="inline-flex min-h-10 items-center gap-2 border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-700 transition-colors hover:bg-amber-500/15 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-60"
				disabled={actionBusy !== null || blockedTotal <= 0}
			>
				<Trash2 size={14} />
				{actionBusy === 'blocked-samples' ? 'Purging...' : 'Purge blocked'}
			</button>
			<button
				type="button"
				onclick={() => void purgeAllSamples()}
				class="inline-flex min-h-10 items-center gap-2 border border-danger/40 bg-danger/10 px-3 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger/15 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-60"
				disabled={actionBusy !== null || !payload}
			>
				<Trash2 size={14} />
				{actionBusy === 'all-samples' ? 'Purging...' : 'Purge all samples'}
			</button>
			<button
				type="button"
				onclick={() => void loadQueue({ silent: true })}
				class="inline-flex min-h-10 items-center gap-2 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-60"
				disabled={refreshing || actionBusy !== null}
			>
				<RefreshCw size={14} class={refreshing ? 'animate-spin' : ''} />
				{refreshing ? 'Refreshing...' : 'Refresh'}
			</button>
		</div>
	</div>

	{#if errorMsg}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger">
			{errorMsg}
		</div>
	{/if}
	{#if actionMsg}
		<div class="border border-success bg-success/10 px-3 py-2 text-sm text-success">
			{actionMsg}
		</div>
	{/if}

	{#if loading}
		<div class="border border-border bg-surface px-4 py-4 text-sm text-text-muted">
			Loading Hive queue...
		</div>
	{:else if payload}
		<section class="border border-border bg-surface">
			<div class="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
				<div>
					<div class="text-sm font-semibold text-text">Sample worklist</div>
					<p class="mt-1 text-xs leading-relaxed text-text-muted">
						Images are the local training crops. Rows that need Gemini, have bad crops, or failed upload
						stay at the top.
					</p>
				</div>
				<div class="flex flex-wrap items-center justify-end gap-2">
					<span class="inline-flex items-center gap-1 border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700">
						<Sparkles size={13} />
						<span class="font-mono tabular-nums">{blockedTotal}</span>
						need work
					</span>
					<span class="inline-flex items-center gap-1 border border-border bg-bg px-2 py-1 text-xs text-text-muted">
						<Clock3 size={13} />
						<span class="font-mono tabular-nums">{totals.queued}</span>
						waiting
					</span>
					<span class="inline-flex items-center gap-1 border border-primary/30 bg-primary/10 px-2 py-1 text-xs text-primary">
						<UploadCloud size={13} />
						<span class="font-mono tabular-nums">{totals.uploading}</span>
						uploading
					</span>
					<span class="inline-flex items-center gap-1 border border-success/30 bg-success/10 px-2 py-1 text-xs text-success">
						<CheckCircle2 size={13} />
						<span class="font-mono tabular-nums">{totals.recent_uploaded}</span>
						done
					</span>
					<span class="inline-flex items-center gap-1 border border-danger/30 bg-danger/10 px-2 py-1 text-xs text-danger">
						<AlertTriangle size={13} />
						<span class="font-mono tabular-nums">{totals.recent_retrying + totals.recent_failed}</span>
						retry/failed
					</span>
					<span class="font-mono text-xs text-text-muted tabular-nums">{listItems.length} visible</span>
				</div>
			</div>

			{#if listItems.length === 0}
				<div class="px-4 py-8 text-sm text-text-muted">
					No queue or local teacher sample entries right now.
				</div>
			{:else}
				<div class="divide-y divide-border">
					{#each listItems as item (item.list_id)}
						<article class="grid grid-cols-[112px,minmax(0,1fr)] gap-3 px-4 py-3 transition-colors hover:bg-bg lg:grid-cols-[144px,minmax(0,1fr),auto]">
							<div class="relative h-24 overflow-hidden border border-border bg-bg outline outline-1 outline-black/10 dark:outline-white/10 lg:h-28">
								{#if item.image_url}
									<img
										src={item.image_url}
										alt={`Sample ${item.sample_id ?? ''}`}
										class="h-full w-full object-contain"
										loading="lazy"
									/>
								{:else}
									<div class="flex h-full items-center justify-center text-text-muted">
										<ImageOff size={22} />
									</div>
								{/if}
							</div>

							<div class="min-w-0">
								<div class="flex flex-wrap items-center gap-2">
									<span class={`border px-2 py-0.5 text-xs font-semibold ${statusTone(item.list_status)}`}>
										{item.list_label}
									</span>
									<span class="text-xs font-medium text-text-muted">{roleLabel(item.source_role)}</span>
									{#if item.target_name}
										<span class="text-xs text-text-muted">to {item.target_name}</span>
									{/if}
								</div>
								<div class="mt-2 truncate font-mono text-sm text-text">
									{item.sample_id ?? 'unknown sample'}
								</div>
								<div class="mt-1 text-sm leading-relaxed text-text-muted">
									{item.list_detail}
								</div>
								<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
									<span>{item.capture_reason ?? 'capture'}</span>
									<span>{item.detection_algorithm ?? 'no detector'}</span>
									{#if item.detection_bbox_count !== null}
										<span class="tabular-nums">{item.detection_bbox_count} box{item.detection_bbox_count === 1 ? '' : 'es'}</span>
									{/if}
									{#if item.age_s !== undefined && item.age_s !== null}
										<span>queued {formatAge(item.age_s)} ago</span>
									{/if}
								</div>
							</div>

							<div class="col-span-2 flex min-w-32 items-center justify-between gap-3 border-t border-border/70 pt-2 lg:col-span-1 lg:flex-col lg:items-end lg:justify-between lg:border-t-0 lg:pt-0">
								<div class="text-xs text-text-muted">
									{formatTime(item.finished_at ?? item.queued_at ?? item.captured_at)}
								</div>
								<div class="text-right font-mono text-xs text-text-muted">
									{item.session_name ?? item.session_id ?? 'local'}
								</div>
							</div>
						</article>
					{/each}
				</div>
			{/if}
		</section>
	{/if}
</div>
