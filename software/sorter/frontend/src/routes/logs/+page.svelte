<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';

	type LogSource = {
		id: string;
		label: string;
		description: string;
		available: boolean;
		path: string | null;
		size_bytes: number | null;
		updated_at: number | null;
	};

	type LogPayload = {
		id: string;
		label: string;
		description: string;
		name: string;
		path: string;
		size_bytes: number;
		updated_at: number;
		content: string;
	};

	type LogLevel = 'ERROR' | 'WARN' | 'INFO' | 'DEBUG' | 'OTHER';

	type LogEntry = {
		index: number;
		raw: string;
		timestamp: string | null;
		level: LogLevel;
		message: string;
	};

	const manager = getMachinesContext();

	let sources = $state<LogSource[]>([]);
	let selectedSourceId = $state<string | null>(null);
	let selectedLog = $state<LogPayload | null>(null);
	let parsedEntries = $state<LogEntry[]>([]);
	let initialLoading = $state(true);
	let refreshingSources = $state(false);
	let refreshingContent = $state(false);
	let error = $state<string | null>(null);
	let autoRefresh = $state(false);
	let wrapLines = $state(true);
	let lineLimit = $state('400');
	let searchQuery = $state('');
	let levelFilter = $state<'all' | LogLevel>('all');

	let sourcesRequestSeq = 0;
	let contentRequestSeq = 0;

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function formatTimestamp(value: number | null): string {
		if (value == null) return 'n/a';
		return new Date(value * 1000).toLocaleString();
	}

	function formatBytes(value: number | null): string {
		if (value == null) return 'n/a';
		if (value < 1024) return `${value} B`;
		if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
		return `${(value / (1024 * 1024)).toFixed(1)} MB`;
	}

	function preferredSourceId(availableSources: LogSource[]): string | null {
		const preferred = availableSources.find((source) => source.id === 'machine-backend' && source.available);
		if (preferred) return preferred.id;
		return availableSources.find((source) => source.available)?.id ?? null;
	}

	async function loadSources(background = false) {
		const requestId = ++sourcesRequestSeq;
		if (background) {
			refreshingSources = true;
		} else {
			initialLoading = sources.length === 0;
		}

		try {
			const res = await fetch(`${baseUrl()}/api/logs`);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			if (requestId !== sourcesRequestSeq) return;
			const nextSources = Array.isArray(data.sources) ? (data.sources as LogSource[]) : [];
			sources = nextSources;
			if (!selectedSourceId || !nextSources.some((source) => source.id === selectedSourceId && source.available)) {
				selectedSourceId = preferredSourceId(nextSources);
			}
			error = null;
		} catch (e: unknown) {
			if (requestId !== sourcesRequestSeq) return;
			error = e instanceof Error ? e.message : 'Failed to load log sources';
			sources = [];
			selectedSourceId = null;
			selectedLog = null;
			parsedEntries = [];
		} finally {
			if (requestId !== sourcesRequestSeq) return;
			initialLoading = false;
			refreshingSources = false;
		}
	}

	async function loadSelectedLog(background = false) {
		if (!selectedSourceId) {
			selectedLog = null;
			parsedEntries = [];
			return;
		}

		const requestId = ++contentRequestSeq;
		refreshingContent = background || selectedLog !== null;

		try {
			const res = await fetch(`${baseUrl()}/api/logs/${encodeURIComponent(selectedSourceId)}?lines=${Number(lineLimit)}`);
			if (!res.ok) {
				const body = await res.json().catch(() => null);
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			const payload = (await res.json()) as LogPayload;
			if (requestId !== contentRequestSeq) return;
			selectedLog = payload;
			parsedEntries = parseLogContent(payload.content);
			error = null;
		} catch (e: unknown) {
			if (requestId !== contentRequestSeq) return;
			error = e instanceof Error ? e.message : 'Failed to load log content';
		} finally {
			if (requestId !== contentRequestSeq) return;
			refreshingContent = false;
		}
	}

	function inferLevel(raw: string): LogLevel {
		if (/\[(ERROR|CRITICAL)\]/.test(raw) || /^(ERROR|CRITICAL)(:|\s|$)/.test(raw)) return 'ERROR';
		if (/\[(WARN|WARNING)\]/.test(raw) || /^(WARN|WARNING)(:|\s|$)/.test(raw)) return 'WARN';
		if (/\[INFO\]/.test(raw) || /^INFO(:|\s|$)/.test(raw)) return 'INFO';
		if (/\[DEBUG\]/.test(raw) || /^DEBUG(:|\s|$)/.test(raw)) return 'DEBUG';
		return 'OTHER';
	}

	function parseLogContent(content: string): LogEntry[] {
		if (!content) return [];
		return content.split('\n').map((raw, index) => {
			const bracketed = raw.match(/^\[([^\]]+)\]\s+\[([A-Z]+)\]\s+(.*)$/);
			if (bracketed) {
				const level = inferLevel(`[${bracketed[2]}]`) as LogLevel;
				return {
					index,
					raw,
					timestamp: bracketed[1],
					level,
					message: bracketed[3],
				};
			}

			const colonLevel = raw.match(/^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)(?::[^:]+)?:\s*(.*)$/);
			if (colonLevel) {
				const level = inferLevel(colonLevel[1]);
				return {
					index,
					raw,
					timestamp: null,
					level,
					message: colonLevel[2],
				};
			}

			return {
				index,
				raw,
				timestamp: null,
				level: inferLevel(raw),
				message: raw,
			};
		});
	}

	function filteredEntries(): LogEntry[] {
		const query = searchQuery.trim().toLowerCase();
		return parsedEntries.filter((entry) => {
			if (levelFilter !== 'all' && entry.level !== levelFilter) return false;
			if (!query) return true;
			return entry.raw.toLowerCase().includes(query);
		});
	}

	function countByLevel(level: LogLevel): number {
		return parsedEntries.filter((entry) => entry.level === level).length;
	}

	const LEVEL_LABELS: Record<LogLevel, string> = {
		ERROR: 'Error',
		WARN: 'Warning',
		INFO: 'Info',
		DEBUG: 'Debug',
		OTHER: 'Other'
	};
	const LEVEL_TONES = {
		ERROR: 'danger',
		WARN: 'warning',
		INFO: 'info',
		DEBUG: 'neutral',
		OTHER: 'neutral'
	} as const;

	async function refreshNow() {
		await loadSources(true);
		await loadSelectedLog(true);
	}

	onMount(() => {
		void loadSources(false).then(() => loadSelectedLog(false));
		let tick = 0;
		const interval = setInterval(() => {
			if (!autoRefresh) return;
			void loadSelectedLog(true);
			tick += 1;
			if (tick % 10 === 0) {
				void loadSources(true);
			}
		}, 3000);
		return () => clearInterval(interval);
	});

	$effect(() => {
		if (selectedSourceId) {
			void loadSelectedLog(true);
		}
	});
</script>

<svelte:head><title>Sorter - Logs</title></svelte:head>

<AppShell fit>
	<div class="mx-auto flex min-h-0 w-full max-w-[1500px] flex-1 flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader title="Logs" description="Curated log sources with search, level filtering and a steady refresh.">
			{#snippet actions()}
				<div class="flex items-center gap-2">
					<span class="text-sm text-ink-muted">Lines</span>
					<Select
						label="Lines to show"
						class="w-24"
						bind:value={lineLimit}
						options={['200', '400', '800', '1500'].map((n) => ({ value: n, label: n }))}
					/>
				</div>
				<div class="flex items-center gap-2">
					<span id="logs-auto-refresh" class="text-sm text-ink-muted">Auto refresh</span>
					<Switch labelledby="logs-auto-refresh" bind:checked={autoRefresh} />
				</div>
				<div class="flex items-center gap-2">
					<span id="logs-wrap" class="text-sm text-ink-muted">Wrap lines</span>
					<Switch labelledby="logs-wrap" bind:checked={wrapLines} />
				</div>
				<Button
					loading={refreshingSources || refreshingContent}
					onclick={() => void refreshNow()}
				>
					Refresh
				</Button>
			{/snippet}
		</PageHeader>

		{#if error}<Alert tone="danger">{error}</Alert>{/if}

		<div class="grid grid-cols-1 min-h-0 gap-(--gap-panels) lg:flex-1 xl:grid-cols-[20rem_minmax(0,1fr)]">
			<Panel title="Sources" flush fill>
				{#if initialLoading && sources.length === 0}
					<p class="flex items-center gap-2 px-(--pad-panel) pb-4 text-sm text-ink-muted">
						<Spinner size={16} />
						Loading the log sources
					</p>
				{:else}
					<ul class="divide-y divide-line">
						{#each sources as source}
							<li>
								<button
									type="button"
									onclick={() => {
										if (source.available) selectedSourceId = source.id;
									}}
									disabled={!source.available}
									aria-pressed={selectedSourceId === source.id}
									class="w-full px-(--pad-panel) py-3 text-left transition-colors disabled:pointer-events-none disabled:opacity-50 {selectedSourceId === source.id
										? 'bg-primary-soft'
										: 'hover:bg-hover'}"
								>
									<div class="flex items-center justify-between gap-2">
										<span class="text-sm font-medium text-ink">{source.label}</span>
										<span class="num text-xs text-ink-muted">
											{source.available ? formatBytes(source.size_bytes) : 'Unavailable'}
										</span>
									</div>
									<div class="mt-1 text-sm text-ink-muted">{source.description}</div>
									{#if source.available}
										<div class="mt-2 truncate font-mono text-xs text-ink-muted">{source.path}</div>
										<div class="mt-1 text-sm text-ink-muted">Updated {formatTimestamp(source.updated_at)}</div>
									{/if}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</Panel>

			<Panel
				title={selectedLog ? selectedLog.label : 'Log output'}
				description={selectedLog ? selectedLog.description : 'Select an available source to inspect its logs.'}
				flush
				fill
			>
				{#snippet actions()}
					{#if selectedLog}
						<div class="flex items-center gap-3 text-sm text-ink-muted">
							{#if refreshingContent || refreshingSources}<Spinner size={14} />{/if}
							<span class="num">{formatBytes(selectedLog.size_bytes)}</span>
							<span>Updated {formatTimestamp(selectedLog.updated_at)}</span>
						</div>
					{/if}
				{/snippet}
				{#if selectedLog}
					<div class="sticky top-0 z-10 flex flex-col gap-3 bg-surface px-(--pad-panel) pb-3">
						<p class="truncate font-mono text-xs text-ink-muted">{selectedLog.path}</p>
						<div class="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_12rem]">
							<Input
								aria-label="Search the log"
								placeholder="Search message text, error names, part IDs, camera names"
								bind:value={searchQuery}
							/>
							<Select
								label="Level"
								bind:value={levelFilter}
								options={[
									{ value: 'all', label: 'All levels' },
									{ value: 'ERROR', label: 'Errors only' },
									{ value: 'WARN', label: 'Warnings only' },
									{ value: 'INFO', label: 'Info only' },
									{ value: 'DEBUG', label: 'Debug only' },
									{ value: 'OTHER', label: 'Other or raw only' }
								]}
							/>
						</div>
						<div class="flex flex-wrap items-center gap-2">
							<Badge>{filteredEntries().length} matching lines</Badge>
							<Badge tone="danger">Errors: {countByLevel('ERROR')}</Badge>
							<Badge tone="warning">Warnings: {countByLevel('WARN')}</Badge>
							<Badge tone="info">Info: {countByLevel('INFO')}</Badge>
						</div>
					</div>

					{#if filteredEntries().length === 0}
						<p class="bg-well px-(--pad-panel) py-4 text-sm text-ink-muted">
							No log lines match the current filters.
						</p>
					{:else}
						<div class="divide-y divide-line bg-well">
							{#each filteredEntries() as entry (entry.index + ':' + entry.raw)}
								<div
									class="grid gap-x-3 gap-y-1 px-(--pad-panel) py-2 text-sm {wrapLines
										? ''
										: 'grid-cols-[7rem_5rem_minmax(0,1fr)] items-baseline'}"
								>
									<div class="font-mono text-ink-muted">{entry.timestamp ?? ''}</div>
									<div><Badge tone={LEVEL_TONES[entry.level]}>{LEVEL_LABELS[entry.level]}</Badge></div>
									<div
										class="font-mono text-ink {wrapLines
											? 'break-words whitespace-pre-wrap'
											: 'overflow-x-auto whitespace-pre'}"
									>
										{entry.message}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				{:else}
					<div class="px-(--pad-panel) pb-(--pad-panel)">
						<EmptyState title="No log source is selected" />
					</div>
				{/if}
			</Panel>
		</div>
	</div>
</AppShell>
