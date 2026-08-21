<script lang="ts">
	import { ArrowLeft, Box, Boxes, CheckCircle2, Layers3 } from 'lucide-svelte';
	import Badge from '$lib/components/Badge.svelte';
	import PriorityBadge from '$lib/components/PriorityBadge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import PartDetailModal from '$lib/components/PartDetailModal.svelte';
	import Seo from '$lib/components/Seo.svelte';
	import { ASSEMBLIES, CHANGES, HARDWARE, PARTS, SECTIONS, fmtDate, hardwareImage, type ChangeTargetKind, type Part, type PartVersion, type PlannedChange } from '$lib/filament';
	import { LASER_CUT_PARTS } from '$lib/lasercut';

	const partNames = new Map(PARTS.map((part) => [part.id, part.name]));
	const assemblyNames = new Map(ASSEMBLIES.map((assembly) => [assembly.id, assembly.name]));
	const sectionNames = new Map(SECTIONS.map((section) => [section.id, section.name]));
	const laserNames = new Map(LASER_CUT_PARTS.map((part) => [part.id, part.name]));
	const hardwareNames = new Map(HARDWARE.map((part) => [part.id, part.name]));
	function byPriority(a: PlannedChange, b: PlannedChange): number {
		const priority = a.priority.localeCompare(b.priority);
		if (priority) return priority;
		return Number(b.condition === 'broken') - Number(a.condition === 'broken');
	}
	const plannedChanges = CHANGES.filter((change) => change.status !== 'complete').sort(byPriority);
	const completedChanges = CHANGES.filter((change) => change.status === 'complete').sort((a, b) =>
		(b.completed_at ?? '').localeCompare(a.completed_at ?? '') || a.name.localeCompare(b.name)
	);

	function targetName(kind: ChangeTargetKind, id: string): string {
		return (kind === 'parts' ? partNames : kind === 'assemblies' ? assemblyNames : kind === 'sections' ? sectionNames : kind === 'lasercut' ? laserNames : hardwareNames).get(id) ?? id;
	}
	function targetHref(kind: ChangeTargetKind, id: string): string {
		if (kind === 'parts') return `/part/${id}`;
		if (kind === 'assemblies') return `/#assembly-${id}`;
		if (kind === 'sections') return `/#section-${id}`;
		if (kind === 'lasercut') return `/lasercut#laser-${id}`;
		return `/hardware#hardware-${id}`;
	}
	function modelsFor(change: PlannedChange): Part[] {
		const ids = new Set(change.targets.parts ?? []);
		for (const assembly of change.targets.assemblies ?? [])
			for (const part of PARTS) if (part.assembly === assembly) ids.add(part.id);
		for (const section of change.targets.sections ?? [])
			for (const part of PARTS) if (section in part.quantities) ids.add(part.id);
		return [...ids].map((id) => PARTS.find((part) => part.id === id)).filter((part): part is Part => !!part);
	}
	const targetLabels: Record<ChangeTargetKind, string> = {
		parts: 'Parts', assemblies: 'Assembly', sections: 'Section', lasercut: 'Laser cut', hardware: 'Hardware'
	};

	let modelOpen = $state(false);
	let modelPart = $state<Part | null>(null);
	let modelColor = $state('ash-gray');
	let modelVersion = $state<PartVersion | null>(null);
	function openModel(part: Part) {
		modelPart = part;
		modelVersion = part.versions?.[part.versions.length - 1] ?? null;
		modelOpen = true;
	}

	let imageOpen = $state(false);
	let imageSrc = $state('');
	let imageAlt = $state('');
	function openImage(src: string, alt: string) {
		imageSrc = src;
		imageAlt = alt;
		imageOpen = true;
	}
</script>

{#snippet changeTable(changes: PlannedChange[], completed: boolean)}
	<div class="overflow-x-auto border border-border bg-surface">
		<table class="w-full min-w-[850px] border-collapse text-sm">
			<thead>
				<tr class="border-b border-border bg-[var(--color-bg)] text-left text-xs uppercase tracking-wider text-text-muted">
					<th class="w-20 px-3 py-2 font-semibold">{completed ? 'Status' : 'Priority'}</th>
					<th class="w-[42%] px-3 py-2 font-semibold">Change</th>
					<th class="px-3 py-2 font-semibold">Affected BOM items</th>
				</tr>
			</thead>
			<tbody>
				{#each changes as change (change.id)}
					{@const models = modelsFor(change)}
					{@const laserTargets = LASER_CUT_PARTS.filter((part) => change.targets.lasercut?.includes(part.id))}
					{@const hardwareTargets = HARDWARE.filter((part) => change.targets.hardware?.includes(part.id))}
					<tr id={change.id} class="scroll-mt-6 border-b border-border align-top last:border-b-0 hover:bg-primary/[0.025]">
						<td class="px-3 py-3">
							{#if completed}
								<Badge variant="success"><CheckCircle2 size={11} /> Complete</Badge>
								{#if change.completed_at}<div class="mt-1 text-[10px] text-text-muted">{fmtDate(change.completed_at)}</div>{/if}
							{:else}
								<PriorityBadge priority={change.priority} />
								{#if change.condition === 'broken'}<div class="mt-1 text-[10px] font-semibold uppercase leading-tight tracking-wide text-danger">Broken feature</div>{/if}
							{/if}
						</td>
						<td class="px-3 py-3">
							<h2 class="font-bold leading-tight text-text">{change.name}</h2>
							<p class="mt-1 text-xs leading-relaxed text-text-muted">{change.description}</p>
							{#if change.images?.length}
								<div class="mt-2 flex gap-2 overflow-x-auto">
									{#each change.images as image}<figure class="w-40 shrink-0"><button type="button" class="block cursor-zoom-in" title="Open full-size image" onclick={() => openImage(image.url, image.alt)}><img src={image.url} alt={image.alt} class="h-24 w-40 border border-border bg-white object-contain hover:border-primary" /></button>{#if image.caption}<figcaption class="mt-0.5 truncate text-[10px] text-text-muted">{image.caption}</figcaption>{/if}</figure>{/each}
								</div>
							{/if}
							<div class="mt-2 flex flex-wrap gap-x-3 gap-y-1">
								{#each Object.entries(change.targets) as [kind, ids]}
									{@const targetKind = kind as ChangeTargetKind}
									{#each ids ?? [] as id}
										<a href={targetHref(targetKind, id)} class="inline-flex items-center gap-1 text-[11px] text-primary hover:text-primary-hover">
											{#if targetKind === 'parts' || targetKind === 'hardware'}<Box size={11} />{:else if targetKind === 'assemblies'}<Boxes size={11} />{:else}<Layers3 size={11} />{/if}
											<span class="text-text-muted">{targetLabels[targetKind]}:</span> {targetName(targetKind, id)}
										</a>
									{/each}
								{/each}
							</div>
						</td>
						<td class="px-3 py-3">
							<div class="flex flex-wrap gap-2">
								{#each models as part (part.id)}
									<button type="button" class="group w-20 cursor-pointer text-left" title="Open current 3D model for {part.name}" onclick={() => openModel(part)}>
										<span class="flex h-14 w-20 items-center justify-center overflow-hidden border border-border bg-[var(--color-bg)] group-hover:border-primary">
											<img src={part.render} alt={part.name} class="h-full w-full object-contain transition-transform group-hover:scale-105" />
										</span>
										<span class="mt-1 block truncate text-[10px] leading-tight text-text-muted group-hover:text-primary">{part.name}</span>
									</button>
								{/each}
								{#each laserTargets as part (part.id)}
									<button type="button" class="group w-20 cursor-zoom-in text-left" title="Open large preview of {part.name}" onclick={() => openImage(part.preview, part.name)}>
										<span class="flex h-14 w-20 items-center justify-center overflow-hidden border border-border bg-white group-hover:border-primary"><img src={part.preview} alt={part.name} class="h-full w-full object-contain transition-transform group-hover:scale-105" /></span>
										<span class="mt-1 block truncate text-[10px] leading-tight text-text-muted group-hover:text-primary">{part.name}</span>
									</button>
								{/each}
								{#each hardwareTargets as part (part.id)}
									{@const image = hardwareImage(part)}
									<a href="/hardware#hardware-{part.id}" class="group w-20" title="Open {part.name}">
										<span class="flex h-14 w-20 items-center justify-center overflow-hidden border border-border bg-white group-hover:border-primary">{#if image}<img src={image.src} alt={part.name} class="h-full w-full object-contain transition-transform group-hover:scale-105" />{:else}<Box size={18} class="text-text-muted" />{/if}</span>
										<span class="mt-1 block truncate text-[10px] leading-tight text-text-muted group-hover:text-primary">{part.name}</span>
									</a>
								{/each}
								{#if !models.length && !laserTargets.length && !hardwareTargets.length}<span class="text-xs italic text-text-muted">No preview available</span>{/if}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/snippet}

<Seo title="Intended Changes — Sorter Parts Calculator" description="Planned and completed improvements to Sorter V2 parts and assemblies." />

<main class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
	<a href="/" class="mb-5 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary-hover"><ArrowLeft size={15} /> Printed parts</a>
	<div class="mb-6">
		<h1 class="text-3xl font-bold tracking-tight text-text">Intended Changes</h1>
		<p class="mt-2 max-w-3xl text-sm text-text-muted">Known fixes and planned improvements. P0 is reserved for broken features; higher numbers are progressively lower priority, with P4 used for nice-to-have improvements. Click any part thumbnail to inspect its current interactive 3D model.</p>
	</div>

	{@render changeTable(plannedChanges, false)}

	{#if completedChanges.length}
		<section class="mt-10" aria-labelledby="completed-changes-heading">
			<h2 id="completed-changes-heading" class="text-2xl font-bold tracking-tight text-text">Completed Changes</h2>
			<p class="mb-4 mt-2 max-w-3xl text-sm text-text-muted">Resolved fixes and improvements remain here as a record of what changed. They no longer mark parts as broken or subject to change.</p>
			{@render changeTable(completedChanges, true)}
		</section>
	{/if}
</main>

<PartDetailModal bind:open={modelOpen} part={modelPart} bind:colorId={modelColor} bind:version={modelVersion} />

<Modal bind:open={imageOpen} title={imageAlt} maxW="max-w-6xl">
	<div class="flex min-h-0 items-center justify-center bg-white p-4">
		<img src={imageSrc} alt={imageAlt} class="max-h-[78vh] max-w-full object-contain" />
	</div>
</Modal>
