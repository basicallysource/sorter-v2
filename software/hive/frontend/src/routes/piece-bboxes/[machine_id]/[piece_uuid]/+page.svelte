<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import * as nav from '$lib/colorLabelNav';
	import PieceLabelPanel from '$lib/components/PieceLabelPanel.svelte';

	const machineId = $derived(page.params.machine_id ?? '');
	const pieceUuid = $derived(page.params.piece_uuid ?? '');

	// Recompute position against the working queue whenever the route piece
	// changes (nav.position reads the module-singleton queue synchronously).
	const position = $derived.by(() => {
		void machineId;
		void pieceUuid;
		return nav.position({ machine_id: machineId, piece_uuid: pieceUuid });
	});

	function gotoKey(k: nav.PieceKey) {
		void goto(`/piece-bboxes/${k.machine_id}/${encodeURIComponent(k.piece_uuid)}`);
	}

	async function goNext() {
		const next = await nav.nextAfter({ machine_id: machineId, piece_uuid: pieceUuid });
		if (next) gotoKey(next);
		else void goto(nav.dashboardUrl());
	}

	async function goPrev() {
		const prev = await nav.prevBefore({ machine_id: machineId, piece_uuid: pieceUuid });
		if (prev) gotoKey(prev);
		else void goto(nav.dashboardUrl());
	}
</script>

<svelte:head>
	<title>Label piece · Hive</title>
</svelte:head>

{#key `${machineId}|${pieceUuid}`}
	<PieceLabelPanel {machineId} {pieceUuid} layout="page" {position} onNext={goNext} onPrev={goPrev} />
{/key}
