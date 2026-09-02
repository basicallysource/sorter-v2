<script lang="ts">
	import { Download, Loader } from 'lucide-svelte';
	import { zipSync } from 'fflate';
	import DropdownMenu from '$lib/components/DropdownMenu.svelte';
	import { concreteLines, getAssembly, getPart, lineQty, type FrozenAssembly } from '$lib/filament';

	// One download control per assembly node: everything printable under it,
	// zipped in the browser from the published hash-addressed STLs — the
	// engraved variant of each part (its best face), or the plain masters.
	// With `tree` (a superseded version's frozen subtree) it zips the pinned
	// revisions of that moment instead: the geometry as it was, by uid.
	let {
		id,
		name,
		layers,
		tree,
		treeArgs
	}: {
		id: string;
		name: string;
		layers: number;
		tree?: Record<string, FrozenAssembly>;
		treeArgs?: Record<string, string>;
	} = $props();
	let zipping = $state(false);

	/** Printed parts reachable below the assembly, id -> {count, pinned uid},
	 *  params resolved the same way the tree rows are. Depth-capped rather
	 *  than cycle-checked, like partsUnder in the detail view. Walks the
	 *  frozen tree when one is given, the live catalog otherwise. */
	function printedUnder(
		aid: string,
		mult = 1,
		args?: Record<string, string>,
		acc = new Map<string, { qty: number; uid?: string }>(),
		depth = 0
	) {
		if (depth > 8) return acc;
		const holder = tree ? tree[aid] : getAssembly(aid);
		if (!holder) return acc;
		const rawLines = tree ? (tree[aid]?.lines ?? []) : (getAssembly(aid)?.lines ?? []);
		for (const line of concreteLines(holder, rawLines, args)) {
			const q = lineQty(line, layers) * mult;
			if (line.assembly && (!tree || tree[line.assembly]))
				printedUnder(line.assembly, q, line.args, acc, depth + 1);
			else if (line.part && getPart(line.part)) {
				const got = acc.get(line.part);
				const pin = (line as { uid?: string }).uid;
				acc.set(line.part, { qty: (got?.qty ?? 0) + q, uid: got?.uid ?? pin });
			}
		}
		return acc;
	}

	/** The STL for a part at a pinned uid: the archived revision's bytes when
	 *  the pin is old, the live master when it is (or nothing pins it). */
	function stlAt(pid: string, uid: string | undefined, engraved: boolean): string | undefined {
		const p = getPart(pid)!;
		if (uid && uid !== p.uid) return p.versions?.find((v) => v.uid === uid)?.stl ?? p.stl;
		return engraved ? (p.stamped?.[0]?.stl ?? p.stl) : p.stl;
	}

	async function download(engraved: boolean) {
		if (zipping) return;
		zipping = true;
		try {
			const counts = printedUnder(id, 1, treeArgs);
			if (!counts.size) return;
			const files: Record<string, Uint8Array> = {};
			const manifest: string[] = [
				`${name} — printed parts for one assembly` +
					(tree
						? ' (the pinned revisions of this version)'
						: engraved
							? ' (uid-engraved where a face fits)'
							: ''),
				''
			];
			for (const [pid, { qty, uid }] of counts) {
				const p = getPart(pid)!;
				const url = stlAt(pid, tree ? uid : undefined, engraved);
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
		{#if tree}
			<button
				type="button"
				role="menuitem"
				class="block w-full px-3 py-1.5 text-left text-xs text-text hover:bg-primary/[0.06]"
				onclick={() => {
					close();
					download(false);
				}}>All STLs at this version (zip)</button>
		{:else}
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
		{/if}
	{/snippet}
</DropdownMenu>
