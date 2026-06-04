#!/bin/bash
# Armbian chroot customization hook for SorterOS Phase 0.
#
# Armbian copies this file into the image and runs it in chroot. The
# userpatches/overlay directory is mounted at /tmp/overlay, so the build wrapper
# places the SorterOS overlay and chroot apt installer there before compile.sh.

set -euo pipefail

RELEASE=$1
LINUXFAMILY=$2
BOARD=$3
BUILD_DESKTOP=$4
ARCH=${5:-arm64}

log() { echo "[sorteros-armbian-customize] $*"; }

copy_sorteros_overlay() {
	local entry
	local boot_entry

	for entry in /tmp/overlay/* /tmp/overlay/.[!.]* /tmp/overlay/..?*; do
		if [ ! -e "${entry}" ] && [ ! -L "${entry}" ]; then
			continue
		fi

		if [ "${entry}" = "/tmp/overlay/tmp" ]; then
			continue
		fi

		if [ "${entry}" = "/tmp/overlay/boot" ]; then
			mkdir -p /boot
			for boot_entry in /tmp/overlay/boot/* /tmp/overlay/boot/.[!.]* /tmp/overlay/boot/..?*; do
				if [ ! -e "${boot_entry}" ] && [ ! -L "${boot_entry}" ]; then
					continue
				fi
				if [ "$(basename "${boot_entry}")" = "dtb" ]; then
					continue
				fi
				cp -a "${boot_entry}" /boot/
			done
			continue
		fi

		cp -a "${entry}" /
	done
}

copy_dtb_overlay() {
	local dtb_dir
	local link_target

	if [ ! -d /tmp/overlay/boot/dtb ]; then
		return 0
	fi

	if [ -d /boot/dtb ]; then
		dtb_dir=/boot/dtb
	elif [ -L /boot/dtb ]; then
		link_target=$(readlink /boot/dtb)
		case "${link_target}" in
			/*) dtb_dir="${link_target}" ;;
			*) dtb_dir="/boot/${link_target}" ;;
		esac
		mkdir -p "${dtb_dir}"
	else
		dtb_dir=/boot/dtb
		mkdir -p "${dtb_dir}"
	fi

	log "copying SorterOS DTB overlay into ${dtb_dir}"
	cp -a /tmp/overlay/boot/dtb/. "${dtb_dir}/"
}

Main() {
	log "customizing release=${RELEASE} family=${LINUXFAMILY} board=${BOARD} desktop=${BUILD_DESKTOP} arch=${ARCH}"

	if [ -d /tmp/overlay ]; then
		log "copying SorterOS overlay"
		copy_sorteros_overlay
		copy_dtb_overlay
		chmod 1777 /tmp
	fi

	if [ -x /tmp/sorteros-chroot_apt.sh ]; then
		log "running SorterOS apt installer"
		/tmp/sorteros-chroot_apt.sh
	elif [ -x /tmp/overlay/tmp/sorteros-chroot_apt.sh ]; then
		log "running SorterOS apt installer from overlay"
		/tmp/overlay/tmp/sorteros-chroot_apt.sh
	else
		log "missing /tmp/sorteros-chroot_apt.sh"
		exit 1
	fi

	if [ -f /boot/dtb/rockchip/rk3588s-orangepi-cm5-tablet.dtb ]; then
		log "CM5 tablet DTB present"
	else
		log "WARNING: CM5 tablet DTB is missing from /boot/dtb/rockchip"
	fi
}

Main
