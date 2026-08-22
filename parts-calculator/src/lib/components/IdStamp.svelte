<script lang="ts">
	import Popover from '$lib/components/Popover.svelte';
	import type { PartStamp } from '$lib/filament';
	import { ChevronLeft, ChevronRight, Crosshair, RotateCcw } from 'lucide-svelte';

	// The id stamp, as one small family of controls that share one state: is the
	// version id engraved into the download (`on`), and on which face (`faceIdx`).
	// `where="viewport"` is the box overlaid on the 3D preview: the checkbox with
	// its explanation, "show me" to fly the camera to the mark, and a second group
	// for trying a different face. `where="download"` is the same checkbox beside
	// the download button, so what you see is what you get. Both bind to the same
	// two values in PartDetail. `where="global"` is the dashboard's one checkbox
	// over every download it hands out (rows, selected, all): no uid, no faces,
	// just the choice and what it means.
	let {
		uid = '',
		stamps = [],
		on = $bindable(true),
		faceIdx = $bindable(0),
		where = 'download',
		onView,
		onReset
	}: {
		uid?: string;
		stamps?: PartStamp[];
		on?: boolean;
		faceIdx?: number;
		where?: 'viewport' | 'download' | 'global';
		onView?: () => void;
		onReset?: () => void;
	} = $props();

	const UID = $derived(uid.toUpperCase());
	const stamp = $derived(on ? (stamps[faceIdx] ?? null) : null);
	const cycle = (dir: 1 | -1) => (faceIdx = (faceIdx + dir + stamps.length) % stamps.length);
	const uniq = $props.id();
	const boxId = `stamp-${uniq}`;
</script>

{#if where === 'global'}
	<label class="inline-flex cursor-pointer items-center gap-1.5 text-xs text-text" for={boxId}>
		<input id={boxId} type="checkbox" class="setup-toggle h-3.5 w-3.5" bind:checked={on} />
		<span>Engrave version ids</span>
	</label>
	<Popover width="w-72" align="right">
		<p>Every part has a 4-character version id. With this on, each STL you download here has its own id recessed 0.6 mm into one face, so a print can be looked up later by typing the id into the site.</p>
		<p class="mt-1.5">Open a part to see where its mark goes, or to put it on a different face. A few parts are too small to carry one and come plain either way.</p>
	</Popover>
{:else if stamps.length}
	{#if where === 'viewport'}
		<div class="pointer-events-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 border border-border bg-[var(--color-surface)]/95 px-2.5 py-1.5 text-xs shadow-sm backdrop-blur">
			<label class="inline-flex cursor-pointer items-center gap-1.5 text-text" for={boxId}>
				<input id={boxId} type="checkbox" class="setup-toggle h-3.5 w-3.5" bind:checked={on} />
				<span class="font-medium">Engrave version id</span>
				<span class="font-mono font-bold tracking-wider">{UID}</span>
			</label>
			<Popover width="w-72">
				<p>The exact version of this part, <span class="font-mono font-semibold text-text">{UID}</span>, is recessed 0.6 mm into one face of the download. Anyone holding the print can type it into the site and land on exactly this version.</p>
				<p class="mt-1.5">It is painted <span class="font-semibold text-warning-dark">yellow</span> in the preview so you can find it. Uncheck to download the plain file.</p>
			</Popover>
			{#if on}
				<span class="h-4 w-px bg-border"></span>
				<button type="button" class="inline-flex items-center gap-1 text-primary hover:text-primary-hover" onclick={onView} title="Turn the view to look straight at the engraving">
					<Crosshair size={13} /> Show me
				</button>
				<button type="button" class="inline-flex items-center gap-1 text-text-muted hover:text-text" onclick={onReset} title="Back to the whole part">
					<RotateCcw size={12} /> Whole part
				</button>
				{#if stamps.length > 1}
					<span class="h-4 w-px bg-border"></span>
					<span class="inline-flex items-center gap-1">
						<button type="button" class="inline-flex h-5 w-5 items-center justify-center border border-border text-text hover:border-primary" onclick={() => cycle(-1)} aria-label="Previous face" title="Previous face (←)"><ChevronLeft size={13} /></button>
						<span class="min-w-[7.5rem] text-center text-text" aria-live="polite">on the {stamp?.face} <span class="text-text-muted">· {faceIdx + 1}/{stamps.length}</span></span>
						<button type="button" class="inline-flex h-5 w-5 items-center justify-center border border-border text-text hover:border-primary" onclick={() => cycle(1)} aria-label="Next face" title="Next face (→)"><ChevronRight size={13} /></button>
					</span>
					<Popover width="w-64" align="right">
						<p>If this face is a bad place for it (a mating surface, somewhere you'll see it), try another. The first one offered is where it prints and hides best. The arrow keys flip too.</p>
					</Popover>
				{:else}
					<span class="text-text-muted">on the {stamp?.face}</span>
				{/if}
			{/if}
		</div>
	{:else}
		<label class="inline-flex cursor-pointer items-center gap-1.5 text-xs text-text" for={boxId}>
			<input id={boxId} type="checkbox" class="setup-toggle h-3.5 w-3.5" bind:checked={on} />
			<span>Engrave version id</span>
			<span class="font-mono font-semibold tracking-wider">{UID}</span>
			{#if stamp}<span class="text-text-muted">on the {stamp.face}</span>{/if}
		</label>
		<Popover width="w-72">
			<p>With this on, the STL you download has <span class="font-mono font-semibold text-text">{UID}</span> recessed 0.6 mm into {stamp ? `the ${stamp.face}` : 'one face'}, so the print can be looked up later. Use the controls on the preview to see where, or to pick a different face.</p>
		</Popover>
	{/if}
{/if}
