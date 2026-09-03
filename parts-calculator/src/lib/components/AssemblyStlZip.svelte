<script lang="ts">
	import { Download, Loader } from 'lucide-svelte';
	import { zipSync } from 'fflate';
	import DropdownMenu from '$lib/components/DropdownMenu.svelte';
	import { concreteLines, getAssembly, getPart, lineQty, type Assembly, type Hardware, type Part } from '$lib/filament';

	// One download control per assembly node: everything printable under it,
	// zipped in the browser from the published hash-addressed STLs — the
	// engraved variant of each part (its best face), or the plain masters.
	// With `snap` (a superseded version's snapshot: the era's own generated
	// records, straight from its commit) it zips that era's files instead —
	// the same URLs the site offered then, engraved or plain.
	let {
		id,
		name,
		layers,
		snap,
		snapArgs
	}: {
		id: string;
		name: string;
		layers: number;
		snap?: { assemblies: Record<string, Assembly>; parts: Record<string, Part>; hardware: Record<string, Hardware> };
		snapArgs?: Record<string, string>;
	} = $props();
	let zipping = $state(false);

	const partOf = (pid: string): Part | undefined => (snap ? snap.parts[pid] : getPart(pid));
	const asmOf = (aid: string): Assembly | undefined => (snap ? snap.assemblies[aid] : getAssembly(aid));

	/** Printed parts reachable below the assembly, id -> count, params
	 *  resolved the same way the tree rows are. Depth-capped rather than
	 *  cycle-checked, like partsUnder in the detail view. Walks the version
	 *  snapshot when one is given, the live catalog otherwise. */
	function printedUnder(
		aid: string,
		mult = 1,
		args?: Record<string, string>,
		acc = new Map<string, number>(),
		depth = 0
	) {
		if (depth > 8) return acc;
		const holder = asmOf(aid);
		if (!holder) return acc;
		for (const line of concreteLines(holder, holder.lines ?? [], args)) {
			const q = lineQty(line, layers) * mult;
			if (line.assembly && asmOf(line.assembly)) printedUnder(line.assembly, q, line.args, acc, depth + 1);
			else if (line.part && partOf(line.part)) acc.set(line.part, (acc.get(line.part) ?? 0) + q);
		}
		return acc;
	}

	async function download(engraved: boolean) {
		if (zipping) return;
		zipping = true;
		try {
			const counts = printedUnder(id, 1, snapArgs);
			if (!counts.size) return;
			const files: Record<string, Uint8Array> = {};
			const manifest: string[] = [
				`${name} — printed parts for one assembly` +
					(engraved ? ' (uid-engraved where a face fits)' : '') +
					(snap ? ', as this version had them' : ''),
				''
			];
			for (const [pid, qty] of counts) {
				const p = partOf(pid)!;
				const url = engraved ? (p.stamped?.[0]?.stl ?? p.stl) : p.stl;
				if (!url) continue;
				const res = await fetch(url);
				if (!res.ok) throw new Error(`${pid}: HTTP ${res.status}`);
				const file = url.slice(url.lastIndexOf('/') + 1);
				files[file] = new Uint8Array(await res.arrayBuffer());
				manifest.push(`x${qty}  ${p.name}  (${file})`);
			}
			// hash-named files say nothing about how many of each to run
			files['print-manifest.txt'] = new TextEncoder().encode(manifest.join('\n') + '\n');
			const zipped = zipSync(files, { level: 6 });
			const a = document.createElement('a');
			a.href = URL.createObjectURL(new Blob([zipped as BlobPart], { type: 'application/zip' }));
			a.download = `${id}-stls${engraved ? '-engraved' : ''}.zip`;
			a.click();
			URL.revokeObjectURL(a.href);
		} finally {
			zipping = false;
		}
	}
</script>

<DropdownMenu label="Download {name}" menuClass="w-64">
	{#snippet trigger({ toggle, open })}
		<button
			type="button"
			class="flex h-5 w-5 items-center justify-center text-text-muted hover:text-text"
			aria-label="Download {name}"
			aria-expanded={open}
			onclick={toggle}
		>
			{#if zipping}<Loader size={13} class="animate-spin" />{:else}<Download size={13} />{/if}
		</button>
	{/snippet}
	{#snippet children({ close })}
		<button
			type="button"
			role="menuitem"
			class="block w-full px-3 py-1.5 text-left text-xs text-text hover:bg-primary/[0.06]"
			onclick={() => {
				close();
				download(true);
			}}>All STLs, version ids engraved (zip)</button>
		<button
			type="button"
			role="menuitem"
			class="block w-full px-3 py-1.5 text-left text-xs text-text hover:bg-primary/[0.06]"
			onclick={() => {
				close();
				download(false);
			}}>All STLs, plain (zip)</button>
	{/snippet}
</DropdownMenu>
