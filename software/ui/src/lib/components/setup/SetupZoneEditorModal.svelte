<script lang="ts">
	import ZoneSection from '$lib/components/settings/ZoneSection.svelte';
	import { createEventDispatcher } from 'svelte';

	type Channel = 'second' | 'third' | 'carousel' | 'class_top' | 'class_bottom';

	let {
		role
	}: {
		role: 'c_channel_2' | 'c_channel_3' | 'carousel' | 'classification_top' | 'classification_bottom';
	} = $props();

	const dispatch = createEventDispatcher<{ saved: void }>();

	function modalConfig(targetRole: string): { channels: Channel[] } {
		switch (targetRole) {
			case 'c_channel_2':
				return {
					channels: ['second']
				};
			case 'c_channel_3':
				return {
					channels: ['third']
				};
			case 'carousel':
				return {
					channels: ['carousel']
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


	<div>
	<ZoneSection
		channels={config.channels}
		wizardMode={true}
		on:saved={() => dispatch('saved')}
	/>
</div>
