<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Input, Alert } from '$lib/components/primitives';

	let {
		initialUuid = '',
		autoShowAll = false,
		reloadToken = 0
	}: { initialUuid?: string; autoShowAll?: boolean; reloadToken?: number } = $props();

	type Candidate = {
		channel_id: number;
		ts: number;
		dt_s: number;
		score: number;
		bbox: number[];
		jpeg_b64: string;
	};

	type SearchResult = {
		anchor: {
			uuid: string;
			ref_ts: number;
			part_id: string | null;
			part_name: string | null;
			color_name: string | null;
			confidence: number | null;
			n_embeddings: number;
			embedding_method?: string;
			images: string[];
		};
		candidates: Candidate[];
		error?: string | null;
		stats: any;
	};

	let values = $state<Record<string, number | boolean>>({});
	let uuid = $state(initialUuid);
	let searching = $state(false);
	let searchError = $state<string | null>(null);
	let result = $state<SearchResult | null>(null);
	let loadedDefaults = $state(false);

	type Preset = { label: string; hint: string; patch: Record<string, number> };
	// Same-piece crops cluster high (~0.98), so the useful range sits near the
	// top — these presets sweep how aggressively we cut by similarity.
	const presets: Preset[] = [
		{ label: 'Strictest', hint: 'near-identical only', patch: { min_similarity: 0.97, max_results: 8 } },
		{ label: 'Strict', hint: 'high confidence', patch: { min_similarity: 0.93, max_results: 16 } },
		{ label: 'Loose', hint: 'more candidates', patch: { min_similarity: 0.85, max_results: 30 } },
		{ label: 'Show all', hint: 'no floor, ranked', patch: { min_similarity: 0.0, max_results: 50 } }
	];

	async function loadDefaults() {
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/upstream-match`);
			if (res.ok) {
				const d = await res.json();
				values = { ...d.config };
			}
		} catch {
			// keep whatever we have; search will still send current values
		}
		loadedDefaults = true;
	}

	async function runSearch() {
		if (!uuid.trim()) {
			searchError = 'Enter a piece UUID';
			return;
		}
		searching = true;
		searchError = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/upstream-match/search`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ uuid: uuid.trim(), ...values })
			});
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			result = await res.json();
		} catch (e: any) {
			searchError = e.message ?? 'Search failed';
			result = null;
		} finally {
			searching = false;
		}
	}

	function presetActive(p: Preset): boolean {
		return Object.entries(p.patch).every(([k, v]) => Number(values[k]) === v);
	}

	function applyPreset(p: Preset) {
		values = { ...values, ...p.patch };
		if (uuid.trim()) runSearch();
	}

	function channelLabel(ch: number): string {
		return ch === 2 ? 'C2' : ch === 3 ? 'C3' : `C${ch}`;
	}

	// Reload defaults when the parent bumps the token (e.g. after Save defaults).
	let prevToken = $state(-1);
	$effect(() => {
		const t = reloadToken;
		if (t === prevToken) return;
		prevToken = t;
		loadDefaults();
	});

	// One-time auto "Show all" when opened against a fixed piece.
	let didAuto = $state(false);
	$effect(() => {
		if (didAuto || !autoShowAll || !loadedDefaults) return;
		didAuto = true;
		if (uuid.trim()) {
			const showAll = presets.find((p) => p.label === 'Show all');
			if (showAll) values = { ...values, ...showAll.patch };
			runSearch();
		}
	});
</script>

<div class="flex flex-col gap-3">
	<div class="flex items-end gap-3">
		<div class="flex-1">
			<label class="mb-1 block text-sm text-text" for="um-uuid">Piece UUID</label>
			<Input id="um-uuid" type="text" bind:value={uuid} />
		</div>
		<Button variant="primary" onclick={runSearch} loading={searching}>Run search</Button>
	</div>

	<div class="flex flex-wrap items-center gap-2">
		<span class="text-sm text-text-muted">Filter:</span>
		{#each presets as p}
			<Button
				variant={presetActive(p) ? 'primary' : 'secondary'}
				size="sm"
				onclick={() => applyPreset(p)}
			>
				{p.label}<span class="ml-1.5 text-text-muted">≥{p.patch.min_similarity}</span>
			</Button>
		{/each}
	</div>

	{#if searchError}
		<Alert variant="danger">{searchError}</Alert>
	{/if}
	{#if result?.error}
		<Alert variant="warning">{result.error}</Alert>
	{/if}

	{#if result}
		<div class="mt-2 flex flex-col gap-4">
			<div class="flex flex-col gap-2">
				<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
					Anchor — {result.anchor.part_name ?? result.anchor.part_id ?? 'unclassified'}
					{#if result.anchor.color_name}({result.anchor.color_name}){/if}
					· {result.anchor.n_embeddings} ref crop(s) · ranked by {result.anchor.embedding_method ?? '—'}
				</div>
				{#if result.anchor.images.length}
					<div class="flex flex-wrap gap-2">
						{#each result.anchor.images as img}
							<div class="h-24 w-24 bg-white">
								<img
									src={`data:image/jpeg;base64,${img}`}
									alt="anchor"
									class="h-full w-full object-contain"
									loading="lazy"
								/>
							</div>
						{/each}
					</div>
				{:else}
					<div class="text-sm text-text-muted">No reference crops on this piece.</div>
				{/if}
			</div>

			<div class="flex flex-col gap-2">
				<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
					Candidates ({result.candidates.length})
				</div>
				{#if result.candidates.length === 0}
					<div class="text-sm text-text-muted">
						No upstream crops cleared the similarity floor in the time window.
					</div>
				{:else}
					<div
						class="grid gap-2"
						style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
					>
						{#each result.candidates as cand}
							<div class="flex flex-col border border-border bg-bg">
								<div class="aspect-square w-full bg-white">
									<img
										src={`data:image/jpeg;base64,${cand.jpeg_b64}`}
										alt="candidate"
										class="h-full w-full object-contain"
										loading="lazy"
									/>
								</div>
								<div class="flex items-center justify-between px-2 py-1.5 text-sm">
									<span class="font-semibold">{cand.score.toFixed(3)}</span>
									<span class="text-text-muted">
										{channelLabel(cand.channel_id)} · {cand.dt_s.toFixed(1)}s
									</span>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
