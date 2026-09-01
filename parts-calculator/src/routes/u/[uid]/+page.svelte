<script lang="ts">
	import Seo from '$lib/components/Seo.svelte';
	import { fmtDate } from '$lib/filament';
	import { ChevronRight } from 'lucide-svelte';

	// What the id on a print names. Everything here is a small summary that
	// answers "what is this, and is it still current" and hands off to the
	// thing's own page for the rest.
	let { data } = $props();
	const uid = $derived(data.uid);
	const m = $derived(data.match);

	type Summary = { what: string; name: string; status: string; detail?: string; href: string; image?: string };
	const s = $derived.by((): Summary => {
		switch (m.kind) {
			case 'part':
				return {
					what: '3D printed part',
					name: m.part.name,
					status: `Current version (v${m.part.version}).`,
					detail: m.part.description,
					href: `/part/${m.part.id}`,
					image: m.part.render
				};
			case 'part-version': {
				const v = m.version;
				return {
					what: '3D printed part',
					name: m.part.name,
					status: `Version ${v.version}, dated ${fmtDate(v.date)}. Superseded: the current version is v${m.part.version}.`,
					detail: v.message,
					href: `/part/${m.part.id}`,
					image: v.render ?? m.part.render
				};
			}
			case 'part-candidate': {
				const c = m.candidate;
				const state = c.rejected_at
					? `Rejected ${fmtDate(c.rejected_at)}.`
					: c.superseded_by
						? `Superseded by candidate ${c.superseded_by}${c.superseded_at ? ` on ${fmtDate(c.superseded_at)}` : ''}.`
						: 'Still under test.';
				return {
					what: '3D printed part · candidate',
					name: `${m.part.name}${c.name ? ` (${c.name})` : ''}`,
					status: `A test revision for the ${m.part.name} slot, added ${fmtDate(c.created_at)}. ${state} Not the current part (v${m.part.version}).`,
					detail: c.message,
					href: `/part/${m.part.id}`,
					image: c.render ?? m.part.render
				};
			}
			case 'assembly':
				return {
					what: 'assembly',
					name: m.assembly.name,
					status: `Current structure${m.assembly.version ? ` (v${m.assembly.version})` : ''}.`,
					detail: m.assembly.description,
					href: `/assembly?focus=${encodeURIComponent(m.assembly.id)}`
				};
			case 'assembly-version':
				return {
					what: 'assembly',
					name: m.assembly.name,
					status: `Structure v${m.version.version}, dated ${fmtDate(m.version.date)}. Superseded: the current structure is v${m.assembly.version}.`,
					detail: m.version.message,
					href: `/assembly?focus=${encodeURIComponent(m.assembly.id)}`
				};
			case 'assembly-candidate':
				return {
					what: 'assembly · candidate',
					name: `${m.assembly.name}${m.candidate.name ? ` (${m.candidate.name})` : ''}`,
					status: `An alternative bill of materials under test for ${m.assembly.name}, added ${fmtDate(m.candidate.created_at)}.${m.candidate.rejected_at ? ` Rejected ${fmtDate(m.candidate.rejected_at)}.` : ''}`,
					detail: m.candidate.message,
					href: `/assembly?focus=${encodeURIComponent(m.assembly.id)}`
				};
			case 'hardware':
				return {
					what: 'off-the-shelf hardware',
					name: m.hardware.name,
					status: 'Current.',
					detail: m.hardware.description,
					href: `/part/${m.hardware.id}`,
					image: m.hardware.image ?? undefined
				};
			case 'lasercut':
				return {
					what: 'laser-cut sheet part',
					name: m.lasercut.name,
					status: 'Current.',
					detail: m.lasercut.description,
					href: '/lasercut',
					image: m.lasercut.photo
				};
		}
	});
</script>

<Seo title="{uid.toUpperCase()} · {s.name}" description={s.status} image={s.image} type="article" />

<div class="mx-auto max-w-2xl px-4 py-8 sm:px-6">
	<div class="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">Id on a print</div>
	<div class="mb-5 font-mono text-4xl font-bold tracking-wider text-text">{uid.toUpperCase()}</div>

	<div class="setup-card-shell flex gap-4 border p-4">
		{#if s.image}
			<img src={s.image} alt="{s.name} preview" class="h-24 w-24 shrink-0 border border-border bg-[var(--color-bg)] object-contain" />
		{/if}
		<div class="min-w-0 text-sm">
			<div class="text-xs text-text-muted">{s.what}</div>
			<a href={s.href} class="inline-flex items-center gap-1 text-lg font-bold text-text hover:text-primary">
				{s.name} <ChevronRight size={16} class="opacity-60" />
			</a>
			<p class="mt-1 text-text">{s.status}</p>
			{#if s.detail}<p class="mt-1 text-text-muted">{s.detail}</p>{/if}
		</div>
	</div>

	<p class="mt-4 text-xs text-text-muted">
		Every part, version and candidate in this catalog carries a 4-character id, and a stamped download
		has it recessed into one face. An id is never reused or removed, so whatever it is on, this page
		says what that was.
	</p>
</div>
