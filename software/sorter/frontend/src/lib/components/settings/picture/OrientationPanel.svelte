<script lang="ts">
	import type { PictureSettings } from '$lib/settings/picture-settings';

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

<div class="grid gap-2 border-t border-border pt-3">
	<div class="text-[11px] font-semibold tracking-wider text-text-muted uppercase">Orientation</div>
	<div class="grid gap-2">
		<div>
			<div class="mb-1 text-xs font-medium text-text">Rotate</div>
			<div class="grid grid-cols-4 gap-1">
				{#each ROTATION_OPTIONS as rotation}
					<button
						onclick={() => onUpdateRotation(rotation)}
						class={`inline-flex items-center justify-center border px-2 py-2 text-xs font-medium transition-colors ${
							draftSettings.rotation === rotation
								? 'border-primary bg-primary text-primary-contrast hover:bg-primary-hover'
								: 'border-border bg-surface text-text hover:bg-bg'
						}`}
						aria-pressed={draftSettings.rotation === rotation}
					>
						{rotation}deg
					</button>
				{/each}
			</div>
		</div>
		<div>
			<div class="mb-1 text-xs font-medium text-text">Mirror</div>
			<div class="grid grid-cols-2 gap-1">
				<button
					onclick={() => onUpdateBoolean('flip_horizontal', !draftSettings.flip_horizontal)}
					class={`inline-flex items-center justify-center border px-2 py-2 text-xs font-medium transition-colors ${
						draftSettings.flip_horizontal
							? 'border-primary bg-primary text-primary-contrast hover:bg-primary-hover'
							: 'border-border bg-surface text-text hover:bg-bg'
					}`}
					aria-pressed={draftSettings.flip_horizontal}
				>
					Flip Horizontally
				</button>
				<button
					onclick={() => onUpdateBoolean('flip_vertical', !draftSettings.flip_vertical)}
					class={`inline-flex items-center justify-center border px-2 py-2 text-xs font-medium transition-colors ${
						draftSettings.flip_vertical
							? 'border-primary bg-primary text-primary-contrast hover:bg-primary-hover'
							: 'border-border bg-surface text-text hover:bg-bg'
					}`}
					aria-pressed={draftSettings.flip_vertical}
				>
					Flip Vertically
				</button>
			</div>
		</div>
	</div>
</div>
