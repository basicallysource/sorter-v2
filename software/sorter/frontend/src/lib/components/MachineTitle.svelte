<script lang="ts">
	// Decorates the browser tab title with the selected machine's name. Every route
	// sets its own "Sorter - <page>" title via <svelte:head>; here we swap the
	// "Sorter" brand token for the machine name (matching the header badge), e.g.
	// "Sorter - Dashboard" -> "GBL Sorter - Dashboard". A MutationObserver keeps it
	// applied across navigations and reactive per-page title changes without having
	// to touch all ~34 page titles.
	import { onMount } from 'svelte';
	import { getMachinesContext } from '$lib/machines/context';

	const manager = getMachinesContext();

	const machineName = $derived(
		manager.selectedMachine?.identity?.nickname ??
			manager.selectedMachine?.identity?.machine_id.slice(0, 8) ??
			null
	);

	// The undecorated title a page set for itself; we always re-derive from this so
	// applying the machine name is idempotent.
	let base = '';

	function decorate(raw: string): string {
		if (!machineName || !raw.includes('Sorter')) return raw;
		return raw.replace('Sorter', machineName);
	}

	function render() {
		const next = decorate(base);
		if (document.title !== next) document.title = next;
	}

	onMount(() => {
		const titleEl = document.querySelector('title');
		if (!titleEl) return;

		base = document.title;
		render();

		const observer = new MutationObserver(() => {
			// Ignore our own writes; anything else is a page setting a fresh title.
			if (document.title === decorate(base)) return;
			base = document.title;
			render();
		});
		observer.observe(titleEl, { childList: true, characterData: true, subtree: true });

		return () => observer.disconnect();
	});

	// Re-decorate when the machine name arrives or changes (it loads asynchronously
	// over the websocket after the page has already set its title).
	$effect(() => {
		machineName;
		render();
	});
</script>
