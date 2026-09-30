<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type Kit,
		type KitPartInput,
		type ProfileCatalogColor,
		type ProfileCatalogSearchResult
	} from '$lib/api';
	import { kitSource, plural } from '$lib/profile-display';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import KitPicture from '$lib/components/profile/KitPicture.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import Select from '$lib/components/Select.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import ColorSelect from '$lib/components/profile/ColorSelect.svelte';
	import PartSearch from '$lib/components/profile/PartSearch.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Boxes from '@lucide/svelte/icons/boxes';
	import Upload from '@lucide/svelte/icons/upload';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';

	// One line of a kit as it is edited: a part in a color, and how many.
	type Line = {
		key: number;
		part_num: string;
		part_source: string;
		bricklink_id: string | null;
		part_name: string | null;
		img_url: string | null;
		// The part's photo when img_url is a render in the line's color.
		fallback_img_url?: string | null;
		// Rebrickable color; null for any color.
		color_id: number | null;
		bricklink_color_id: number | null;
		color_name: string | null;
		rgb: string | null;
		quantity: number;
	};

	// Lines listed before "Show more".
	const PAGE = 100;

	// A line's part in its color: Rebrickable renders any part in any color at
	// this address (as Hive does for bins), so a new color shows at once. Its
	// photo is the fallback, for a part with no render and for any color.
	function photo(line: Line) {
		return line.fallback_img_url ?? line.img_url;
	}
	function picture(line: Line) {
		return line.part_source === 'rebrickable' && line.color_id != null
			? `https://cdn.rebrickable.com/media/parts/ldraw/${line.color_id}/${encodeURIComponent(line.part_num)}.png`
			: photo(line);
	}

	let loading = $state(true);
	let kit = $state<Kit | null>(null);
	let error = $state<string | null>(null);
	let colors = $state<ProfileCatalogColor[]>([]);
	let lines = $state<Line[]>([]);
	let baseline = $state('[]');
	let counter = 0;

	let adding = $state(false);
	// A new search box after each part added, so it is empty and ready for the next.
	let searchRound = $state(0);
	// Lines just added, tinted until the kit is saved.
	let fresh = $state<Set<number>>(new Set());
	let filter = $state('');
	let shown = $state(PAGE);
	let saving = $state(false);
	let saveProblems = $state<string[] | null>(null);
	let saved = $state(false);
	let importWarnings = $state<string[]>([]);

	let name = $state('');
	let description = $state('');
	let visibility = $state<'private' | 'unlisted' | 'public'>('private');
	let savingDetails = $state(false);
	let detailsSaved = $state(false);
	let detailsError = $state<string | null>(null);
	let uploading = $state(false);
	let pictureInput = $state<HTMLInputElement>();
	let showDeleteModal = $state(false);
	let deleting = $state(false);
	let deleteError = $state<string | null>(null);

	const kitId = $derived(page.params.id ?? '');
	const isOwner = $derived(kit?.is_owner ?? false);

	function inputOf(line: Line): KitPartInput {
		const base = { part: line.part_num, quantity: line.quantity };
		if (line.color_id !== null) return { ...base, color_id: line.color_id };
		if (line.bricklink_color_id !== null) return { ...base, bricklink_color_id: line.bricklink_color_id };
		return base;
	}

	function linesOf(k: Kit): Line[] {
		return k.parts.map((part) => ({ key: ++counter, ...part }));
	}

	function apply(k: Kit) {
		kit = k;
		lines = linesOf(k);
		baseline = JSON.stringify(lines.map(inputOf));
		fresh = new Set();
		name = k.name;
		description = k.description ?? '';
		visibility = k.visibility;
		// A new, empty kit opens on the part search: adding parts is its first job.
		if (k.is_owner && k.parts.length === 0) adding = true;
	}

	$effect(() => {
		const id = kitId;
		if (!id) return;
		loading = true;
		error = null;
		kit = null;
		adding = false;
		saved = false;
		api
			.getKit(id)
			.then((k) => {
				apply(k);
				// What the import from a BrickLink list left out, told once.
				try {
					const stored = sessionStorage.getItem(`kit-import:${id}`);
					if (stored) {
						const all: string[] = JSON.parse(stored);
						importWarnings = all.filter((w) => !k.warnings.includes(w));
					}
				} catch {
					/* nothing stored */
				}
			})
			.catch((e: any) => (error = e.error || 'Failed to load the kit'))
			.finally(() => (loading = false));
	});

	$effect(() => {
		void api
			.getProfileCatalogColors()
			.then((res) => (colors = res.results))
			.catch(() => (colors = []));
	});

	function dismissImportWarnings() {
		importWarnings = [];
		try {
			sessionStorage.removeItem(`kit-import:${kitId}`);
		} catch {
			/* nothing stored */
		}
	}

	const dirty = $derived(JSON.stringify(lines.map(inputOf)) !== baseline);
	const badQuantity = $derived(lines.some((l) => !Number.isInteger(l.quantity) || l.quantity < 1));
	const anyColorLines = $derived(lines.filter((l) => l.color_id === null && l.bricklink_color_id === null).length);
	const uncatalogued = $derived(lines.filter((l) => l.part_source === 'bricklink').length);
	const totals = $derived.by(() => {
		const colorsUsed = new Set(
			lines
				.filter((l) => l.color_id !== null || l.bricklink_color_id !== null)
				.map((l) => (l.color_id !== null ? `r${l.color_id}` : `b${l.bricklink_color_id}`))
		);
		return {
			parts: lines.length,
			colors: colorsUsed.size,
			pieces: lines.reduce((sum, l) => sum + (Number.isFinite(l.quantity) ? l.quantity : 0), 0)
		};
	});

	// Warnings the server gives that the page does not already say itself.
	const otherWarnings = $derived(
		(kit?.warnings ?? []).filter((w) => !/line\(s\) (have no color|are BrickLink parts)/.test(w))
	);

	const visibleLines = $derived.by(() => {
		const needle = filter.trim().toLowerCase();
		if (!needle) return lines;
		return lines.filter((l) =>
			[l.part_name, l.part_num, l.bricklink_id, l.color_name].some((v) => v?.toLowerCase().includes(needle))
		);
	});

	// A line's color as the catalog knows it. A part the catalog does not know
	// keeps its color as a BrickLink ID, which the catalog's colors map back.
	function catalogColor(line: Line): ProfileCatalogColor | null {
		if (line.color_id !== null) return colors.find((c) => c.id === line.color_id) ?? null;
		if (line.bricklink_color_id === null) return null;
		return colors.find((c) => c.bricklink_id === String(line.bricklink_color_id)) ?? null;
	}

	function setColor(line: Line, id: number | null) {
		const color = id === null ? null : colors.find((c) => c.id === id);
		line.color_id = id;
		line.color_name = id === null ? 'Any color' : (color?.name ?? null);
		line.rgb = color?.rgb ?? null;
		line.bricklink_color_id = color?.bricklink_id ? Number(color.bricklink_id) : null;
	}

	function setQuantity(line: Line, value: string | number | null) {
		const n = typeof value === 'number' ? value : Number(value);
		line.quantity = Number.isFinite(n) ? Math.trunc(n) : 0;
	}

	function removeLine(key: number) {
		lines = lines.filter((l) => l.key !== key);
		fresh.delete(key);
		saved = false;
	}

	// A part picked in the search becomes a line of one piece in any color, at
	// the top where it is seen; the color and the count are set on the line.
	function addPart(part: ProfileCatalogSearchResult) {
		saved = false;
		searchRound++;
		const ids = part.external_ids?.BrickLink;
		const existing = lines.find((l) => l.part_num === part.part_num && l.color_id === null && l.part_source === 'rebrickable');
		if (existing) {
			existing.quantity += 1;
			fresh = new Set([...fresh, existing.key]);
			return;
		}
		const line: Line = {
			key: ++counter,
			part_num: part.part_num,
			part_source: 'rebrickable',
			bricklink_id: Array.isArray(ids) && ids.length > 0 ? String(ids[0]) : null,
			part_name: part.name,
			img_url: part.part_img_url,
			color_id: null,
			bricklink_color_id: null,
			color_name: 'Any color',
			rgb: null,
			quantity: 1
		};
		lines = [line, ...lines];
		fresh = new Set([...fresh, line.key]);
		filter = '';
	}

	async function save() {
		if (!kit || saving || badQuantity) return;
		saving = true;
		saveProblems = null;
		saved = false;
		try {
			apply(await api.updateKit(kit.id, { parts: lines.map(inputOf) }));
			saved = true;
		} catch (e: any) {
			const details: unknown = e.details;
			saveProblems = [
				e.error || 'Could not save the kit.',
				...(Array.isArray(details) ? details.filter((d): d is string => typeof d === 'string') : [])
			];
		} finally {
			saving = false;
		}
	}

	function discard() {
		if (kit) apply(kit);
		saveProblems = null;
		saved = false;
	}

	async function saveDetails() {
		if (!kit || !name.trim()) return;
		savingDetails = true;
		detailsError = null;
		detailsSaved = false;
		try {
			const updated = await api.updateKit(kit.id, {
				name: name.trim(),
				description: description.trim() || null,
				visibility
			});
			// Only the details: lines being edited stay as they are.
			kit = { ...updated, parts: kit.parts };
			detailsSaved = true;
		} catch (e: any) {
			detailsError = e.error || 'Could not save the details.';
		} finally {
			savingDetails = false;
		}
	}

	async function changePicture(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !kit) return;
		uploading = true;
		detailsError = null;
		try {
			const { url } = await api.uploadProfileImage(file);
			const updated = await api.updateKit(kit.id, { image_url: url });
			kit = { ...updated, parts: kit.parts };
		} catch (e: any) {
			detailsError = e.error || 'Could not upload the picture.';
		} finally {
			uploading = false;
		}
	}

	async function deleteKit() {
		if (!kit) return;
		deleting = true;
		deleteError = null;
		try {
			await api.deleteKit(kit.id);
			goto('/kits');
		} catch (e: any) {
			deleteError = e.error || 'Could not delete the kit.';
		} finally {
			deleting = false;
		}
	}
</script>

<svelte:head><title>{kit ? `${kit.name} - Hive` : 'Kit - Hive'}</title></svelte:head>

<div>
	<Button href="/kits" size="sm" variant="ghost" icon={ArrowLeft}>Kits</Button>
</div>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if !kit}
	<Alert tone="danger">{error ?? 'Kit not found.'}</Alert>
{:else}
	<div class="flex items-start gap-4">
		<KitPicture src={kit.image_url} class="size-20 shrink-0 max-sm:size-14" />
		<div class="min-w-0 flex-1">
			<PageHeader title={kit.name} description={kit.description ?? undefined}>
				<div class="flex flex-col gap-1.5 text-sm text-ink-muted">
					<div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
						<span>{kitSource(kit)}</span>
						<span class="num"
							>{plural(totals.parts, 'part')} in {plural(totals.colors, 'color')}, {plural(totals.pieces, 'piece')}</span
						>
						{#if isOwner}
							<Badge>{sentence(kit.visibility)}</Badge>
						{:else}
							<span>By {kit.owner.display_name ?? kit.owner.github_login ?? 'unknown'}</span>
						{/if}
					</div>
					{#if isOwner}
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
							{#if kit.used_by.length === 0}
								<span>No profile uses this kit yet.</span>
							{:else}
								<span>Used by</span>
								{#each kit.used_by as use, i (use.profile_id)}
									<a href="/profiles/{use.profile_id}" class="text-primary-ink hover:underline"
										>{use.name}<span class="num ml-1 text-ink-muted">v{use.version_number}</span></a
									>{#if i < kit.used_by.length - 1},{/if}
								{/each}
							{/if}
						</div>
					{/if}
				</div>
			</PageHeader>
		</div>
	</div>

	{#if importWarnings.length > 0}
		<Alert tone="warning" title="Some rows of the list were not recognized">
			<ul class="flex max-h-48 flex-col gap-1 overflow-y-auto">
				{#each importWarnings as warning, i (i)}<li>{warning}</li>{/each}
			</ul>
			{#snippet actions()}
				<Button size="sm" variant="ghost" icon={X} label="Dismiss" onclick={dismissImportWarnings} />
			{/snippet}
		</Alert>
	{/if}

	{#each otherWarnings as warning, i (i)}
		<Alert tone="warning">{warning}</Alert>
	{/each}

	<Panel title="Parts" description={lines.length === 0 ? undefined : 'A part in a color, and how many pieces the kit wants.'} flush>
		{#snippet actions()}
			{#if isOwner}
				<Button icon={adding ? X : Plus} onclick={() => (adding = !adding)}>{adding ? 'Close' : 'Add a part'}</Button>
			{/if}
		{/snippet}

		{#if adding}
			<div class="px-(--pad-panel) pb-3">
				{#key searchRound}
					<PartSearch title="Add a part" autofocus onSelect={addPart} />
				{/key}
			</div>
		{/if}

		{#if anyColorLines > 0}
			<div class="px-(--pad-panel) pb-3">
				<Alert tone="warning" title="{plural(anyColorLines, 'part')} in any color">
					A piece of any color counts toward {anyColorLines === 1 ? 'this part' : 'these parts'}. Give
					{anyColorLines === 1 ? 'it' : 'each'} a color to collect exact pieces.
				</Alert>
			</div>
		{/if}
		{#if uncatalogued > 0}
			<div class="px-(--pad-panel) pb-3">
				<Alert tone="warning" title="{plural(uncatalogued, 'part')} not in the catalog">
					Hive does not know {uncatalogued === 1 ? 'this part' : 'these parts'}, so {uncatalogued === 1 ? 'it is' : 'they are'} collected by BrickLink ID.
					{#if isOwner}Saving the kit needs each one removed or replaced by a part Hive knows.{/if}
				</Alert>
			</div>
		{/if}

		{#if lines.length > 12}
			<div class="px-(--pad-panel) pb-3">
				<Input type="search" bind:value={filter} placeholder="Filter the parts" aria-label="Filter the parts" class="sm:w-72" />
			</div>
		{/if}

		{#if lines.length === 0}
			{#if !adding}
				<div class="px-(--pad-panel) pb-(--pad-panel)">
					<EmptyState icon={Boxes} title="No parts yet">
						{isOwner ? 'Search for a part and add it, then give it a color and a quantity.' : 'This kit has no parts.'}
						{#snippet action()}
							{#if isOwner}
								<Button variant="primary" icon={Plus} onclick={() => (adding = true)}>Add a part</Button>
							{/if}
						{/snippet}
					</EmptyState>
				</div>
			{/if}
		{:else if visibleLines.length === 0}
			<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">No part matches.</p>
		{:else}
			<ul class="divide-y divide-line border-t border-line">
				{#each visibleLines.slice(0, shown) as line (line.key)}
					<li class={fresh.has(line.key) ? 'bg-primary-soft' : ''}>
						{#if isOwner}
							<PartTile
								name={line.part_name ?? line.part_num}
								imgUrl={picture(line)}
								fallbackImgUrl={photo(line)}
								bricklinkId={line.bricklink_id}
								partNum={line.part_source === 'rebrickable' ? line.part_num : null}
							>
								{#if line.part_source === 'bricklink'}<Badge tone="warning">Not in the catalog</Badge>{/if}
								<ColorSelect
									value={catalogColor(line)?.id ?? line.color_id}
									{colors}
									emptyLabel="Any color"
									emptyWarning
									size="sm"
									class="w-44"
									label="Color of {line.part_name ?? line.part_num}"
									onchange={(id) => setColor(line, id)}
								/>
								<Input
									type="number"
									size="sm"
									class="w-24"
									min={1}
									value={line.quantity || ''}
									invalid={!Number.isInteger(line.quantity) || line.quantity < 1}
									aria-label="Quantity of {line.part_name ?? line.part_num}"
									oninput={(event) => setQuantity(line, (event.currentTarget as HTMLInputElement).valueAsNumber)}
								/>
								<Button
									size="sm"
									variant="ghost"
									icon={Trash2}
									label="Remove {line.part_name ?? line.part_num}"
									onclick={() => removeLine(line.key)}
								/>
							</PartTile>
						{:else}
							<PartTile
								name={line.part_name ?? line.part_num}
								imgUrl={picture(line)}
								fallbackImgUrl={photo(line)}
								bricklinkId={line.bricklink_id}
								partNum={line.part_source === 'rebrickable' ? line.part_num : null}
								color={{ name: catalogColor(line)?.name ?? line.color_name, rgb: catalogColor(line)?.rgb ?? line.rgb }}
								quantity={line.quantity}
							/>
						{/if}
					</li>
				{/each}
			</ul>
			{#if visibleLines.length > shown}
				<div class="flex items-center gap-3 border-t border-line px-(--pad-panel) py-3">
					<Button size="sm" onclick={() => (shown += PAGE)}>Show {Math.min(PAGE, visibleLines.length - shown)} more</Button>
					<span class="num text-sm text-ink-muted">{(visibleLines.length - shown).toLocaleString('en-US')} not shown</span>
				</div>
			{/if}
		{/if}

		{#if isOwner}
			{#if saveProblems}
				<div class="border-t border-line px-(--pad-panel) py-3">
					<Alert tone="danger" title={saveProblems[0]}>
						{#if saveProblems.length > 1}
							<ul class="flex max-h-40 flex-col gap-1 overflow-y-auto">
								{#each saveProblems.slice(1) as problem, i (i)}<li>{problem}</li>{/each}
							</ul>
						{/if}
					</Alert>
				</div>
			{/if}
			<div class="flex flex-wrap items-center justify-end gap-x-3 gap-y-2 border-t border-line px-(--pad-panel) py-3">
				<p class="mr-auto min-w-0 text-sm text-ink-muted">
					{#if badQuantity}
						Every part needs a quantity of at least 1.
					{:else if dirty}
						{#if kit.source === 'set'}Saving makes this a kit made by hand. {/if}{#if kit.used_by.length > 0}Profiles keep the
							lines they saved until you save a new version of each.{:else}Unsaved changes.{/if}
					{:else if saved}
						Saved.{#if kit.used_by.length > 0} Profiles that use this kit keep the lines they saved until you save a new version of each.{/if}
					{/if}
				</p>
				<Button variant="ghost" disabled={!dirty || saving} onclick={discard}>Discard changes</Button>
				<Button variant="primary" loading={saving} disabled={!dirty || badQuantity} onclick={() => void save()}>Save changes</Button>
			</div>
		{/if}
	</Panel>

	{#if isOwner}
		<div class="flex max-w-3xl flex-col gap-(--gap-panels)">
			<Panel title="Details">
				<div class="flex flex-col gap-4">
					<Field label="Name" for="kit-name">
						<Input id="kit-name" bind:value={name} />
					</Field>
					<Field label="Description" for="kit-desc">
						<Textarea id="kit-desc" rows={3} bind:value={description} />
					</Field>
					<Field label="Visibility" for="kit-vis" help="Anyone can see a public kit. An unlisted kit opens only from its address.">
						<Select
							id="kit-vis"
							bind:value={visibility}
							options={[
								{ value: 'private', label: 'Private' },
								{ value: 'unlisted', label: 'Unlisted' },
								{ value: 'public', label: 'Public' }
							]}
						/>
					</Field>
					<div class="flex items-center gap-3">
						<KitPicture src={kit.image_url} class="size-14 shrink-0" />
						<div class="flex flex-col items-start gap-1">
							<Button size="sm" icon={Upload} loading={uploading} onclick={() => pictureInput?.click()}>Change picture</Button>
							<span class="text-sm text-ink-muted">A JPEG or PNG. Without one, the kit shows its set or its first part.</span>
						</div>
						<input bind:this={pictureInput} type="file" accept="image/png,image/jpeg" class="hidden" onchange={changePicture} />
					</div>
					{#if detailsError}<Alert tone="danger">{detailsError}</Alert>{/if}
					{#if detailsSaved}<Alert tone="success">Details saved.</Alert>{/if}
				</div>
				{#snippet footer()}
					<Button variant="primary" loading={savingDetails} disabled={!name.trim()} onclick={() => void saveDetails()}>Save details</Button>
				{/snippet}
			</Panel>

			<Panel title="Delete this kit">
				{#snippet actions()}
					<Button icon={Trash2} onclick={() => { deleteError = null; showDeleteModal = true; }}>Delete kit</Button>
				{/snippet}
				<p class="text-sm text-ink-muted">A kit a profile uses cannot be deleted: take its bin out of the profile first.</p>
			</Panel>
		</div>
	{/if}
{/if}

<Modal bind:open={showDeleteModal} title="Delete kit" size="sm">
	<p class="text-sm text-ink-muted">
		Delete <span class="font-medium text-ink">{kit?.name}</span>? This cannot be undone.
	</p>
	{#if deleteError}<Alert tone="danger" class="mt-3">{deleteError}</Alert>{/if}
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (showDeleteModal = false)}>Cancel</Button>
		<Button variant="danger" loading={deleting} onclick={() => void deleteKit()}>Delete kit</Button>
	{/snippet}
</Modal>
