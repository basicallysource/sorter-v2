<script lang="ts">
    import { onMount } from 'svelte';
    import HardDrive from '@lucide/svelte/icons/hard-drive';
    import Download from '@lucide/svelte/icons/download';
    import FilePen from '@lucide/svelte/icons/file-pen';
    import Alert from '$lib/components/Alert.svelte';
    import Button from '$lib/components/Button.svelte';
    import Checkbox from '$lib/components/Checkbox.svelte';
    import Field from '$lib/components/Field.svelte';
    import Input from '$lib/components/Input.svelte';
    import Panel from '$lib/components/Panel.svelte';
    import ProgressBar from '$lib/components/ProgressBar.svelte';
    import Textarea from '$lib/components/Textarea.svelte';
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
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || undefined,
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

            // requestPermission is in the File System Access API, not yet in the DOM types.
            const permission = await (
                handle as FileSystemFileHandle & {
                    requestPermission(options: { mode: 'readwrite' }): Promise<PermissionState>;
                }
            ).requestPermission({ mode: 'readwrite' });
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
    <title>SorterOS setup · basically</title>
</svelte:head>

<main class="mx-auto flex min-h-screen max-w-xl flex-col gap-(--gap-panels) px-4 py-8 sm:px-6">
    <header class="mb-4">
        <p class="label">basically</p>
        <h1 class="mt-1 text-2xl font-semibold tracking-tight text-ink">SorterOS setup</h1>
        <p class="mt-2 text-sm text-ink-muted">
            Configure the image for your Orange Pi before flashing. Nothing is uploaded to a
            server; everything happens here, in your browser.
        </p>
    </header>

    <Panel title="Image" description="The SorterOS image to customize before flashing.">
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
            class="flex w-full flex-col items-center justify-center gap-3 rounded-control px-4 py-8 text-center text-sm transition-colors
                {dragging ? 'bg-primary-soft' : 'bg-well'}"
            ondragover={onDragOver}
            ondragleave={onDragLeave}
            ondrop={onDrop}
        >
            <HardDrive size={24} class={dragging ? 'text-primary-ink' : 'text-ink-faint'} />
            {#if file}
                <span class="font-medium break-all text-ink">{file.name}</span>
                <Button size="sm" onclick={openFilePicker}>Change file</Button>
            {:else}
                <span class="text-ink-muted">Drop a <span class="font-mono">.img</span> file here, or</span>
                <Button size="sm" onclick={openFilePicker}>Browse</Button>
            {/if}
        </div>
    </Panel>

    <Panel title="Settings" description="All of them are optional.">
        <div class="flex flex-col gap-5">
            <Field
                label="Hostname"
                for="hostname"
                help="The device's name on your network, such as sorter.local."
            >
                <Input id="hostname" bind:value={hostname} autocomplete="off" spellcheck="false" />
            </Field>
            <Checkbox bind:checked={remember_hostname}>Remember the hostname on this device</Checkbox>

            <Field
                label="Wi-Fi network"
                for="ssid"
                help="The network's exact name. Leave it empty to use Ethernet."
            >
                <Input id="ssid" bind:value={ssid} autocomplete="off" spellcheck="false" />
            </Field>

            <Field
                label="Wi-Fi password"
                for="pw"
                help="Leave it empty only for an open network, or with Ethernet."
            >
                <Input
                    id="pw"
                    type={showPassword ? 'text' : 'password'}
                    bind:value={password}
                    autocomplete="off"
                >
                    {#snippet end()}
                        <Button
                            size="sm"
                            variant="ghost"
                            aria-pressed={showPassword}
                            onclick={() => (showPassword = !showPassword)}
                            >{showPassword ? 'Hide' : 'Show'}</Button
                        >
                    {/snippet}
                </Input>
            </Field>
            <Checkbox bind:checked={remember_password}>
                Remember the Wi-Fi password on this device
            </Checkbox>

            <Field
                label="SSH public key"
                for="ssh"
                help="Adds your key for password-free SSH after the first boot."
            >
                <Textarea
                    id="ssh"
                    bind:value={sshKey}
                    rows={3}
                    placeholder="ssh-ed25519 AAAA..."
                    class="font-mono"
                />
            </Field>

            <Field
                label="Tailscale auth key"
                for="tskey"
                help="Joins your Tailscale network on the first boot, tagged tag:sorter, so you can reach the machine without knowing its address."
            >
                <Input
                    id="tskey"
                    type={showTailscaleKey ? 'text' : 'password'}
                    bind:value={tailscaleKey}
                    placeholder="tskey-auth-..."
                    autocomplete="off"
                    class="font-mono"
                >
                    {#snippet end()}
                        <Button
                            size="sm"
                            variant="ghost"
                            aria-pressed={showTailscaleKey}
                            onclick={() => (showTailscaleKey = !showTailscaleKey)}
                            >{showTailscaleKey ? 'Hide' : 'Show'}</Button
                        >
                    {/snippet}
                </Input>
            </Field>
        </div>
    </Panel>

    <Panel title="Customize">
        <div class="flex flex-col gap-3">
            <Button
                variant="primary"
                icon={Download}
                class="w-full"
                loading={busy}
                onclick={handleDownloadPatch}
            >
                Customize and download a copy
            </Button>
            <Button icon={FilePen} class="w-full" disabled={busy} onclick={handlePatchInPlace}>
                Patch the original file in place
            </Button>
            <p class="text-sm text-ink-muted">
                Patching in place asks for write access to the file: pick the same image again. It
                needs a Chromium browser.
            </p>
            {#if busy && progress !== null}
                <ProgressBar value={Math.round(progress * 100)} label="Patching the image" />
            {/if}
            {#if status}
                <Alert tone={statusKind}>{status}</Alert>
            {/if}
        </div>
    </Panel>
</main>
