<!--
	"Where would a piece go?" Give a part (found by name or number, or an ID typed
	in) and, if it matters, a color, and this says which bin the draft sends it to
	and why: a rule or a kit takes it, the fallback sends it to its category, or
	nothing does and it lands in Everything else. It answers again as the draft
	changes.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import {
		api,
		type ProfileBin as BinData,
		type ProfileDocument,
		type ProfileCatalogSearchResult,
		type RouteResult
	} from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import ProfileBin from '$lib/components/ProfileBin.svelte';
	import ColorSelect from '$lib/components/profile/ColorSelect.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { catalog, bricklinkIdsOf } from './catalog.svelte';
	import PartPicker from './PartPicker.svelte';
	import type { Rule } from './rules';
	import ValueBox from './value/ValueBox.svelte';

	let {
		draft,
		draftKey,
		bins,
		rules,
		onselect
	}: {
		draft: ProfileDocument;
		draftKey: string;
		bins: Record<string, BinData>;
		rules: Rule[];
		// Show the rule a piece goes to.
		onselect: (ruleId: string) => void;
	} = $props();

	// What was asked: the part as given (an ID or a number), and its color.
	let part = $state<string | null>(null);
	let colorId = $state<number | null>(null);
	let result = $state.raw<RouteResult | null>(null);
	let busy = $state(false);
	let failed = $state<string | null>(null);
	let latest = 0;

	$effect(() => {
		void catalog.ensureColors();
	});

	$effect(() => {
		void draftKey;
		const asked = part;
		const color = colorId;
		const mine = ++latest;
		if (asked === null) {
			result = null;
			busy = false;
			failed = null;
			return;
		}
		busy = true;
		const timer = setTimeout(async () => {
			try {
				const res = await api.routePieces({
					document: untrack(() => draft),
					pieces: [{ part: asked, color_id: color }]
				});
				if (mine !== latest) return;
				result = res.results[0] ?? null;
				failed = null;
			} catch (e) {
				if (mine !== latest) return;
				failed = (e as { error?: string })?.error ?? 'The answer could not be worked out.';
			}
			busy = false;
		}, 300);
		return () => clearTimeout(timer);
	});

	function pick(found: ProfileCatalogSearchResult) {
		part = bricklinkIdsOf(found)[0] ?? found.part_num;
	}

	function typed(text: string) {
		if (text) part = text;
	}

	const destination = $derived.by((): BinData | null => {
		if (!result) return null;
		const known = bins[result.category_id];
		if (known) return known;
		return {
			name: result.category_name,
			kind: result.why === 'default' ? 'default' : result.why === 'fallback' ? 'fallback' : 'rule',
			part_count: null,
			samples: []
		};
	});

	// The same sentences the profile page's own check says.
	const reasons: Record<RouteResult['why'], string> = {
		rule: 'The first rule that takes it.',
		kit: 'A kit that still needs it.',
		fallback: 'No rule takes it, so the fallback sends it here.',
		default: 'No rule takes it, and the fallback has no category for it.'
	};
	const why = $derived.by(() => {
		if (!result) return '';
		if (!result.known_part) return 'The catalog has no such part, so nothing takes it.';
		if (result.why === 'kit' && result.kit_left != null) {
			return `A kit that still needs ${result.kit_left.toLocaleString('en-US')} more of it.`;
		}
		return reasons[result.why];
	});

	const isRule = $derived(result !== null && rules.some((rule) => rule.id === result!.category_id));
</script>

<section class="flex flex-col gap-3">
	<h3 class="label">Where would a piece go?</h3>

	{#if part === null}
		<ValueBox>
			<PartPicker
				label="Find a part to route"
				placeholder="Search a part, or type its ID and press Enter"
				onpick={pick}
				onenter={typed}
			/>
		</ValueBox>
	{:else}
		<div class="flex items-center gap-2">
			<div class="min-w-0 flex-1">
				{#if result}
					<PartTile
						padded={false}
						name={result.part_name ?? result.part}
						imgUrl={result.img_url}
						bricklinkId={result.known_part ? result.bricklink_id : null}
					/>
				{:else}
					<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} />Looking up {part}</p>
				{/if}
			</div>
			<Button variant="ghost" size="sm" icon={X} label="Try another part" onclick={() => (part = null)} />
		</div>
		<div class="flex flex-wrap items-center gap-2">
			<span class="text-sm text-ink-muted">In</span>
			<ColorSelect
				class="w-56"
				size="sm"
				label="The piece's color"
				colors={catalog.colors}
				emptyLabel="Any color"
				value={colorId}
				onchange={(next) => (colorId = next)}
			/>
		</div>
	{/if}

	{#if failed}
		<p class="text-sm text-danger-ink">{failed}</p>
	{:else if result && destination}
		<div class="flex flex-col gap-2 rounded-control bg-well p-3">
			<div class="flex items-center gap-2 text-sm text-ink">
				<span class="font-medium">Goes to</span>
				{#if busy}<Spinner size={14} class="text-ink-muted" />{/if}
			</div>
			<ProfileBin
				layout="row"
				plane="well"
				bin={destination}
				onclick={isRule ? () => onselect(result!.category_id) : undefined}
			/>
			<p class="text-sm text-ink-muted">{why}</p>
		</div>
	{/if}
</section>
