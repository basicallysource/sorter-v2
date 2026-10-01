<!--
	"Where would a piece go?" on a profile's page: a part (a BrickLink ID or a
	Rebrickable number) and, if wanted, a color, asked of the version on the
	page. Each answer is the part as a PartTile and the bin it lands in, with
	why: a rule took it, a kit still needs it, the fallback sent it, or
	nothing did. The pieces asked about stay in the box and are asked again
	(in one call) whenever the page shows another version, so someone changing
	the profile can keep a few pieces in view and watch their bins move.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import {
		api,
		type ProfileCatalogColor,
		type RoutePiece,
		type RouteResult
	} from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import ProfileBin, { type Bin } from '$lib/components/ProfileBin.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import ColorSelect from './ColorSelect.svelte';
	import PartSearch from './PartSearch.svelte';
	import CornerDownRight from '@lucide/svelte/icons/corner-down-right';
	import Search from '@lucide/svelte/icons/search';
	import X from '@lucide/svelte/icons/x';

	let {
		profileId,
		versionId,
		destination,
		onshow
	}: {
		profileId: string;
		// The version the page shows.
		versionId: string;
		// The bin a category is, and its place in the order when it is a rule's.
		destination: (categoryId: string, name: string) => { bin: Bin; number?: number };
		// Show that bin in the page's list.
		onshow: (categoryId: string) => void;
	} = $props();

	type Check = { key: number; piece: RoutePiece; result: RouteResult };

	let part = $state('');
	let colorId = $state<number | null>(null);
	let colors = $state<ProfileCatalogColor[]>([]);
	let checks = $state<Check[]>([]);
	let checking = $state(false);
	let error = $state<string | null>(null);
	let finding = $state(false);
	let partField = $state<HTMLInputElement>();
	let counter = 0;

	$effect(() => {
		void api
			.getProfileCatalogColors()
			.then((res) => (colors = res.results))
			.catch(() => (colors = []));
	});

	function sameAs(a: RoutePiece, b: RoutePiece) {
		return a.part === b.part && (a.color_id ?? null) === (b.color_id ?? null);
	}

	async function check(text: string) {
		const wanted = text.trim();
		if (!wanted || checking) return;
		const piece: RoutePiece = colorId === null ? { part: wanted } : { part: wanted, color_id: colorId };
		checking = true;
		error = null;
		try {
			const { results } = await api.routePieces({
				profile_id: profileId,
				version_id: versionId,
				pieces: [piece]
			});
			const result = results[0];
			if (result) {
				checks = [{ key: ++counter, piece, result }, ...checks.filter((c) => !sameAs(c.piece, piece))].slice(0, 8);
			}
		} catch (e: any) {
			error = e.error || 'Could not check that piece.';
		} finally {
			checking = false;
			partField?.select();
		}
	}

	function onPartKey(event: KeyboardEvent) {
		if (event.key !== 'Enter') return;
		event.preventDefault();
		void check(part);
	}

	function found(picked: { part_num: string; external_ids?: Record<string, unknown> }) {
		const ids = picked.external_ids?.BrickLink;
		part = Array.isArray(ids) && ids.length > 0 ? String(ids[0]) : picked.part_num;
		finding = false;
		void check(part);
	}

	// Another version on the page: ask again about every piece in the box.
	let asked: string | null = null;
	$effect(() => {
		const version = versionId;
		if (asked === null) {
			asked = version;
			return;
		}
		if (asked === version) return;
		asked = version;
		untrack(() => void askAgain(version));
	});

	async function askAgain(version: string) {
		if (checks.length === 0) return;
		const current = checks;
		try {
			// Each piece is asked about on its own: no kit fills from the others.
			const { results } = await api.routePieces({
				profile_id: profileId,
				version_id: version,
				pieces: current.map((c) => c.piece),
				fill_kits: false
			});
			// Only if the box did not change while the answer came.
			if (current === checks && asked === version) {
				checks = current.map((c, i) => ({ ...c, result: results[i] ?? c.result }));
			}
		} catch {
			/* the old answers stay, marked by the version they came from */
		}
	}

	function reason(result: RouteResult): string {
		switch (result.why) {
			case 'rule':
				return 'The first rule that takes it.';
			case 'kit':
				return result.kit_left != null ? `A kit that still takes ${result.kit_left.toLocaleString('en-US')} of it.` : 'A kit that still needs it.';
			case 'fallback':
				return 'No rule takes it, so the fallback sends it here.';
			default:
				return 'No rule takes it, and the fallback has no category for it.';
		}
	}
</script>

<Panel
	title="Where would a piece go?"
	description="Type a part and a color to see where it goes."
	flush
>
	{#snippet actions()}
		{#if checks.length > 0}
			<Button size="sm" variant="ghost" onclick={() => (checks = [])}>Clear</Button>
		{/if}
	{/snippet}

	<div class="flex flex-col gap-3 px-(--pad-panel) pb-(--pad-panel)">
		<Field label="Part" for="route-part">
			<div class="flex items-center gap-2">
				<Input
					id="route-part"
					bind:value={part}
					bind:element={partField}
					class="flex-1"
					placeholder="BrickLink ID or part number, like 3001"
					autocomplete="off"
					spellcheck={false}
					onkeydown={onPartKey}
				/>
				<Button
					icon={Search}
					label={finding ? 'Close the part search' : 'Find a part by name'}
					onclick={() => (finding = !finding)}
				/>
			</div>
		</Field>
		{#if finding}
			<PartSearch title="Find a part" autofocus onSelect={found} onCancel={() => (finding = false)} />
		{/if}
		<Field
			label="Color"
			for="route-color"
			help="With no color, a rule that needs one does not take the piece."
		>
			<ColorSelect id="route-color" bind:value={colorId} {colors} emptyLabel="No color" />
		</Field>
		{#if error}<Alert tone="danger">{error}</Alert>{/if}
		<div>
			<Button variant="primary" loading={checking} disabled={!part.trim()} onclick={() => void check(part)}
				>Check</Button
			>
		</div>
	</div>

	{#if checks.length > 0}
		<ul class="divide-y divide-line border-t border-line">
			{#each checks as item (item.key)}
				{@const result = item.result}
				{@const where = destination(result.category_id, result.category_name)}
				<li class="relative flex flex-col gap-1 py-2">
					<PartTile
						name={result.known_part ? (result.part_name ?? result.part) : `No part called "${result.part}"`}
						imgUrl={result.img_url}
						bricklinkId={result.known_part ? result.bricklink_id : null}
						color={result.color ? { name: result.color.name, rgb: result.color.rgb } : null}
						class="pr-10"
					/>
					<Button
						size="sm"
						variant="ghost"
						icon={X}
						label="Remove this piece"
						class="absolute top-3 right-3"
						onclick={() => (checks = checks.filter((c) => c.key !== item.key))}
					/>
					<div class="flex items-center gap-2 px-(--pad-panel) text-sm text-ink-muted">
						<CornerDownRight size={14} class="shrink-0" />
						<span>{reason(result)}</span>
					</div>
					<ProfileBin
						layout="row"
						bin={where.bin}
						number={where.number}
						onclick={() => onshow(result.category_id)}
					/>
				</li>
			{/each}
		</ul>
	{/if}
</Panel>
