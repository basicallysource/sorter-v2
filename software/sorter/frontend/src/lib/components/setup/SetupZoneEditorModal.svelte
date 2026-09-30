<script lang="ts">
	import ZoneSection from '$lib/components/settings/ZoneSection.svelte';

	type Channel =
		| 'second'
		| 'third'
		| 'carousel'
		| 'classification_channel';

	let {
		role,
		onsaved
	}: {
		role: 'c_channel_2' | 'c_channel_3' | 'carousel' | 'classification_channel';
		onsaved?: () => void;
	} = $props();

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
			case 'classification_channel':
				return {
					channels: ['classification_channel']
				};
			default:
				return {
					channels: ['second']
				};
		}
	}

	const config = $derived(modalConfig(role));
</script>

<ZoneSection channels={config.channels} wizardMode={true} {onsaved} />
