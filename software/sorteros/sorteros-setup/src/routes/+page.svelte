<script lang="ts">
    import { onMount } from 'svelte';
    import {
        patchImageFile,
        patchImageFileHandleInPlace,
        type SorterosConfig
    } from '$lib/img-patch';

    const HOSTNAME_STORAGE_KEY = 'sorteros_setup_hostname';
    const REMEMBER_HOSTNAME_STORAGE_KEY = 'sorteros_setup_remember_hostname';
    const PASSWORD_STORAGE_KEY = 'sorteros_setup_wifi_password';
    const REMEMBER_PASSWORD_STORAGE_KEY = 'sorteros_setup_remember_password';

    let file: File | null = $state(null);
    let hostname = $state('sorter');
    let remember_hostname = $state(false);
    let ssid = $state('');
    let password = $state('');
    let remember_password = $state(false);
    let sshKey = $state('');
    let tailscaleKey = $state('');
    let status = $state('');
    let statusKind: 'info' | 'success' | 'danger' = $state('info');
    let busy = $state(false);
    let progress = $state<number | null>(null); // null = indeterminate, 0–1 = determinate
    let file_input: HTMLInputElement | null = $state(null);

    onMount(() => {
        try {
            remember_hostname =
                window.localStorage.getItem(REMEMBER_HOSTNAME_STORAGE_KEY) === 'true';
            remember_password =
                window.localStorage.getItem(REMEMBER_PASSWORD_STORAGE_KEY) === 'true';

            if (remember_hostname) {
                hostname = window.localStorage.getItem(HOSTNAME_STORAGE_KEY) || hostname;
            }

            if (remember_password) {
                password = window.localStorage.getItem(PASSWORD_STORAGE_KEY) || '';
            }
        } catch (e) {
            console.error(e);
        }
    });

    $effect(() => {
        if (typeof window === 'undefined') return;
        try {
            window.localStorage.setItem(
                REMEMBER_HOSTNAME_STORAGE_KEY,
                remember_hostname ? 'true' : 'false'
            );
            if (remember_hostname) {
                window.localStorage.setItem(HOSTNAME_STORAGE_KEY, hostname);
            } else {
                window.localStorage.removeItem(HOSTNAME_STORAGE_KEY);
            }
        } catch (e) {
            console.error(e);
        }
    });

    $effect(() => {
        if (typeof window === 'undefined') return;
        try {
            window.localStorage.setItem(
                REMEMBER_PASSWORD_STORAGE_KEY,
                remember_password ? 'true' : 'false'
            );
            if (remember_password) {
                window.localStorage.setItem(PASSWORD_STORAGE_KEY, password);
            } else {
                window.localStorage.removeItem(PASSWORD_STORAGE_KEY);
            }
        } catch (e) {
            console.error(e);
        }
    });

    function buildConfig(): SorterosConfig {
        return {
            hostname,
            wifi: ssid ? { ssid, password } : undefined,
            ssh_authorized_key: sshKey || undefined,
            tailscale_auth_key: tailscaleKey || undefined
        };
    }

    async function handleDownloadPatch() {
        if (!file) {
            statusKind = 'danger';
            status = 'Pick an image file first.';
            return;
        }
        busy = true;
        progress = null;
        statusKind = 'info';
        status = 'Building customized image...';
        try {
            const blob = await patchImageFile(file, buildConfig());
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = file.name.replace(/\.img$/, '') + '-customized.img';
            a.click();
            statusKind = 'success';
            status = 'Customized copy downloaded. Flash that new file with balenaEtcher.';
        } catch (e: unknown) {
            statusKind = 'danger';
            status =
                e instanceof Error
                    ? `Error: ${e.message}`
                    : `Error: ${String(e)}`;
        } finally {
            busy = false;
            progress = null;
        }
    }

    async function handlePatchInPlace() {
        const picker = (window as Window & {
            showOpenFilePicker?: (options?: {
                multiple?: boolean;
                types?: Array<{
                    description?: string;
                    accept: Record<string, string[]>;
                }>;
            }) => Promise<FileSystemFileHandle[]>;
        }).showOpenFilePicker;

        if (!picker) {
            statusKind = 'danger';
            status = 'Patch in place requires a Chromium browser with File System Access support.';
            return;
        }

        busy = true;
        progress = null;
        statusKind = 'info';
        status = 'Opening image for in-place patch...';

        try {
            const [handle] = await picker({
                multiple: false,
                types: [
                    {
                        description: 'SorterOS image',
                        accept: {
                            'application/octet-stream': ['.img']
                        }
                    }
                ]
            });

            if (!handle) {
                throw new Error('No file selected.');
            }

            const permission = await handle.requestPermission({ mode: 'readwrite' });
            if (permission !== 'granted') {
                throw new Error('Write access was not granted.');
            }

            status = 'Scanning image for config region...';
            progress = 0;
            await patchImageFileHandleInPlace(handle, buildConfig(), (f) => { progress = f; });
            progress = 1;
            file = await handle.getFile();
            statusKind = 'success';
            status = 'Original image patched in place.';
        } catch (e: unknown) {
            statusKind = 'danger';
            status =
                e instanceof Error
                    ? `Error: ${e.message}`
                    : `Error: ${String(e)}`;
        } finally {
            busy = false;
            progress = null;
        }
    }

    function pickFile(e: Event) {
        const files = (e.currentTarget as HTMLInputElement).files;
        file = files?.[0] ?? null;
    }

    function openFilePicker() {
        file_input?.click();
    }

    let showPassword = $state(false);
    let showTailscaleKey = $state(false);

    let dragging = $state(false);

    function onDragOver(e: DragEvent) {
        e.preventDefault();
        dragging = true;
    }

    function onDragLeave() {
        dragging = false;
    }

    function onDrop(e: DragEvent) {
        e.preventDefault();
        dragging = false;
        const dropped = e.dataTransfer?.files?.[0];
        if (dropped) file = dropped;
    }
</script>

<svelte:head>
    <title>SorterOS Setup - basically</title>
</svelte:head>

<main class="mx-auto min-h-screen max-w-xl p-6">
    <header class="mb-10">
        <p class="text-text-muted text-xs font-semibold tracking-wider uppercase">basically</p>
        <h1 class="mt-1 text-2xl font-semibold">SorterOS Setup</h1>
        <p class="text-text-muted mt-2 text-sm">
            Configure the image for your Orange Pi before flashing. Nothing is
            uploaded to a server. Everything is done locally in your browser.
        </p>
    </header>

    <section class="space-y-4">
        <div>
            <label for="img" class="mb-2 block text-sm font-medium">SorterOS .img file</label>
            <p class="text-text-muted mb-2 text-xs">
                Select the SorterOS image you want to customize before flashing.
            </p>
            <input
                bind:this={file_input}
                id="img"
                type="file"
                accept=".img"
                onchange={pickFile}
                class="sr-only"
            />
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
                class="flex w-full cursor-default flex-col items-center justify-center gap-2 px-4 py-6 text-center text-sm transition-colors"
                style="border: 2px dashed {dragging ? 'var(--color-primary)' : '#d6d3cb'}; background: {dragging ? 'color-mix(in oklab, var(--color-primary) 6%, var(--color-surface))' : 'var(--color-surface)'};"
                ondragover={onDragOver}
                ondragleave={onDragLeave}
                ondrop={onDrop}
            >
                {#if file}
                    <span class="font-medium">{file.name}</span>
                    <button type="button" class="setup-button-secondary h-8 px-3 text-xs font-medium" onclick={openFilePicker}>
                        Change file
                    </button>
                {:else}
                    <span class="text-text-muted">Drop a <code>.img</code> file here, or</span>
                    <button type="button" class="setup-button-secondary h-8 px-3 text-xs font-medium" onclick={openFilePicker}>
                        Browse…
                    </button>
                {/if}
            </div>
        </div>

        <div>
            <label for="hostname" class="mb-2 block text-sm font-medium">Hostname</label>
            <p class="text-text-muted mb-2 text-xs">
                The device name on your network, such as <code>sorter.local</code>.
            </p>
            <input
                id="hostname"
                type="text"
                bind:value={hostname}
                class="setup-control text-sm"
            />
            <label class="mt-2 flex items-center gap-2 text-xs">
                <input
                    type="checkbox"
                    bind:checked={remember_hostname}
                    class="setup-toggle"
                />
                <span class="text-text-muted">Remember hostname on this device</span>
            </label>
        </div>

        <div>
            <label for="ssid" class="mb-2 block text-sm font-medium">Wi-Fi SSID</label>
            <p class="text-text-muted mb-2 text-xs">
                The exact name of your Wi-Fi network. Optional if you plan to use Ethernet.
            </p>
            <input
                id="ssid"
                type="text"
                bind:value={ssid}
                placeholder="Optional"
                class="setup-control text-sm"
            />
        </div>

        <div>
            <label for="pw" class="mb-2 block text-sm font-medium">Wi-Fi password</label>
            <p class="text-text-muted mb-2 text-xs">
                Leave this blank only if the Wi-Fi network is open or you are using Ethernet.
            </p>
            <div class="relative">
                <input
                    id="pw"
                    type={showPassword ? 'text' : 'password'}
                    bind:value={password}
                    autocomplete="off"
                    class="setup-control text-sm"
                    style="padding-right: 2.5rem;"
                />
                <button
                    type="button"
                    onclick={() => { showPassword = !showPassword; }}
                    class="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text transition-colors"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                    {#if showPassword}
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                    {:else}
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    {/if}
                </button>
            </div>
            <label class="mt-2 flex items-center gap-2 text-xs">
                <input
                    type="checkbox"
                    bind:checked={remember_password}
                    class="setup-toggle"
                />
                <span class="text-text-muted">Remember Wi-Fi password on this device</span>
            </label>
        </div>

        <div>
            <label for="ssh" class="mb-2 block text-sm font-medium">SSH public key</label>
            <p class="text-text-muted mb-2 text-xs">
                Optional. Adds your public key for password-free SSH access after first boot.
            </p>
            <textarea
                id="ssh"
                bind:value={sshKey}
                rows={3}
                placeholder="ssh-ed25519 AAAA..."
                class="setup-control font-mono text-sm"
            ></textarea>
        </div>

        <div>
            <label for="tskey" class="mb-2 block text-sm font-medium">Tailscale auth key</label>
            <p class="text-text-muted mb-2 text-xs">
                Optional. Joins your Tailscale network on first boot with tag <code>tag:sorter</code>,
                enabling remote access without knowing the device's IP.
            </p>
            <div class="relative">
                <input
                    id="tskey"
                    type={showTailscaleKey ? 'text' : 'password'}
                    bind:value={tailscaleKey}
                    autocomplete="off"
                    placeholder="tskey-auth-..."
                    class="setup-control font-mono text-sm"
                    style="padding-right: 2.5rem;"
                />
                <button
                    type="button"
                    onclick={() => { showTailscaleKey = !showTailscaleKey; }}
                    class="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text transition-colors"
                    aria-label={showTailscaleKey ? 'Hide key' : 'Show key'}
                >
                    {#if showTailscaleKey}
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                    {:else}
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    {/if}
                </button>
            </div>
        </div>

        <div class="space-y-2">
            <button
                onclick={handleDownloadPatch}
                disabled={busy}
                class="setup-button-primary text-sm"
            >
                Customize and download copy
            </button>
            <button
                onclick={handlePatchInPlace}
                disabled={busy}
                class="setup-button-secondary setup-button-full text-sm font-semibold"
            >
                Patch original file in place <span style="font-size: 0.8em; font-weight: 400; opacity: 0.75;">— Select the same file you uploaded again</span>
            </button>
            <p class="text-text-muted text-xs">
                The second button uses the browser file system API and will ask for write access.
            </p>
        </div>

        {#if busy && progress !== null}
            <div class="w-full overflow-hidden" style="height:4px; background: #e2e0db;">
                <div
                    class="h-full transition-all duration-200"
                    style="width: {Math.round(progress * 100)}%; background: var(--color-primary);"
                ></div>
            </div>
        {/if}

        {#if status}
            {@const kindToBorder = {
                info: 'border-text-muted/40',
                success: 'border-success/40',
                danger: 'border-danger/40'
            }}
            {@const kindToText = {
                info: 'text-text',
                success: 'text-success',
                danger: 'text-danger'
            }}
            <div
                class={'border bg-surface/40 p-3 text-sm ' +
                    kindToBorder[statusKind] +
                    ' ' +
                    kindToText[statusKind]}
                role="status"
            >
                {status}
            </div>
        {/if}
    </section>

    <footer class="text-text-muted mt-12 space-y-1 text-xs">
        <p>All fields except the image file are optional.</p>
    </footer>
</main>
