<script lang="ts">
	import ZoneSection from '$lib/components/settings/ZoneSection.svelte';
	import type { EndstopConfig, StepperKey } from '$lib/settings/stations';
	import { createEventDispatcher } from 'svelte';

	type Channel = 'second' | 'third' | 'carousel' | 'class_top' | 'class_bottom';

	let {
		role
	}: {
		role: 'c_channel_2' | 'c_channel_3' | 'carousel' | 'classification_top' | 'classification_bottom';
	} = $props();

	const dispatch = createEventDispatcher<{ reviewed: void }>();

	function modalConfig(targetRole: string): {
		channels: Channel[];
		stepperKey?: StepperKey;
		stepperEndstop?: EndstopConfig;
	} {
		switch (targetRole) {
			case 'c_channel_2':
				return {
					channels: ['second'],
					stepperKey: 'c_channel_2'
				};
			case 'c_channel_3':
				return {
					channels: ['third'],
					stepperKey: 'c_channel_3'
				};
			case 'carousel':
				return {
					channels: ['carousel'],
					stepperKey: 'carousel',
					stepperEndstop: {
						configEndpoint: '/api/hardware-config/carousel',
						liveEndpoint: '/api/hardware-config/carousel/live',
						homeEndpoint: '/api/hardware-config/carousel/home',
						homeCancelEndpoint: '/api/hardware-config/carousel/home/cancel'
					}
				};
			case 'classification_top':
				return {
					channels: ['class_top']
				};
			case 'classification_bottom':
				return {
					channels: ['class_bottom']
				};
			default:
				return {
					channels: ['second']
				};
		}
	}

	const config = $derived(modalConfig(role));
</script>

<div onfocusout={() => dispatch('reviewed')}>
	<ZoneSection
		channels={config.channels}
		stepperKey={config.stepperKey}
		stepperEndstop={config.stepperEndstop}
	/>
</div>
