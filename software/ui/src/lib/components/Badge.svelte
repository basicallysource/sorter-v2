<script lang="ts">
	import type { Snippet } from 'svelte';

	type Color = 'gray' | 'yellow' | 'blue' | 'orange' | 'green' | 'red';

	interface Props {
		color?: Color;
		children: Snippet;
	}

	let { color = 'gray', children }: Props = $props();

	const colors: Record<Color, string> = {
		gray: 'bg-gray-500/20 text-gray-400 border-gray-500/50',
		yellow: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
		blue: 'bg-primary/20 text-primary border-primary/50',
		orange: 'bg-orange-500/20 text-orange-400 border-orange-500/50',
		green: 'bg-[#00852B]/20 text-[#00852B] border-[#00852B]/50',
		red: 'bg-[#D01012]/20 text-[#D01012] border-[#D01012]/50'
	};
</script>

<span class="inline-block border px-1.5 py-0.5 text-xs font-medium {colors[color]}">
	{@render children()}
</span>
