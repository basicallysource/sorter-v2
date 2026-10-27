<!--
	docs/components.md#data. A picture that enlarges where it is pointed at: a
	thumbnail in a list of pieces, one frame of a burst. The pointer on it, or
	keyboard focus in it, shows the picture large beside it at once, and taking
	the pointer off puts it away: nothing to click, nothing to close, so a row
	of photos is looked over by moving along it. It floats, so it is the raised
	plane, in the browser's top layer (no overflow clips it), and it never takes
	the pointer: what is under it stays where it was.

	The large picture is the thumbnail's own file (`src`), shown whole at its own
	shape, as large as `size` and the window allow, up to three times its size
	(it is the same file, so it is already loaded). Beside it, on the right,
	or on the left where there is no room, and kept 8px inside the window.
	`label` says what it is under it. With no `src` it is only its children.

	<ImageZoom src={crop.src} label="Burst 3 of 9, 16:37:31">
		<img src={crop.src} alt="" class="size-20 object-contain" />
	</ImageZoom>
-->
<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import { place } from './place';

	let {
		src,
		label,
		size = 28,
		class: className = '',
		children
	}: {
		src: string | null | undefined;
		// What it is, under the large picture.
		label?: string;
		// The most it grows to, in rem.
		size?: number;
		// On the element around the thumbnail.
		class?: string;
		children: Snippet;
	} = $props();

	let anchor: HTMLElement;
	let panel: HTMLElement;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let open = $state(false);
	let natural = $state({ width: 0, height: 0 });

	// The picture's size in the window: as large as `size` and the window allow,
	// not more than three times its own, in its own shape.
	const shown = $derived.by(() => {
		if (!natural.width || !natural.height || typeof window === 'undefined') return null;
		const room = Math.min(size * 16, window.innerWidth * 0.8, window.innerHeight * 0.8);
		const scale = Math.min(room / natural.width, room / natural.height, 3);
		return { width: natural.width * scale, height: natural.height * scale };
	});

	function position() {
		// Shown once its size is known, so it never appears and then jumps.
		if (!panel || !open || !shown) return;
		const at = place(anchor.getBoundingClientRect(), panel.getBoundingClientRect(), 'right', 10);
		panel.style.top = `${at.top}px`;
		panel.style.left = `${at.left}px`;
		panel.style.visibility = 'visible';
	}

	function show(delay: number) {
		if (!src) return;
		clearTimeout(timer);
		timer = setTimeout(async () => {
			open = true;
			panel.style.visibility = 'hidden';
			if (!panel.matches(':popover-open')) panel.showPopover();
			await tick();
			position();
		}, delay);
	}

	function hide() {
		clearTimeout(timer);
		open = false;
		natural = { width: 0, height: 0 };
		if (panel?.matches(':popover-open')) panel.hidePopover();
	}

	// Its size is known once the picture has loaded (at once, from the cache).
	$effect(() => {
		if (open && shown) void tick().then(position);
	});

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') hide();
	}
</script>

<svelte:window {onkeydown} />

<span
	bind:this={anchor}
	class="inline-flex {className}"
	role="presentation"
	onpointerenter={() => show(60)}
	onpointerleave={hide}
	onfocusin={() => show(0)}
	onfocusout={hide}
>
	{@render children()}
</span>

<div
	bind:this={panel}
	popover="manual"
	role="img"
	aria-label={label ?? 'Enlarged picture'}
	class="pointer-events-none fixed inset-auto m-0 rounded-control border border-line bg-raised p-1.5 text-ink"
>
	{#if open && src}
		<img
			{src}
			alt=""
			decoding="async"
			bind:naturalWidth={natural.width}
			bind:naturalHeight={natural.height}
			style:width={shown ? `${shown.width}px` : undefined}
			style:height={shown ? `${shown.height}px` : undefined}
			class="block max-w-none object-contain"
		/>
		{#if label}<div class="px-1 pt-1.5 pb-0.5 text-xs text-ink-muted">{label}</div>{/if}
	{/if}
</div>
