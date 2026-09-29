<script lang="ts">
	import LiveImage from '$lib/components/LiveImage.svelte';
	import PictureSettingsSidebar from '$lib/components/settings/PictureSettingsSidebar.svelte';
	import { pictureSettingsEqual, type PictureSettings } from '$lib/settings/picture-settings';
	import type { CameraRole } from '$lib/settings/stations';
	import { roleView } from '$lib/video';
	import { createEventDispatcher } from 'svelte';

	type TransformMatrix = [number, number, number, number];
	type PicturePreviewState = {
		saved: PictureSettings;
		draft: PictureSettings;
	};

	let {
		role,
		label,
		source = null,
		hasCamera = true
	}: {
		role: CameraRole;
		label: string;
		source?: number | string | null;
		hasCamera?: boolean;
	} = $props();

	const dispatch = createEventDispatcher<{ saved: void }>();

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
		dispatch('saved');
	}
</script>

<div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem] xl:items-start">
	<div class="flex min-w-0 flex-col gap-3">
		<div class="relative overflow-hidden bg-black">
			<div
				class="relative min-h-[24rem] sm:min-h-[30rem] lg:min-h-[36rem] xl:min-h-[42rem]"
			>
				{#if hasCamera}
					<LiveImage
						view={roleView(role, false, false)}
						alt={label}
						class="absolute inset-0 h-full w-full object-contain"
						style={previewTransformStyle()}
					/>
				{:else}
					<div
						class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-white/80"
					>
						<div class="max-w-sm rounded-control bg-black/55 px-4 py-3">
							Assign a camera first so you can preview picture settings.
						</div>
					</div>
				{/if}
			</div>
		</div>
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
