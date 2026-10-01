<!--
	The site's own viewing controls, at the foot of its side nav, so every
	page can be read in both modes and with any primary. They belong to this
	site, not to the pattern: in an app, light or dark and the primary are
	settings (Settings > General on a machine, the account's settings on
	Hive), never controls in the top bar.
-->
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

<div class="flex flex-col gap-2 px-2.5">
	<div class="label">View the site in</div>
	<div class="flex flex-wrap items-center gap-2">
		<SegmentedControl
			label="Mode"
			size="sm"
			bind:value={mode}
			onchange={(m) => theme.setMode(m)}
			options={[
				{ value: 'light', label: 'Light', icon: Sun },
				{ value: 'dark', label: 'Dark', icon: Moon }
			]}
		/>
		<Popover label="Primary color" placement="top-start" width="auto">
			{#snippet trigger(props)}
				<Button {...props} size="sm" variant="ghost">
					<span class="size-3.5 bg-primary"></span>Color
				</Button>
			{/snippet}
			<ColorPicker bind:value={colorId} columns={8} onchange={(id) => theme.setColor(id)} />
		</Popover>
	</div>
</div>
