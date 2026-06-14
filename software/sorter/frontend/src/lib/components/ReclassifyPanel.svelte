<script lang="ts">
	import { Check, FlaskConical } from 'lucide-svelte';
	import { Button } from '$lib/components/primitives';
	import Spinner from '$lib/components/Spinner.svelte';

	// Scratch / ephemeral Brickognize re-classification. Pick a subset of a
	// piece's crops and run them back through Brickognize purely for testing —
	// the backend records NOTHING and this has no effect on sorting. Self-
	// contained: owns its own selection + request state, talks to
	// POST /api/classify/retry.
	type CandidateImage = {
		image: string; // base64 (with or without data: prefix)
		label: string;
		used?: boolean;
		score?: number | null;
		source?: string;
	};
	type RetryItem = { id: string; name: string; category?: string; score: number; img_url?: string };
	type RetryColor = { id: string; name: string; score?: number };
	type RetryResult = {
		n_images: number;
		items: RetryItem[];
		colors: RetryColor[];
		best_item: RetryItem | null;
		best_color: RetryColor | null;
	};

	const MAX_IMAGES = 8;

	let {
		images,
		endpointBase
	}: {
		images: CandidateImage[];
		endpointBase: string;
	} = $props();

	// Default selection mirrors the real call: the crops that were actually
	// shipped (used). Selection is by index into `images`.
	let selected = $state<Set<number>>(
		new Set(images.map((img, i) => (img.used ? i : -1)).filter((i) => i >= 0))
	);
	let running = $state(false);
	let error = $state<string | null>(null);
	let result = $state<RetryResult | null>(null);

	function srcOf(img: CandidateImage): string {
		return img.image.startsWith('data:') ? img.image : `data:image/jpeg;base64,${img.image}`;
	}

	function toggle(i: number) {
		const next = new Set(selected);
		if (next.has(i)) next.delete(i);
		else next.add(i);
		selected = next;
	}

	const selectedCount = $derived(selected.size);
	const overLimit = $derived(selectedCount > MAX_IMAGES);

	async function run() {
		if (selectedCount === 0 || overLimit) return;
		running = true;
		error = null;
		result = null;
		try {
			const payload = [...selected].sort((a, b) => a - b).map((i) => images[i].image);
			const res = await fetch(`${endpointBase}/api/classify/retry`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ images: payload })
			});
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			result = (await res.json()) as RetryResult;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'request failed';
		} finally {
			running = false;
		}
	}
</script>

<div class="border border-warning/40 bg-warning/[0.06]">
	<div class="flex flex-wrap items-center gap-2 border-b border-warning/40 px-3 py-2">
		<FlaskConical size={14} class="text-warning" />
		<span class="text-sm font-semibold text-text">Scratch reclassify</span>
		<span class="text-xs text-text-muted">
			testing only — not recorded, no effect on sorting
		</span>
		<span class="ml-auto flex items-center gap-2">
			<span class="text-xs tabular-nums {overLimit ? 'text-danger' : 'text-text-muted'}">
				{selectedCount}/{MAX_IMAGES} selected
			</span>
			<Button
				variant="secondary"
				size="sm"
				onclick={run}
				disabled={running || selectedCount === 0 || overLimit}
				loading={running}
			>
				Run Brickognize
			</Button>
		</span>
	</div>

	<div class="p-3">
		{#if images.length === 0}
			<div class="text-sm text-text-muted">No images available to test.</div>
		{:else}
			<div class="flex flex-wrap gap-2">
				{#each images as img, i (i)}
					{@const isSel = selected.has(i)}
					<button
						type="button"
						onclick={() => toggle(i)}
						class="relative flex flex-col bg-white text-left {isSel
							? 'border-2 border-primary'
							: 'border border-border opacity-70 hover:opacity-100'}"
						title={img.label}
					>
						<div class="h-24 w-24 bg-white">
							<img src={srcOf(img)} alt={img.label} class="h-full w-full object-contain" loading="lazy" />
						</div>
						{#if isSel}
							<span class="absolute right-1 top-1 flex items-center justify-center bg-primary p-0.5 text-white">
								<Check size={12} />
							</span>
						{/if}
						<div class="border-t border-border px-1.5 py-1 text-xs text-text-muted">
							<span class="block truncate">{img.label}</span>
						</div>
					</button>
				{/each}
			</div>
			{#if overLimit}
				<div class="mt-2 text-xs text-danger">
					Brickognize accepts at most {MAX_IMAGES} images — deselect {selectedCount - MAX_IMAGES}.
				</div>
			{/if}
		{/if}

		{#if error}
			<div class="mt-3 border border-danger/40 bg-danger/[0.06] px-3 py-2 text-sm text-danger">
				{error}
			</div>
		{/if}

		{#if result}
			<div class="mt-3 border border-border bg-surface p-3">
				<div class="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
					Result · {result.n_images} image{result.n_images === 1 ? '' : 's'} sent
				</div>
				{#if result.best_item}
					<div class="flex items-start gap-3">
						{#if result.best_item.img_url}
							<img
								src={result.best_item.img_url.startsWith('http')
									? result.best_item.img_url
									: `https:${result.best_item.img_url}`}
								alt={result.best_item.name}
								class="h-16 w-16 flex-shrink-0 border border-border bg-white object-contain"
								loading="lazy"
							/>
						{/if}
						<div class="flex min-w-0 flex-col gap-0.5 text-sm">
							<span class="font-mono font-semibold text-text">{result.best_item.id}</span>
							<span class="text-text">{result.best_item.name}</span>
							<span class="tabular-nums text-text-muted">
								{(result.best_item.score * 100).toFixed(0)}% match{#if result.best_color}
									· {result.best_color.name}{/if}
							</span>
						</div>
					</div>
					{#if result.items.length > 1}
						<div class="mt-2 flex flex-col gap-0.5 text-xs text-text-muted">
							{#each result.items.slice(1, 5) as it (it.id)}
								<span class="tabular-nums">
									{(it.score * 100).toFixed(0)}% · <span class="font-mono">{it.id}</span>
									{it.name}
								</span>
							{/each}
						</div>
					{/if}
				{:else}
					<div class="text-sm text-text-muted">No items returned (not recognized).</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
