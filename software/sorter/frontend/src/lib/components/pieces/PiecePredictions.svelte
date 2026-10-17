<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import {
		findLegoColor,
		type PiecePrediction,
		type PredictionAnswer,
		type PredictionImage
	} from '$lib/pieces';

	// Every prediction made for a piece, by source: what the machine's own
	// requests said while sorting, then each later run over the piece's
	// stored images. Each request shows its provider and model, its top part
	// and color answers with scores, which one the piece took, and the images
	// it saw. `imageSrc` resolves an image the page has loaded; one it has
	// not (aged out) is named instead.
	let {
		predictions,
		imageSrc,
		onZoom
	}: {
		predictions: PiecePrediction[];
		imageSrc: (image: PredictionImage) => string | null;
		onZoom: (src: string, label: string) => void;
	} = $props();

	// How many answers of each kind a request shows.
	const SHOWN = 3;
	const KINDS: { kind: string; label: string }[] = [
		{ kind: 'part', label: 'Part' },
		{ kind: 'color', label: 'Color' }
	];
	const PROVIDERS: Record<string, string> = {
		brickognize: 'Brickognize',
		hive_basically: 'basically color model'
	};
	const LIVE_REQUESTS: Record<string, string> = {
		combined: 'Combined (fused set)',
		single_burst: 'Single burst frame'
	};

	const groups = $derived.by(() => {
		const out: { source: string; at: number | null; predictions: PiecePrediction[] }[] = [];
		for (const p of predictions) {
			let group = out.find((g) => g.source === p.source);
			if (!group) {
				group = { source: p.source, at: p.created_at, predictions: [] };
				out.push(group);
			}
			group.predictions.push(p);
		}
		return out;
	});

	function sourceLabel(source: string): string {
		return source === 'live' ? 'While sorting' : source;
	}

	function requestLabel(p: PiecePrediction): string {
		if (p.source === 'live' && LIVE_REQUESTS[p.request]) return LIVE_REQUESTS[p.request];
		return p.model_name ?? p.request;
	}

	function answersOf(p: PiecePrediction, kind: string): PredictionAnswer[] {
		return p.answers.filter((a) => a.kind === kind).slice(0, SHOWN);
	}

	function percent(score: number | null): string {
		return score == null || !Number.isFinite(score) ? '' : `${Math.round(score * 100)}%`;
	}

	// The same numbering as the piece's image panels: "Burst 3", "Link 1".
	function imageLabel(image: PredictionImage): string {
		const set = image.set === 'link' ? 'Link' : 'Burst';
		const channel = image.channel != null ? ` (C${image.channel})` : '';
		return `${set} ${image.seq + 1}${channel}`;
	}

	function formatWhen(ts: number | null): string {
		return ts ? new Date(ts * 1000).toLocaleString() : '';
	}
</script>

<Panel
	title="Predictions"
	description="{predictions.length} request{predictions.length === 1
		? ''
		: 's'} from {groups.length} source{groups.length === 1 ? '' : 's'}."
	flush
>
	<div class="divide-y divide-line">
		{#each groups as group (group.source)}
			<section>
				<div class="flex flex-wrap items-baseline gap-x-3 px-(--pad-panel) pt-2.5">
					<h3 class="text-sm font-semibold text-ink">{sourceLabel(group.source)}</h3>
					{#if group.at}<span class="text-xs text-ink-muted">{formatWhen(group.at)}</span>{/if}
				</div>
				<ul class="divide-y divide-line">
					{#each group.predictions as p (p.request)}
						<!-- One request on one line where there is room: who asked, what it said
							for the part and the color, and the images it saw. -->
						<li class="@container px-(--pad-panel) py-2.5">
							<div
								class="grid items-start gap-x-6 gap-y-2 @4xl:grid-cols-[13rem_minmax(0,1fr)_minmax(0,1fr)_19rem]"
							>
								<div class="flex min-w-0 flex-col text-sm">
									<span class="truncate font-medium text-ink">{requestLabel(p)}</span>
									<span class="flex items-baseline gap-2 text-xs text-ink-muted">
										<span class="truncate">{PROVIDERS[p.provider] ?? p.provider}</span>
										{#if p.model_sha}
											<span class="shrink-0 font-mono" title={p.model_sha}
												>{p.model_sha.slice(0, 8)}</span
											>
										{/if}
									</span>
								</div>

								{#each KINDS as { kind, label } (kind)}
									{@const answers = answersOf(p, kind)}
									<div class="flex min-w-0 flex-col gap-0.5">
										{#if answers.length > 0}
											<div class="label">{label}</div>
											<ol class="flex flex-col gap-0.5 text-sm">
												{#each answers as a (a.rank)}
													<li class="flex min-w-0 items-center gap-2">
														{#if kind === 'color'}
															<ColorChip
																name={a.value_name ?? a.value_id}
																rgb={findLegoColor(a.value_id, a.value_name)?.hex ?? null}
																class="min-w-0 text-ink"
															/>
														{:else}
															<span class="font-mono text-ink">{a.value_id}</span>
															{#if a.value_name}<span class="truncate text-ink-muted"
																	>{a.value_name}</span
																>{/if}
														{/if}
														<span class="num ml-auto shrink-0 text-ink-muted"
															>{percent(a.score)}</span
														>
														{#if a.applied}
															<span title="The piece took this answer"
																><Badge tone="primary">Applied</Badge></span
															>
														{/if}
													</li>
												{/each}
											</ol>
										{/if}
									</div>
								{/each}

								<div class="flex flex-wrap items-center gap-1">
									<span class="mr-1 text-xs text-ink-muted">Saw</span>
									{#if p.images === null}
										<span class="text-xs text-ink-muted">Not recorded</span>
									{:else if p.images.length === 0}
										<span class="text-xs text-ink-muted">No stored images</span>
									{:else}
										{#each p.images as image (`${image.set}|${image.seq}`)}
											{@const src = imageSrc(image)}
											{#if src}
												<ImageZoom {src} label={imageLabel(image)}>
													<button
														type="button"
														class="rounded-item p-0.5 transition-colors hover:bg-hover"
														aria-label={imageLabel(image)}
														onclick={() => onZoom(src, imageLabel(image))}
													>
														<img
															{src}
															alt=""
															class="size-8 rounded-item object-contain"
															loading="lazy"
														/>
													</button>
												</ImageZoom>
											{:else}
												<span title="This image is no longer on the machine"
													><Badge>{imageLabel(image)}</Badge></span
												>
											{/if}
										{/each}
									{/if}
								</div>
							</div>
						</li>
					{/each}
				</ul>
			</section>
		{/each}
	</div>
</Panel>
