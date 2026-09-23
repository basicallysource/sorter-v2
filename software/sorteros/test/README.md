# Testing an image before flashing it

Two checks, both run on the Linux box that built the image.

```bash
sudo apt-get install qemu-system-arm qemu-utils sshpass

sudo ./check.py image ../build/out/sorteros-v4.1.0-<date>.img   # seconds
./boot.sh ../build/out/sorteros-v4.1.0-<date>.img               # starts a VM in the background
./check.py boot --expect-default-model                           # follows first boot, then checks it
kill "$(cat work/qemu.pid)"
```

`check.py image` reads the image directly: ext4 `data=ordered`, `errors=panic`,
the kernel arguments that let a headless machine repair and reboot itself,
the hostname, which services are enabled, no git-lfs, the portal baked in.

`boot.sh` boots the image's root filesystem in QEMU with a stock Ubuntu arm64
kernel (the Orange Pi kernel only runs on the board) behind a user-mode
network, as a machine plugged into Ethernet with no hardware attached. It
never modifies the image. `check.py boot` then follows the first-boot status
page stage by stage until the Sorter UI takes over port 80, and checks the
backend answers, that the checked-out code is the newest `sorter/stable/v*`
tag (or `--expect-ref`), that Hive's default model landed on every channel,
and, over SSH, the hostname, avahi, and that no stage gave up.

What it can't cover: anything that needs the board (Wi-Fi and the captive
portal, the NPU, cameras, the control boards, the boot loader and kernel
arguments actually taking effect). Those still need a card.

Speed: on an x86_64 host QEMU emulates every instruction and first boot
(`uv sync`, `pnpm build`) takes one to two hours. On an arm64 Linux host with
KVM it runs at close to native speed.
