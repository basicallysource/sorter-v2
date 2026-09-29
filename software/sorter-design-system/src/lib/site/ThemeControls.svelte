<!-- The site's own theme controls, so every page can be read in both modes and any primary. -->
<script lang="ts">
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import Button from '$lib/components/Button.svelte';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import { theme, type Mode } from '$lib/theme.svelte';

	let mode = $state<Mode>(theme.mode);
	let colorId = $state(theme.colorId);
</script>

<div class="flex items-center gap-2">
	<Popover label="Primary color" placement="bottom-end" width="auto">
		{#snippet trigger(props)}
			<Button {...props} size="sm" variant="ghost">
				<span class="size-3.5 bg-primary"></span><span class="max-sm:sr-only">Color</span>
			</Button>
		{/snippet}
		<ColorPicker bind:value={colorId} columns={8} onchange={(id) => theme.setColor(id)} />
	</Popover>
	<SegmentedControl
		label="Mode"
		size="sm"
		labelClass="max-sm:sr-only"
		bind:value={mode}
		onchange={(m) => theme.setMode(m)}
		options={[
			{ value: 'light', label: 'Light', icon: Sun },
			{ value: 'dark', label: 'Dark', icon: Moon }
		]}
	/>
</div>
