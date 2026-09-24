# Testing an image before flashing it

`check.py image` mounts the image, so it runs on Linux as root (the build box).
`boot.sh` and `check.py boot` run there too, or on an Apple Silicon Mac, where
the VM runs at native speed.

```bash
sudo apt-get install qemu-system-arm qemu-utils     # or on a Mac: brew install qemu

sudo ./check.py image ../build/out/sorteros-v4.1.0-<date>.img   # seconds
./boot.sh ../build/out/sorteros-v4.1.0-<date>.img               # starts a VM in the background
./check.py boot --expect-default-model                           # follows first boot, then checks it
./check.py wifi                                                   # simulated Wi-Fi scenarios in the same VM
kill "$(cat work/qemu.pid)"
```

`REUSE=1 ./boot.sh <img>` boots the disk the last run left in `work/`, a
machine past its first boot: copy changed overlay files in over ssh and rerun
`check.py wifi` without waiting for first boot again.

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

`check.py wifi` then runs `wifi-sim.sh` in the same VM: `mac80211_hwsim`
gives it three simulated radios (the Pi's Wi-Fi, a home router, a phone, the
last two in their own network namespaces), and it walks the network decisions
end to end with the real NetworkManager, setup page and sorteros-network:
setup-site Wi-Fi with the right and the wrong password, the phone fixing it,
the phone typing a wrong password first (and the page saying so), a router
that comes back after the Pi, a cable plugged in during setup, and a network
name and password full of characters that break naive keyfiles. A restart
(the setup page joining a network, the service retrying saved ones) restarts
the service there instead of the VM. `test_network.py` covers the same
decisions across restarts in seconds against a fake:
`python3 -m unittest test_network`.

What it can't cover: anything that needs the board (the real Wi-Fi chip and
its driver, the NPU, cameras, the control boards, the boot loader and kernel
arguments actually taking effect). Those still need a card. The Orange Pi 5's
Wi-Fi in particular can neither scan nor join a network after it has
broadcast the setup network until it restarts, which the simulated radios
happily do.

Speed: on an x86_64 host QEMU emulates every instruction and first boot
(`uv sync`, `pnpm build`) takes one to two hours. On an arm64 Linux host with
KVM it runs at close to native speed.
