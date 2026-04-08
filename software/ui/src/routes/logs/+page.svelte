<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
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
			) ?? backendHttpBaseUrl
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

	function levelBadgeClass(level: LogLevel): string {
		if (level === 'ERROR') return 'border-[#D01012]/40 bg-[#D01012]/10 text-[#D01012]';
		if (level === 'WARN') return 'border-[#F2A900]/40 bg-[#F2A900]/10 text-[#A56D00]';
		if (level === 'INFO') return 'border-primary/40 bg-primary/10 text-primary';
		if (level === 'DEBUG') return 'border-border bg-bg text-text-muted';
		return 'border-border bg-bg text-text-muted';
	}

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

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-4 sm:p-6">
		<div class="mb-4 flex flex-wrap items-start justify-between gap-3">
			<div>
				<h2 class="text-xl font-bold text-text">Logs</h2>
				<p class="mt-1 text-sm text-text-muted">
					Curated log sources with search, level filtering, and stable refresh.
				</p>
			</div>
			<div class="flex flex-wrap items-center gap-2 text-sm">
				<label class="flex items-center gap-2 text-text-muted">
					<span>Lines</span>
					<select bind:value={lineLimit} class="border border-border bg-surface px-2 py-1 text-sm text-text">
						<option value="200">200</option>
						<option value="400">400</option>
						<option value="800">800</option>
						<option value="1500">1500</option>
					</select>
				</label>
				<label class="flex items-center gap-2 text-text-muted">
					<input type="checkbox" bind:checked={autoRefresh} />
					Auto refresh
				</label>
				<label class="flex items-center gap-2 text-text-muted">
					<input type="checkbox" bind:checked={wrapLines} />
					Wrap lines
				</label>
				<button
					type="button"
					onclick={() => void refreshNow()}
					class="border border-border px-3 py-1.5 text-text transition-colors hover:bg-surface disabled:opacity-50"
					disabled={refreshingSources || refreshingContent}
				>
					Refresh
				</button>
			</div>
		</div>

		{#if error}
			<StatusBanner message={error} variant="error" />
		{/if}

		<div class="mt-4 grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
			<div class="border border-border bg-surface">
				<div class="border-b border-border px-4 py-3 text-sm font-medium text-text">Sources</div>
				{#if initialLoading && sources.length === 0}
					<div class="px-4 py-4 text-sm text-text-muted">Loading log sources…</div>
				{:else}
					<div class="flex flex-col">
						{#each sources as source}
							<button
								type="button"
								onclick={() => {
									if (source.available) selectedSourceId = source.id;
								}}
								disabled={!source.available}
								class="border-b border-border px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 {selectedSourceId === source.id ? 'bg-bg' : 'hover:bg-bg'}"
							>
								<div class="flex items-center justify-between gap-2">
									<div class="text-sm font-medium text-text">{source.label}</div>
									{#if source.available}
										<span class="text-[11px] text-text-muted">{formatBytes(source.size_bytes)}</span>
									{:else}
										<span class="text-[11px] text-text-muted">Unavailable</span>
									{/if}
								</div>
								<div class="mt-1 text-xs text-text-muted">{source.description}</div>
								{#if source.available}
									<div class="mt-2 truncate text-[11px] text-text-muted">{source.path}</div>
									<div class="mt-1 text-[11px] text-text-muted">Updated {formatTimestamp(source.updated_at)}</div>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<div class="border border-border bg-surface">
				<div class="border-b border-border px-4 py-3">
					{#if selectedLog}
						<div class="flex flex-wrap items-start justify-between gap-3">
							<div>
								<div class="text-sm font-medium text-text">{selectedLog.label}</div>
								<div class="mt-1 text-xs text-text-muted">{selectedLog.description}</div>
								<div class="mt-2 text-[11px] text-text-muted">{selectedLog.path}</div>
							</div>
							<div class="text-right text-[11px] text-text-muted">
								<div>{formatBytes(selectedLog.size_bytes)}</div>
								<div>Updated {formatTimestamp(selectedLog.updated_at)}</div>
								{#if refreshingContent || refreshingSources}
									<div class="mt-1 text-primary">Refreshing…</div>
								{/if}
							</div>
						</div>
					{:else}
						<div class="text-sm font-medium text-text">Log Output</div>
						<div class="mt-1 text-xs text-text-muted">Select an available source to inspect its logs.</div>
					{/if}
				</div>

				{#if selectedLog}
					<div class="border-b border-border px-4 py-3">
						<div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
							<input
								type="text"
								bind:value={searchQuery}
								placeholder="Search message text, error names, part IDs, camera names…"
								class="border border-border bg-bg px-3 py-2 text-sm text-text"
							/>
							<select bind:value={levelFilter} class="border border-border bg-bg px-3 py-2 text-sm text-text">
								<option value="all">All levels</option>
								<option value="ERROR">Errors only</option>
								<option value="WARN">Warnings only</option>
								<option value="INFO">Info only</option>
								<option value="DEBUG">Debug only</option>
								<option value="OTHER">Other / raw only</option>
							</select>
						</div>

						<div class="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
							<span class="rounded border border-border bg-bg px-2 py-1">{filteredEntries().length} matching lines</span>
							<span class="rounded border border-[#D01012]/30 bg-[#D01012]/10 px-2 py-1 text-[#D01012]">Errors: {countByLevel('ERROR')}</span>
							<span class="rounded border border-[#F2A900]/30 bg-[#F2A900]/10 px-2 py-1 text-[#A56D00]">Warnings: {countByLevel('WARN')}</span>
							<span class="rounded border border-primary/30 bg-primary/10 px-2 py-1 text-primary">Info: {countByLevel('INFO')}</span>
						</div>
					</div>

					<div class="max-h-[70vh] overflow-auto bg-bg">
						{#if filteredEntries().length === 0}
							<div class="px-4 py-4 text-sm text-text-muted">No log lines match the current filters.</div>
						{:else}
							<div class="min-w-full">
								{#each filteredEntries() as entry (entry.index + ':' + entry.raw)}
									<div class="grid gap-2 border-b border-border px-4 py-2 text-xs leading-5 {wrapLines ? '' : 'grid-cols-[110px_70px_minmax(0,1fr)]'}">
										<div class="font-mono text-text-muted">{entry.timestamp ?? ''}</div>
										<div>
											<span class={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${levelBadgeClass(entry.level)}`}>
												{entry.level}
											</span>
										</div>
										<div class={`font-mono text-text ${wrapLines ? 'whitespace-pre-wrap break-words' : 'overflow-x-auto whitespace-pre'}`}>
											{entry.message}
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{:else}
					<div class="px-4 py-4 text-sm text-text-muted">No log source selected.</div>
				{/if}
			</div>
		</div>
	</div>
</div>
