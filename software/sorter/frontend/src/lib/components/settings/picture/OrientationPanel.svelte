<script lang="ts">
	import type { PictureSettings } from '$lib/settings/picture-settings';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';

	type BooleanSettingKey = 'flip_horizontal' | 'flip_vertical';

	let {
		draftSettings,
		onUpdateRotation,
		onUpdateBoolean
	}: {
		draftSettings: PictureSettings;
		onUpdateRotation: (value: number) => void;
		onUpdateBoolean: (key: BooleanSettingKey, value: boolean) => void;
	} = $props();

	const ROTATION_OPTIONS = [0, 90, 180, 270] as const;
</script>

<section class="flex flex-col gap-3 px-(--pad-panel) py-4">
	<h3 class="label">Orientation</h3>
	<SegmentedControl
		label="Rotate"
		full
		value={String(draftSettings.rotation)}
		options={ROTATION_OPTIONS.map((r) => ({ value: String(r), label: `${r}°` }))}
		onchange={(r) => onUpdateRotation(Number(r))}
	/>
	<div class="flex flex-wrap gap-x-5 gap-y-2">
		<Checkbox
			checked={draftSettings.flip_horizontal}
			onchange={() => onUpdateBoolean('flip_horizontal', !draftSettings.flip_horizontal)}
		>
			Flip horizontally
		</Checkbox>
		<Checkbox
			checked={draftSettings.flip_vertical}
			onchange={() => onUpdateBoolean('flip_vertical', !draftSettings.flip_vertical)}
		>
			Flip vertically
		</Checkbox>
	</div>
</section>
