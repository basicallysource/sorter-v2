<script lang="ts">
	import ChannelSection from '$lib/components/settings/ChannelSection.svelte';
	import type { ZoneChannelId } from '$lib/settings/stations';

	let {
		role,
		onsaved
	}: {
		role: 'c_channel_2' | 'c_channel_3' | 'carousel' | 'classification_channel';
		onsaved?: () => void;
	} = $props();

	const CHANNEL: Record<typeof role, ZoneChannelId> = {
		c_channel_2: 2,
		c_channel_3: 3,
		carousel: 4,
		classification_channel: 4
	};
</script>

<ChannelSection channel={CHANNEL[role]} wizard {onsaved} />
