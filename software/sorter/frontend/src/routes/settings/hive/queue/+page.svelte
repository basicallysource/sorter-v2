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
		UploadCloud,
		X
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
		sample_type?: string | null;
		sample_type_label?: string | null;
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
		condition_teacher?: {
			enabled?: boolean;
			running?: boolean;
			last_run_at?: number | null;
			last_selected?: number;
			last_archived?: number;
			last_errors?: number;
			last_error?: string | null;
			total_archived?: number;
			total_errors?: number;
			total_runs?: number;
			batch_size?: number;
			lookback_minutes?: number;
		};
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
	type SampleTypeId = 'all' | 'teacher_detection' | 'condition' | 'classification' | 'other';
	type BackfillKind = 'upload' | 'condition';
	type BackfillSelection = 'latest' | 'random' | 'today' | 'last_minutes' | 'time_range';

	let payload = $state<QueuePayload | null>(null);
	let loading = $state(true);
	let refreshing = $state(false);
	let errorMsg = $state<string | null>(null);
	let actionMsg = $state<string | null>(null);
	let actionBusy = $state<string | null>(null);
	let filter = $state<FilterId>('all');
	let sampleTypeFilter = $state<SampleTypeId>('all');
	let backfillOpen = $state(false);
	let backfillKind = $state<BackfillKind>('upload');
	let backfillSampleType = $state<SampleTypeId>('teacher_detection');
	let backfillSelection = $state<BackfillSelection>('latest');
	let backfillLimit = $state(100);
	let backfillConditionLimit = $state(10);
	let backfillMaxCropsPerPiece = $state(1);
	let backfillMinutes = $state(30);
	let backfillFrom = $state('');
	let backfillTo = $state('');
	let backfillForce = $state(false);
	let backfillDryRun = $state(false);

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
		let items = allItems;
		if (sampleTypeFilter !== 'all') {
			items = items.filter((item) => itemSampleType(item) === sampleTypeFilter);
		}
		if (filter === 'problem') return items.filter((item) => item.problem);
		if (filter === 'queue') {
			return items.filter((item) => item.list_status === 'queued' || item.list_status === 'uploading');
		}
		if (filter === 'done') return items.filter((item) => item.list_status === 'uploaded');
		return items;
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

	function backfillTimestamp(value: string): number | null {
		if (!value.trim()) return null;
		const timestamp = Date.parse(value);
		return Number.isFinite(timestamp) ? timestamp / 1000 : null;
	}

	function backfillWindowPayload(): Record<string, number | string | null> {
		const body: Record<string, number | string | null> = {
			selection: backfillSelection,
			minutes: backfillSelection === 'last_minutes' ? backfillMinutes : null,
			from_ts: null,
			to_ts: null
		};
		if (backfillSelection === 'time_range') {
			body.from_ts = backfillTimestamp(backfillFrom);
			body.to_ts = backfillTimestamp(backfillTo);
		}
		return body;
	}

	async function startBackfill() {
		actionBusy = 'backfill';
		errorMsg = null;
		actionMsg = null;
		try {
			if (backfillKind === 'condition') {
				const res = await fetch(`${currentBackendBaseUrl()}/api/samples/condition/backfill`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						limit: Math.max(0, Math.min(50, Number(backfillConditionLimit) || 0)),
						max_crops_per_piece: Math.max(1, Math.min(5, Number(backfillMaxCropsPerPiece) || 1)),
						force: backfillForce,
						dry_run: backfillDryRun,
						...backfillWindowPayload()
					})
				});
				if (!res.ok) throw new Error(await res.text());
				const data = await res.json();
				if (!data.ok && !data.dry_run) throw new Error(data.error ?? 'Condition backfill failed.');
				actionMsg = data.dry_run
					? `Condition dry run selected ${data.selected ?? 0} crop${data.selected === 1 ? '' : 's'}.`
					: `Condition backfill archived ${data.archived ?? 0}/${data.selected ?? 0} crop${data.selected === 1 ? '' : 's'}${data.errors ? ` (${data.errors} errors)` : ''}.`;
			} else {
				const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/backfill`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						target_ids: targetId ? [targetId] : null,
						sample_type: backfillSampleType,
						limit: Math.max(0, Math.min(500, Number(backfillLimit) || 0)),
						...backfillWindowPayload()
					})
				});
				if (!res.ok) throw new Error(await res.text());
				const data = await res.json();
				if (!data.ok) throw new Error(data.error ?? 'Backfill failed.');
				actionMsg =
					`Queued ${data.queued ?? 0} ${typeLabel(backfillSampleType).toLowerCase()} sample` +
					`${data.queued === 1 ? '' : 's'} (${data.skipped ?? 0} skipped` +
					`${data.needs_gemini ? `, ${data.needs_gemini} need Gemini` : ''}` +
					`${data.no_teacher_detection ? `, ${data.no_teacher_detection} no Gemini box` : ''}` +
					`${data.bad_teacher_sample ? `, ${data.bad_teacher_sample} bad crop` : ''}` +
					`${data.dark_image_sample ? `, ${data.dark_image_sample} too dark` : ''}` +
					`${data.errors ? `, ${data.errors} errors` : ''}).`;
			}
			await loadQueue({ silent: true });
		} catch (e: any) {
			errorMsg = e?.message ?? 'Backfill failed.';
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

	function normalizeSampleType(value: string | null | undefined): SampleTypeId {
		if (value === 'teacher_detection' || value === 'condition' || value === 'classification' || value === 'other') {
			return value;
		}
		return 'other';
	}

	function itemSampleType(item: QueueJob): SampleTypeId {
		const explicit = normalizeSampleType(item.sample_type);
		if (explicit !== 'other') return explicit;
		if (item.capture_reason === 'piece_condition_teacher' || item.source_role === 'piece_crop') {
			return 'condition';
		}
		if (item.detection_algorithm === 'gemini_sam') return 'teacher_detection';
		if (item.capture_reason === 'live_classification' || item.source_role === 'classification_channel') {
			return 'classification';
		}
		return explicit;
	}

	function typeLabel(value: SampleTypeId | string | null | undefined): string {
		const type = normalizeSampleType(value === 'all' ? null : value);
		if (value === 'all') return 'All types';
		if (type === 'teacher_detection') return 'Gemini boxes';
		if (type === 'condition') return 'Condition';
		if (type === 'classification') return 'Classification';
		return 'Other';
	}

	function typeCount(type: SampleTypeId): number {
		if (type === 'all') return allItems.length;
		return allItems.filter((item) => itemSampleType(item) === type).length;
	}

	function sampleTypeTone(type: SampleTypeId): string {
		if (type === 'all') return 'border-primary bg-primary/10 text-primary';
		if (type === 'teacher_detection') return 'border-amber-500/30 bg-amber-500/10 text-amber-700';
		if (type === 'condition') return 'border-primary/30 bg-primary/10 text-primary';
		if (type === 'classification') return 'border-success/30 bg-success/10 text-success';
		return 'border-border bg-bg text-text-muted';
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
				onclick={() => (backfillOpen = !backfillOpen)}
				class="inline-flex items-center gap-1.5 border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-60"
				disabled={actionBusy !== null}
				title="Backfill archived samples with filters"
			>
				<UploadCloud size={12} />
				Backfill
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

	{#if backfillOpen}
		<section class="border border-border bg-surface p-3">
			<div class="mb-3 flex items-start gap-3">
				<div>
					<h2 class="text-sm font-semibold tracking-tight text-text">Scoped backfill</h2>
					<p class="mt-0.5 max-w-2xl text-xs text-text-muted">
						Queue existing archive samples, or generate new condition samples from piece crops. Keep it small when Gemini is involved.
					</p>
				</div>
				<button
					type="button"
					onclick={() => (backfillOpen = false)}
					class="ml-auto inline-flex h-8 w-8 items-center justify-center border border-border bg-bg text-text-muted transition-colors hover:text-text"
					title="Close backfill panel"
				>
					<X size={14} />
				</button>
			</div>

			<div class="grid gap-2 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)]">
				<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
					Mode
					<select
						bind:value={backfillKind}
						class="border border-border bg-bg px-2 py-1.5 text-sm normal-case tracking-normal text-text"
					>
						<option value="upload">Upload archived samples</option>
						<option value="condition">Generate condition samples</option>
					</select>
				</label>

				{#if backfillKind === 'upload'}
					<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
						Sample type
						<select
							bind:value={backfillSampleType}
							class="border border-border bg-bg px-2 py-1.5 text-sm normal-case tracking-normal text-text"
						>
							<option value="all">All types</option>
							<option value="teacher_detection">Gemini boxes</option>
							<option value="condition">Condition</option>
							<option value="classification">Classification</option>
							<option value="other">Other</option>
						</select>
					</label>
					<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
						Limit
						<input
							type="number"
							min="0"
							max="500"
							bind:value={backfillLimit}
							class="border border-border bg-bg px-2 py-1.5 font-mono text-sm normal-case tracking-normal text-text tabular-nums"
						/>
					</label>
				{:else}
					<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
						Crops
						<input
							type="number"
							min="0"
							max="50"
							bind:value={backfillConditionLimit}
							class="border border-border bg-bg px-2 py-1.5 font-mono text-sm normal-case tracking-normal text-text tabular-nums"
						/>
					</label>
					<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
						Max per piece
						<input
							type="number"
							min="1"
							max="5"
							bind:value={backfillMaxCropsPerPiece}
							class="border border-border bg-bg px-2 py-1.5 font-mono text-sm normal-case tracking-normal text-text tabular-nums"
						/>
					</label>
				{/if}

				<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
					Selection
					<select
						bind:value={backfillSelection}
						class="border border-border bg-bg px-2 py-1.5 text-sm normal-case tracking-normal text-text"
					>
						<option value="latest">Latest first</option>
						<option value="random">Random sample</option>
						<option value="today">Today</option>
						<option value="last_minutes">Last minutes</option>
						<option value="time_range">Time range</option>
					</select>
				</label>
			</div>

			{#if backfillSelection === 'last_minutes' || backfillSelection === 'time_range' || backfillKind === 'condition'}
				<div class="mt-2 grid gap-2 md:grid-cols-3">
					{#if backfillSelection === 'last_minutes'}
						<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
							Minutes
							<input
								type="number"
								min="1"
								max="1440"
								bind:value={backfillMinutes}
								class="border border-border bg-bg px-2 py-1.5 font-mono text-sm normal-case tracking-normal text-text tabular-nums"
							/>
						</label>
					{/if}
					{#if backfillSelection === 'time_range'}
						<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
							From
							<input
								type="datetime-local"
								bind:value={backfillFrom}
								class="border border-border bg-bg px-2 py-1.5 font-mono text-sm normal-case tracking-normal text-text tabular-nums"
							/>
						</label>
						<label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
							To
							<input
								type="datetime-local"
								bind:value={backfillTo}
								class="border border-border bg-bg px-2 py-1.5 font-mono text-sm normal-case tracking-normal text-text tabular-nums"
							/>
						</label>
					{/if}
					{#if backfillKind === 'condition'}
						<label class="flex min-h-10 items-center gap-2 border border-border bg-bg px-2 py-1.5 text-xs text-text">
							<input type="checkbox" bind:checked={backfillDryRun} />
							Dry run
						</label>
						<label class="flex min-h-10 items-center gap-2 border border-border bg-bg px-2 py-1.5 text-xs text-text">
							<input type="checkbox" bind:checked={backfillForce} />
							Allow duplicates
						</label>
					{/if}
				</div>
			{/if}

			<div class="mt-3 flex flex-wrap items-center gap-2">
				<button
					type="button"
					onclick={() => void startBackfill()}
					class="inline-flex min-h-10 items-center gap-1.5 border border-primary bg-primary px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
					disabled={actionBusy !== null}
				>
					<UploadCloud size={14} />
					{actionBusy === 'backfill' ? 'Starting…' : 'Start backfill'}
				</button>
				<p class="text-xs text-text-muted">
					{#if targetId && selectedTarget}
						Target: {selectedTarget.name}.
					{:else if backfillKind === 'upload'}
						Target: every enabled Hive.
					{:else}
						Condition samples are archived locally and then queued through the normal Hive uploader.
					{/if}
				</p>
			</div>
		</section>
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

		{#if payload.condition_teacher}
			<div class="flex flex-wrap items-center gap-2 border border-border bg-surface px-2 py-1.5 text-xs text-text-muted">
				<span class="inline-flex items-center gap-1 font-semibold text-text">
					<Sparkles size={12} />
					Condition teacher
				</span>
				<span class={`border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${payload.condition_teacher.running ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-bg text-text-muted'}`}>
					{payload.condition_teacher.running ? 'Running' : 'Idle'}
				</span>
				<span>
					Last: {payload.condition_teacher.last_archived ?? 0}/{payload.condition_teacher.last_selected ?? 0} archived
				</span>
				<span>·</span>
				<span>Total: {payload.condition_teacher.total_archived ?? 0}</span>
				<span>·</span>
				<span>Lookback: {payload.condition_teacher.lookback_minutes ?? 0}m</span>
				<span>·</span>
				<span>Last run: {formatTime(payload.condition_teacher.last_run_at)}</span>
				{#if payload.condition_teacher.last_error}
					<span>·</span>
					<span class="truncate text-danger">{payload.condition_teacher.last_error}</span>
				{/if}
			</div>
		{/if}

		<div class="flex flex-wrap items-center gap-1 border border-border bg-surface px-2 py-1.5">
			{@render filterChip('all', `All (${allItems.length})`)}
			{@render filterChip('problem', `Needs attention (${allItems.filter((i) => i.problem).length})`)}
			{@render filterChip('queue', `In flight (${totals.queued + totals.uploading})`)}
			{@render filterChip('done', `Uploaded (${totals.recent_uploaded})`)}
			<span class="mx-1 h-4 w-px bg-border"></span>
			{@render typeFilterChip('all', `All types (${typeCount('all')})`)}
			{@render typeFilterChip('teacher_detection', `Gemini (${typeCount('teacher_detection')})`)}
			{@render typeFilterChip('condition', `Condition (${typeCount('condition')})`)}
			{@render typeFilterChip('classification', `Classification (${typeCount('classification')})`)}
			{@render typeFilterChip('other', `Other (${typeCount('other')})`)}
			<span class="ml-auto font-mono text-[11px] text-text-muted tabular-nums">
				{filteredItems.length}/{allItems.length} shown
			</span>
		</div>

		<section class="border border-border bg-surface">
			<div class="grid grid-cols-[44px_minmax(0,1fr)_92px_90px_44px_56px_56px_88px] items-center gap-2 border-b border-border bg-bg px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
				<span></span>
				<span>Sample</span>
				<span>Status</span>
				<span>Type</span>
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
						<li class={`grid grid-cols-[44px_minmax(0,1fr)_92px_90px_44px_56px_56px_88px] items-center gap-2 px-3 py-1.5 transition-colors hover:bg-bg ${rowAccent(item.list_status)}`}>
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

							<span class={`inline-flex justify-center border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${sampleTypeTone(itemSampleType(item))}`}>
								{typeLabel(itemSampleType(item))}
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

{#snippet typeFilterChip(id: SampleTypeId, label: string)}
	{@const active = sampleTypeFilter === id}
	<button
		type="button"
		onclick={() => (sampleTypeFilter = id)}
		class={`border px-2 py-0.5 text-[11px] transition-colors ${active ? sampleTypeTone(id) : 'border-border bg-bg text-text-muted hover:text-text'}`}
	>
		{label}
	</button>
{/snippet}
