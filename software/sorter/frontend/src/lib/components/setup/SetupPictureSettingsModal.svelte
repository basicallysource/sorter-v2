<script lang="ts">
	import CameraPicture from '$lib/components/CameraPicture.svelte';
	import PictureSettingsSidebar from '$lib/components/settings/PictureSettingsSidebar.svelte';
	import { pictureSettingsEqual, type PictureSettings } from '$lib/settings/picture-settings';
	import type { CameraRole } from '$lib/settings/stations';
	import { roleView } from '$lib/video';

	type TransformMatrix = [number, number, number, number];
	type PicturePreviewState = {
		saved: PictureSettings;
		draft: PictureSettings;
	};

	let {
		role,
		label,
		source = null,
		hasCamera = true,
		onsaved
	}: {
		role: CameraRole;
		label: string;
		source?: number | string | null;
		hasCamera?: boolean;
		onsaved?: () => void;
	} = $props();

	let picturePreview = $state<PicturePreviewState | null>(null);
	let previewKey = $state('');

	$effect(() => {
		const nextKey = `${role}::${typeof source === 'string' ? source : source === null ? 'none' : source}`;
		if (nextKey === previewKey) return;
		previewKey = nextKey;
		picturePreview = null;
	});

	function multiplyTransformMatrices(
		left: TransformMatrix,
		right: TransformMatrix
	): TransformMatrix {
		return [
			left[0] * right[0] + left[1] * right[2],
			left[0] * right[1] + left[1] * right[3],
			left[2] * right[0] + left[3] * right[2],
			left[2] * right[1] + left[3] * right[3]
		];
	}

	function inverseTransformMatrix(matrix: TransformMatrix): TransformMatrix {
		return [matrix[0], matrix[2], matrix[1], matrix[3]];
	}

	function pictureTransformMatrix(settings: PictureSettings): TransformMatrix {
		let matrix: TransformMatrix = [1, 0, 0, 1];

		const rotationMatrix: Record<number, TransformMatrix> = {
			0: [1, 0, 0, 1],
			90: [0, -1, 1, 0],
			180: [-1, 0, 0, -1],
			270: [0, 1, -1, 0]
		};

		matrix = multiplyTransformMatrices(
			rotationMatrix[settings.rotation] ?? rotationMatrix[0],
			matrix
		);
		if (settings.flip_horizontal) {
			matrix = multiplyTransformMatrices([-1, 0, 0, 1], matrix);
		}
		if (settings.flip_vertical) {
			matrix = multiplyTransformMatrices([1, 0, 0, -1], matrix);
		}
		return matrix;
	}

	function previewTransformStyle(): string {
		if (!picturePreview || pictureSettingsEqual(picturePreview.saved, picturePreview.draft))
			return '';

		const relativeMatrix = multiplyTransformMatrices(
			pictureTransformMatrix(picturePreview.draft),
			inverseTransformMatrix(pictureTransformMatrix(picturePreview.saved))
		);

		const isIdentity =
			relativeMatrix[0] === 1 &&
			relativeMatrix[1] === 0 &&
			relativeMatrix[2] === 0 &&
			relativeMatrix[3] === 1;

		if (isIdentity) return '';
		return `transform: matrix(${relativeMatrix[0]}, ${relativeMatrix[2]}, ${relativeMatrix[1]}, ${relativeMatrix[3]}, 0, 0); transform-origin: center center;`;
	}

	function handleSidebarSaved() {
		picturePreview = null;
		onsaved?.();
	}
</script>

<!-- The picture beside its settings; below xl, the settings under it. -->
<div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem] xl:items-start">
	<div class="dark relative min-h-[20rem] overflow-hidden rounded-control bg-media sm:min-h-[28rem]">
		{#if hasCamera}
			<CameraPicture
				view={roleView(role)}
				alt={label}
				class="absolute inset-0 h-full w-full"
				style={previewTransformStyle()}
			/>
		{:else}
			<p class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-ink-muted">
				Choose a camera first to preview its picture.
			</p>
		{/if}
	</div>
	<PictureSettingsSidebar
		{role}
		{label}
		{source}
		{hasCamera}
		showHeader={false}
		primaryActionLabel="Confirm"
		allowPrimaryActionWithoutChanges={true}
		onSaved={handleSidebarSaved}
		onPreviewChange={(roleName, savedSettings, draftSettings) => {
			void roleName;
			picturePreview = {
				saved: savedSettings,
				draft: draftSettings
			};
		}}
	/>
</div>
