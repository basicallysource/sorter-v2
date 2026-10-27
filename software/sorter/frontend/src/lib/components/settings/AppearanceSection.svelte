<script lang="ts">
	import { settings } from '$lib/stores/settings';
	import { getCurrentThemeColorId, setThemeColor } from '$lib/stores/themeColor.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import ColorPicker from '$lib/components/ui/ColorPicker.svelte';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';

	let colorId = $state(getCurrentThemeColorId());
</script>

<Panel title="Appearance" flush>
	<div class="divide-y divide-line">
		<SettingRow label="Theme" help="Applies at once, on this browser.">
			<SegmentedControl
				label="Theme"
				value={$settings.theme}
				onchange={(mode) => settings.setTheme(mode)}
				options={[
					{ value: 'light', label: 'Light', icon: Sun },
					{ value: 'dark', label: 'Dark', icon: Moon }
				]}
			/>
		</SettingRow>
		<div class="px-(--pad-panel) py-(--pad-row)">
			<div class="text-sm font-medium text-ink">Theme color</div>
			<p class="mt-0.5 text-sm text-ink-muted">
				The LEGO color of buttons, focus rings and the current page, on every browser pointed at
				this machine. Applies at once.
			</p>
			<div class="mt-3 rounded-control bg-well p-4">
				<ColorPicker bind:value={colorId} onchange={(id) => void setThemeColor(id)} />
			</div>
		</div>
	</div>
</Panel>
