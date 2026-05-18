<script lang="ts">
    import { patchImageFile, type SorterosConfig } from '$lib/img-patch';

    let file: File | null = $state(null);
    let hostname = $state('sorter');
    let ssid = $state('');
    let password = $state('');
    let sshKey = $state('');
    let status = $state('');
    let statusKind: 'info' | 'success' | 'danger' = $state('info');
    let busy = $state(false);
    let file_input: HTMLInputElement | null = $state(null);

    async function handlePatch() {
        if (!file) {
            statusKind = 'danger';
            status = 'Pick an image file first.';
            return;
        }
        busy = true;
        statusKind = 'info';
        status = 'Patching image...';
        try {
            const cfg: SorterosConfig = {
                hostname,
                wifi: ssid ? { ssid, password } : undefined,
                ssh_authorized_key: sshKey || undefined
            };
            const blob = await patchImageFile(file, cfg);
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = file.name.replace(/\.img$/, '') + '-customized.img';
            a.click();
            statusKind = 'success';
            status = 'Done. Flash with balenaEtcher.';
        } catch (e: unknown) {
            statusKind = 'danger';
            status =
                e instanceof Error
                    ? `Error: ${e.message}`
                    : `Error: ${String(e)}`;
        } finally {
            busy = false;
        }
    }

    function pickFile(e: Event) {
        const files = (e.currentTarget as HTMLInputElement).files;
        file = files?.[0] ?? null;
    }

    function openFilePicker() {
        file_input?.click();
    }
</script>

<svelte:head>
    <title>sorter — setup</title>
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
            <div class="setup-control flex items-center gap-3 px-3 text-sm">
                <button type="button" class="setup-button-secondary h-9 px-3 text-sm font-medium" onclick={openFilePicker}>
                    Choose file
                </button>
                <span class:text-text-muted={!file} class="min-w-0 truncate">
                    {file ? file.name : 'No file chosen'}
                </span>
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
            <input
                id="pw"
                type="password"
                bind:value={password}
                autocomplete="off"
                class="setup-control text-sm"
            />
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

        <button
            onclick={handlePatch}
            disabled={busy}
            class="setup-button-primary text-sm"
        >
            Customize &amp; download
        </button>

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
        <p>
            Leave the Wi-Fi SSID blank to make the sorter boot into AP mode. You can
            join its hotspot from your phone and choose a network there.
        </p>
    </footer>
</main>
