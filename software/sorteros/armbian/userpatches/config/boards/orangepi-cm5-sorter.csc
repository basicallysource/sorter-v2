# Experimental Orange Pi CM5 Tablet board for SorterOS Phase 0.
#
# Armbian main currently has Orange Pi 5/5 Plus RK3588 board files but no
# Orange Pi CM5 Tablet board file. Use OrangePi's vendor U-Boot defconfig for
# the tablet baseboard, then point the kernel at the CM5 tablet DTB copied into
# the image by build-sorteros-armbian-cm5.sh.

BOARD_NAME="Orange Pi CM5 Sorter"
BOARD_VENDOR="xunlong"
BOARDFAMILY="rockchip-rk3588"
BOARD_MAINTAINER="sorter"
INTRODUCED="2026"
BOOTCONFIG="orangepi_cm5_tablet_defconfig"
BOOT_SOC="rk3588"
KERNEL_TARGET="vendor"
KERNEL_TEST_TARGET="vendor"
FULL_DESKTOP="no"
BOOT_LOGO="desktop"
BOOT_FDT_FILE="rockchip/rk3588s-orangepi-cm5-tablet.dtb"
BOOT_SCENARIO="spl-blobs"
BOOT_SUPPORT_SPI="yes"
BOOT_SPI_RKSPI_LOADER="yes"
IMAGE_PARTITION_TABLE="gpt"

declare -g UEFI_EDK2_BOARD_ID="orangepi-5"

function post_family_config_branch_vendor__orangepi_cm5_sorter_use_vendor_uboot() {
	display_alert "$BOARD" "OrangePi CM5 Tablet vendor U-Boot for $BOARD - $BRANCH" "info"

	declare -g BOOTCONFIG="orangepi_cm5_tablet_defconfig"
	declare -g BOOTSOURCE="https://github.com/orangepi-xunlong/u-boot-orangepi.git"
	declare -g BOOTBRANCH="branch:v2017.09-rk3588"
	declare -g BOOTPATCHDIR="legacy"
	declare -g BOOTDIR="u-boot-orangepi-rk3588"
}

function post_family_tweaks__orangepi_cm5_sorter_naming_audios() {
	display_alert "$BOARD" "Renaming Orange Pi CM5 audio devices" "info"

	mkdir -p "$SDCARD/etc/udev/rules.d/"
	echo 'SUBSYSTEM=="sound", ENV{ID_PATH}=="platform-hdmi0-sound", ENV{SOUND_DESCRIPTION}="HDMI0 Audio"' > "$SDCARD/etc/udev/rules.d/90-naming-audios.rules"
	echo 'SUBSYSTEM=="sound", ENV{ID_PATH}=="platform-dp0-sound", ENV{SOUND_DESCRIPTION}="DP0 Audio"' >> "$SDCARD/etc/udev/rules.d/90-naming-audios.rules"

	return 0
}
