<!--
	What a sorter shares, one row per stream: its name, an info icon that says
	what it is for, and at the right "Always" for a stream that cannot be turned
	off or a switch for one that can. The rows of a divided list in a flush
	Panel (Settings > Data, and the setup step).

	`reset` is asked for each stream: when it says a stream is not at its
	default (or at the value every Hive has), the row takes the primary's tint
	with a button that puts it back.
-->
<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import type { SharingStream } from '$lib/sharing/api';

	type Reset = { text: string; help?: string; onreset: () => void };

	let {
		streams,
		value,
		onchange,
		reset,
		disabled = false
	}: {
		streams: SharingStream[];
		// Whether a stream is on, for what is being shown.
		value: (stream: SharingStream) => boolean;
		onchange: (stream: SharingStream, on: boolean) => void;
		reset?: (stream: SharingStream) => Reset | null;
		disabled?: boolean;
	} = $props();
</script>

{#each streams as stream (stream.key)}
	{@const back = reset?.(stream) ?? null}
	<SettingRow
		label={stream.label}
		info={stream.info}
		changed={back !== null}
		defaultText={back?.text}
		defaultHelp={back?.help}
		onreset={back?.onreset}
	>
		{#if stream.required}
			<Badge>Always</Badge>
		{:else}
			<Switch
				checked={value(stream)}
				label={stream.label}
				{disabled}
				onchange={(on) => onchange(stream, on)}
			/>
		{/if}
	</SettingRow>
{/each}
