<script lang="ts">
	// Stands in for a piece's picture when there is none: a 2x4 brick drawn in
	// line, with a question mark on its side, in the gray of whatever text color
	// the caller gives it (text-ink-faint for a placeholder). The same drawing
	// wherever a piece has no image, so it reads as "a piece we never saw".
	let { class: className = '' }: { class?: string } = $props();

	// Studs on the top face, back row first so the front row draws over it.
	const STUDS: [number, number][] = [
		[15, 16],
		[25, 16],
		[35, 16],
		[45, 16],
		[11, 20],
		[21, 20],
		[31, 20],
		[41, 20]
	];
	const R = 3; // stud radius along the brick
	const RY = 1.5; // the same radius seen from above
	const H = 2.5; // stud height

	// The stud's side: between the front halves of its bottom and top ellipses,
	// so the top (drawn after) doesn't overlap it.
	function studBody(cx: number, cy: number): string {
		return (
			`M${cx - R} ${cy - H} L${cx - R} ${cy} A${R} ${RY} 0 0 0 ${cx + R} ${cy} ` +
			`L${cx + R} ${cy - H} A${R} ${RY} 0 0 1 ${cx - R} ${cy - H} Z`
		);
	}
</script>

<svg
	viewBox="0 0 56 42"
	class={className}
	role="img"
	aria-label="No picture of this piece"
	fill="none"
	stroke="currentColor"
	stroke-width="1.4"
	stroke-linejoin="round"
>
	<path d="M4 22 L44 22 L52 14 L12 14 Z" fill="currentColor" fill-opacity="0.12" />
	<path d="M4 22 L44 22 L44 38 L4 38 Z" fill="currentColor" fill-opacity="0.2" />
	<path d="M44 22 L52 14 L52 30 L44 38 Z" fill="currentColor" fill-opacity="0.32" />
	{#each STUDS as [cx, cy] (`${cx}-${cy}`)}
		<path d={studBody(cx, cy)} fill="currentColor" fill-opacity="0.25" />
		<ellipse {cx} cy={cy - H} rx={R} ry={RY} fill="currentColor" fill-opacity="0.1" />
	{/each}
	<text
		x="24"
		y="34.6"
		text-anchor="middle"
		font-size="12"
		font-weight="700"
		fill="currentColor"
		stroke="none">?</text
	>
</svg>
