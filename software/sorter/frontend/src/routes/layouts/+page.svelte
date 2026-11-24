<script lang="ts">
	import { onMount } from 'svelte';
	import AppShell from '$lib/components/AppShell.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import { pictures, type Fit } from '$lib/components/pieces/layouts/fit.svelte';
	import { bestShot, loadPieces, type PieceView } from '$lib/components/pieces/layouts/model';
	import PageColumns from '$lib/components/pieces/layouts/PageColumns.svelte';
	import PageCompare from '$lib/components/pieces/layouts/PageCompare.svelte';
	import PageRide from '$lib/components/pieces/layouts/PageRide.svelte';
	import RowBand from '$lib/components/pieces/layouts/RowBand.svelte';
	import RowCompare from '$lib/components/pieces/layouts/RowCompare.svelte';
	import RowDense from '$lib/components/pieces/layouts/RowDense.svelte';
	import RowRide from '$lib/components/pieces/layouts/RowRide.svelte';
	import Slot from '$lib/components/pieces/layouts/Slot.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { fetchLegoColors } from '$lib/pieces';

	// Layouts to choose between, drawn from the machine's newest pieces: the
	// card of a piece in the records, and a piece's own page. Nothing here
	// saves anything. The one that is chosen replaces what the records and the
	// piece's page have now, and this page goes.
	const ctx = getMachineContext();
	const base = () => machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();

	const ROWS = [
		{
			name: 'A. Compare',
			why: 'The camera’s picture and Brickognize’s side by side at one size: the two a reviewer looks between. Every other picture is small, on one line, each channel always in the same place.',
			row: RowCompare
		},
		{
			name: 'B. Picture band',
			why: 'Every picture once, at one size, across the row, with Brickognize’s first. What was decided and the review share one line under it.',
			row: RowBand
		},
		{
			name: 'C. Ride',
			why: 'Left to right as the piece rode through the machine: C2, C3, the classification channel, then what it was taken for.',
			row: RowRide
		},
		{
			name: 'D. Dense',
			why: 'A third of the height, for going through many pieces: one picture, the part, the answer buttons, and every picture in a small block.',
			row: RowDense
		}
	];

	const PAGES = [
		{ value: 'compare', label: 'A. Compare' },
		{ value: 'ride', label: 'B. Ride' },
		{ value: 'columns', label: 'C. Two columns' }
	];
	const PAGE_WHY: Record<string, string> = {
		compare:
			'The camera’s picture and Brickognize’s large and at one size; what was decided and the review in a column beside them. Click any picture under them to put it in the large place.',
		ride: 'The piece’s ride left to right in five columns: what each channel saw and when, what it was taken for, and where it went. The review sits beside the predictions.',
		columns:
			'The pictures keep the left column and stay in sight while the right one is read: what was decided, the review, the predictions.'
	};

	let view = $state<'card' | 'page'>('card');
	let pageLayout = $state('compare');
	let pieces = $state<PieceView[]>([]);
	let status = $state<'loading' | 'ok' | 'failed'>('loading');
	let chosen = $state<string | null>(null);

	// For the page layouts: a piece with pictures from every channel, when there is one.
	const piece = $derived(
		pieces.find((p) => p.uuid === chosen) ??
			pieces.find((p) => new Set(p.shots.map((shot) => shot.channel)).size === 3) ??
			pieces[0] ??
			null
	);

	onMount(async () => {
		await fetchLegoColors(base()).catch(() => {});
		try {
			pieces = await loadPieces(base(), 6);
			status = 'ok';
		} catch {
			status = 'failed';
		}
	});
</script>

<svelte:head>
	<title>Layouts - Sorter</title>
</svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-[1600px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader
			title="Layouts"
			description="Ways to lay out a piece's card in the records and a piece's page, drawn from this machine's newest pieces. The buttons answer but save nothing."
		/>

		<div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
			<Tabs
				label="What to lay out"
				bind:value={view}
				items={[
					{ value: 'card', label: 'Card in the records' },
					{ value: 'page', label: "A piece's page" }
				]}
			/>
			<label class="flex items-center gap-3 text-sm text-ink-muted">
				A picture in its slot
				<SegmentedControl
					label="How a picture sits in its slot"
					size="sm"
					value={pictures.fit}
					options={[
						{ value: 'fill', label: 'Fills it' },
						{ value: 'tile', label: 'Whole, on a tile' },
						{ value: 'bare', label: 'Whole, bare' }
					]}
					onchange={(fit) => (pictures.fit = fit as Fit)}
				/>
			</label>
		</div>

		{#if status === 'loading'}
			<Panel>
				<div class="flex items-center gap-3 text-sm text-ink-muted">
					<Spinner size={14} /> Loading the newest pieces
				</div>
			</Panel>
		{:else if status === 'failed' || pieces.length === 0}
			<Alert tone="warning" title="No pieces to draw the layouts from">
				The machine did not answer, or it has no identified pieces with pictures yet.
			</Alert>
		{:else if view === 'card'}
			{#each ROWS as layout (layout.name)}
				<section class="flex flex-col gap-2">
					<div class="flex flex-col gap-0.5">
						<h2 class="text-base font-semibold text-ink">{layout.name}</h2>
						<p class="max-w-4xl text-sm text-ink-muted">{layout.why}</p>
					</div>
					<Panel flush>
						<div class="divide-y divide-line">
							{#each pieces as p (p.uuid)}
								<layout.row piece={p} />
							{/each}
						</div>
					</Panel>
				</section>
			{/each}
		{:else if piece}
			<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
				<SegmentedControl label="The page's layout" bind:value={pageLayout} options={PAGES} />
				<div class="flex items-center gap-3 text-sm text-ink-muted">
					Piece
					<span class="flex items-center gap-1.5">
						{#each pieces as p (p.uuid)}
							{@const shot = bestShot(p)}
							{#if shot}
								<Slot
									{shot}
									size={2.25}
									fit="fill"
									mark={false}
									selected={p.uuid === piece.uuid}
									onpick={() => (chosen = p.uuid)}
								/>
							{/if}
						{/each}
					</span>
				</div>
			</div>
			<p class="max-w-4xl text-sm text-ink-muted">{PAGE_WHY[pageLayout]}</p>

			<header class="flex flex-wrap items-center gap-x-4 gap-y-2">
				<h1 class="text-xl font-semibold tracking-tight text-ink">
					Piece {piece.uuid.slice(0, 8)}
				</h1>
				<PieceStatusBadge status={piece.summary.classification_status} />
				<a href={`/tracked/${piece.uuid}`} class="text-sm text-ink-muted hover:underline">
					Its page as it is now
				</a>
			</header>
			{#key piece.uuid}
				{#if pageLayout === 'compare'}
					<PageCompare {piece} />
				{:else if pageLayout === 'ride'}
					<PageRide {piece} />
				{:else}
					<PageColumns {piece} />
				{/if}
			{/key}
		{/if}
	</div>
</AppShell>
