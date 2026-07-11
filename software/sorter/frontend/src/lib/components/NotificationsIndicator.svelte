<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		notifications,
		type AppNotification,
		type NotificationColor
	} from '$lib/stores/notifications.svelte';
	import { Bell, X } from 'lucide-svelte';

	let open = $state(false);

	const active = $derived(notifications.active);
	const count = $derived(active.length);
	const single = $derived(count === 1 ? active[0] : null);

	const colorText: Record<NotificationColor, string> = {
		success: 'text-success',
		primary: 'text-primary',
		warning: 'text-warning',
		danger: 'text-danger'
	};

	const TriggerIcon = $derived(single?.icon ?? Bell);
	const triggerColor = $derived(single ? colorText[single.color] : 'text-text-muted');

	function activate(n: AppNotification): void {
		open = false;
		if (n.href) void goto(n.href);
	}

	function dismiss(event: MouseEvent, n: AppNotification): void {
		event.stopPropagation();
		notifications.dismiss(n.id);
		if (notifications.active.length === 0) open = false;
	}
</script>

{#if count > 0}
	<div
		class="relative flex"
		role="presentation"
		onmouseenter={() => (open = true)}
		onmouseleave={() => (open = false)}
	>
		<button
			type="button"
			class="relative flex items-center p-2 transition-colors hover:bg-bg {triggerColor}"
			title={single ? single.title : `${count} notifications`}
			onclick={() => (single ? activate(single) : (open = !open))}
		>
			<TriggerIcon size={18} />
			{#if count > 1}
				<span
					class="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center bg-primary px-1 text-xs font-semibold text-primary-contrast"
				>
					{count}
				</span>
			{/if}
		</button>

		{#if open}
			<div class="absolute top-full right-0 z-50 mt-1 w-[300px] border border-border bg-surface shadow-lg">
				<div
					class="px-3 pt-2.5 pb-1.5 text-xs font-semibold tracking-wider text-text-muted uppercase"
				>
					Notifications
				</div>
				<ul class="flex flex-col">
					{#each active as n (n.id)}
						{@const Icon = n.icon}
						<li class="flex items-start gap-2.5 border-t border-border px-3 py-2.5">
							<button
								type="button"
								class="flex min-w-0 flex-1 items-start gap-2.5 text-left"
								onclick={() => activate(n)}
							>
								{#if Icon}
									<Icon size={16} class="mt-0.5 shrink-0 {colorText[n.color]}" />
								{/if}
								<span class="min-w-0 flex-1">
									<span class="block text-sm font-medium text-text">{n.title}</span>
									{#if n.content}
										<span class="mt-0.5 block text-sm text-text-muted">{n.content}</span>
									{/if}
								</span>
							</button>
							<button
								type="button"
								class="shrink-0 p-0.5 text-text-muted transition-colors hover:text-text"
								title="Dismiss"
								onclick={(event) => dismiss(event, n)}
							>
								<X size={14} />
							</button>
						</li>
					{/each}
				</ul>
			</div>
		{/if}
	</div>
{/if}
