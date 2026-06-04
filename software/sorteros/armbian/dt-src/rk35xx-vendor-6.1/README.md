# Orange Pi CM5 Tablet DTS Source

These DTS files are the Phase 0 source for
`artifacts/rk3588s-orangepi-cm5-tablet.dtb`.

They are imported from the Orange Pi CM5 patch set in MichaIng's Armbian/DietPi
branch:

- Repository: `https://github.com/MichaIng/build.git`
- Branch: `orangepicm5`
- Commit: `85a312eaf21a4a867efac33a39181ff8be425b40`
- Source path: `patch/kernel/rk35xx-vendor-6.1/dt/`

The DTB is compiled against Armbian `linux-rockchip` vendor 6.1:

- Repository: `https://github.com/armbian/linux-rockchip.git`
- Branch: `rk-6.1-rkr5.1`
- Commit used for the current image: `713542620f7c9c6287ef11487748e7bae13a63df`

Regenerate it with:

```bash
software/sorteros/armbian/compile-cm5-tablet-dtb.sh \
  --kernel-tree /path/to/linux-rockchip-rk-6.1-rkr5.1
```
