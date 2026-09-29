<!-- Light or dark, remembered in this browser (src/lib/stores/theme.ts). -->
<script lang="ts">
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { theme, type Theme } from '$lib/stores/theme';
</script>

<SegmentedControl
	label="Mode"
	size="sm"
	labelClass="max-sm:sr-only"
	value={$theme}
	onchange={(mode: Theme) => theme.setTheme(mode)}
	options={[
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'dark', label: 'Dark', icon: Moon }
	]}
/>
