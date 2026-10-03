<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import FlaskConical from '@lucide/svelte/icons/flask-conical';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';

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

<section class="rounded-control bg-well p-3">
	<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
		<h3 class="flex items-center gap-2 text-sm font-semibold text-ink">
			<FlaskConical size={16} />
			Scratch reclassify
		</h3>
		<Badge tone="warning">Testing only</Badge>
		<span class="text-sm text-ink-muted">Not recorded, and no effect on sorting.</span>
		<span class="ml-auto flex items-center gap-3">
			<span class="num text-sm {overLimit ? 'text-danger-ink' : 'text-ink-muted'}">
				{selectedCount} of {MAX_IMAGES} selected
			</span>
			<Button
				size="sm"
				onclick={run}
				disabled={running || selectedCount === 0 || overLimit}
				loading={running}
			>
				Run Brickognize
			</Button>
		</span>
	</div>

	{#if images.length === 0}
		<p class="mt-3 text-sm text-ink-muted">No images are available to test.</p>
	{:else}
		<div class="mt-3 flex flex-wrap gap-2">
			{#each images as img, i (i)}
				{@const isSel = selected.has(i)}
				<button
					type="button"
					onclick={() => toggle(i)}
					aria-pressed={isSel}
					class="relative flex flex-col gap-1 rounded-control p-1 text-left transition-colors {isSel
						? 'bg-primary-soft'
						: 'opacity-70 hover:bg-hover hover:opacity-100'}"
					title={img.label}
				>
					<img src={srcOf(img)} alt={img.label} class="size-24 rounded-item object-contain" loading="lazy" />
					{#if isSel}
						<span class="absolute top-2 right-2 rounded-badge bg-primary p-0.5 text-on-primary">
							<Check size={12} />
						</span>
					{/if}
					<span class="block max-w-24 truncate text-xs text-ink-muted">{img.label}</span>
				</button>
			{/each}
		</div>
		{#if overLimit}
			<p class="mt-2 text-sm text-danger-ink">
				Brickognize accepts at most {MAX_IMAGES} images. Deselect {selectedCount - MAX_IMAGES}.
			</p>
		{/if}
	{/if}

	{#if error}<Alert tone="danger" class="mt-3">{error}</Alert>{/if}

	{#if result}
		<div class="mt-3 border-t border-line pt-3">
			<div class="label mb-2">
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
							class="size-16 shrink-0 rounded-item object-contain"
							loading="lazy"
						/>
					{/if}
					<div class="flex min-w-0 flex-col gap-0.5 text-sm">
						<span class="font-mono font-semibold text-ink">{result.best_item.id}</span>
						<span class="text-ink">{result.best_item.name}</span>
						<span class="num text-ink-muted">
							{(result.best_item.score * 100).toFixed(0)}% match{#if result.best_color}
								· {result.best_color.name}{/if}
						</span>
					</div>
				</div>
				{#if result.items.length > 1}
					<ul class="mt-2 flex flex-col gap-0.5 text-sm text-ink-muted">
						{#each result.items.slice(1, 5) as it (it.id)}
							<li class="num">
								{(it.score * 100).toFixed(0)}% · <span class="font-mono">{it.id}</span>
								{it.name}
							</li>
						{/each}
					</ul>
				{/if}
			{:else}
				<p class="text-sm text-ink-muted">No items were returned: the piece was not recognized.</p>
			{/if}
		</div>
	{/if}
</section>
