<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		notifications,
		type AppNotification,
		type NotificationColor
	} from '$lib/stores/notifications.svelte';
	import { ChevronDown, X } from 'lucide-svelte';

	const active = $derived(notifications.active);
	const primary = $derived(active[0] ?? null);
	const rest = $derived(active.slice(1));

	// The dropdown (for the extra notifications) closes on a short delay so moving
	// the mouse from the box across the small gap into the menu doesn't dismiss it.
	let menuOpen = $state(false);
	let closeTimer: ReturnType<typeof setTimeout> | null = null;

	function openMenu(): void {
		if (closeTimer) {
			clearTimeout(closeTimer);
			closeTimer = null;
		}
		menuOpen = true;
	}
	function scheduleClose(): void {
		if (closeTimer) clearTimeout(closeTimer);
		closeTimer = setTimeout(() => {
			menuOpen = false;
			closeTimer = null;
		}, 160);
	}

	// Washed-out token style (thin border + faint tint), matching the Alert /
	// "Active" pills used across the site. The icon carries the saturated color.
	const boxClass: Record<NotificationColor, string> = {
		success: 'border border-success/40 bg-success/[0.08] text-text hover:bg-success/[0.14]',
		primary: 'border border-primary/40 bg-primary/[0.08] text-text hover:bg-primary/[0.14]',
		warning: 'border border-warning/50 bg-warning/[0.1] text-text hover:bg-warning/[0.16]',
		danger: 'border border-danger/40 bg-danger/[0.08] text-text hover:bg-danger/[0.14]'
	};
	const iconClass: Record<NotificationColor, string> = {
		success: 'text-success',
		primary: 'text-primary',
		warning: 'text-warning',
		danger: 'text-danger'
	};

	function activate(n: AppNotification): void {
		menuOpen = false;
		if (n.href) void goto(n.href);
	}
	function dismiss(event: MouseEvent, n: AppNotification): void {
		event.stopPropagation();
		notifications.dismiss(n.id);
		if (notifications.active.length === 0) menuOpen = false;
	}
</script>

{#if primary}
	<div
		class="relative flex"
		role="presentation"
		onmouseenter={openMenu}
		onmouseleave={scheduleClose}
	>
		<div class="group relative flex">
			<button
				type="button"
				class="flex items-center gap-1.5 px-2.5 py-1 text-sm transition-colors {boxClass[
					primary.color
				]}"
				title={primary.content ?? primary.title}
				onclick={() => activate(primary)}
			>
				{#if primary.icon}
					{@const Icon = primary.icon}
					<Icon size={15} class={iconClass[primary.color]} />
				{/if}
				{primary.title}
				{#if rest.length > 0}
					<span class="ml-0.5 flex items-center gap-0.5 border-l border-border pl-1.5 text-text-muted">
						+{rest.length}
						<ChevronDown size={12} />
					</span>
				{/if}
			</button>

			<!-- Hover-reveal dismiss for the primary notification. -->
			<button
				type="button"
				class="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center border border-border bg-surface text-text opacity-0 transition-opacity hover:bg-bg group-hover:opacity-100 focus:opacity-100"
				title="Dismiss"
				onclick={(event) => dismiss(event, primary)}
			>
				<X size={11} />
			</button>
		</div>

		{#if menuOpen && rest.length > 0}
			<div class="absolute top-full right-0 z-50 mt-1 w-[280px] border border-border bg-surface shadow-lg">
				<ul class="flex flex-col">
					{#each rest as n (n.id)}
						{@const Icon = n.icon}
						<li class="flex items-start gap-2.5 border-b border-border px-3 py-2.5 last:border-b-0">
							<button
								type="button"
								class="flex min-w-0 flex-1 items-start gap-2.5 text-left"
								onclick={() => activate(n)}
							>
								{#if Icon}
									<Icon size={16} class="mt-0.5 shrink-0 text-text-muted" />
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
