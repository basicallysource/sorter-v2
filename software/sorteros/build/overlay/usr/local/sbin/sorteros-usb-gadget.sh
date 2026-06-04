#!/usr/bin/env bash
# Bring up a USB-C direct Ethernet fallback for headless first boot.

set -euo pipefail

TAG=sorteros-usb-gadget
CONNECTION=sorteros-usb-gadget
IFACE=usb0
DEVICE_IP=172.31.42.2/24
DHCP_RANGE_START=172.31.42.10
DHCP_RANGE_END=172.31.42.50
DHCP_NETMASK=255.255.255.0
DNSMASQ_PID=/run/sorteros-usb-gadget-dnsmasq.pid
DNSMASQ_LOG=/var/log/sorteros-usb-gadget-dnsmasq.log
DEV_ADDR=02:73:6f:72:42:02
HOST_ADDR=02:73:6f:72:42:01

log() {
	logger -t "${TAG}" -- "$*" || echo "[${TAG}] $*"
}

first_udc() {
	ls /sys/class/udc 2>/dev/null | head -n 1 || true
}

wait_for_udc() {
	local udc=""

	for _ in $(seq 1 20); do
		udc=$(first_udc)
		if [ -n "${udc}" ]; then
			printf '%s\n' "${udc}"
			return 0
		fi
		sleep 1
	done

	return 1
}

wait_for_interface() {
	for _ in $(seq 1 20); do
		if ip link show "${IFACE}" >/dev/null 2>&1; then
			return 0
		fi
		sleep 1
	done

	return 1
}

configure_networkmanager() {
	if ! command -v nmcli >/dev/null 2>&1; then
		return 1
	fi

	if nmcli -t -f NAME connection show | grep -qx "${CONNECTION}"; then
		nmcli connection modify "${CONNECTION}" \
			connection.interface-name "${IFACE}" \
			connection.autoconnect yes \
			ipv4.method manual \
			ipv4.addresses "${DEVICE_IP}" \
			ipv6.method ignore >/dev/null
	else
		nmcli connection add \
			type ethernet \
			ifname "${IFACE}" \
			con-name "${CONNECTION}" \
			connection.autoconnect yes \
			ipv4.method manual \
			ipv4.addresses "${DEVICE_IP}" \
			ipv6.method ignore >/dev/null
	fi

	nmcli connection up "${CONNECTION}" >/dev/null 2>&1 || true
}

configure_interface() {
	ip link set "${IFACE}" up || true
	configure_networkmanager || true
	ip addr replace "${DEVICE_IP}" dev "${IFACE}" || true
	ip link set "${IFACE}" up || true
}

start_dhcp() {
	if ! command -v dnsmasq >/dev/null 2>&1; then
		log "dnsmasq not installed; ${IFACE} is up with static ${DEVICE_IP}"
		return 0
	fi

	if [ -s "${DNSMASQ_PID}" ] && kill -0 "$(cat "${DNSMASQ_PID}")" 2>/dev/null; then
		log "dnsmasq already running for ${IFACE}"
		return 0
	fi

	rm -f "${DNSMASQ_PID}"
	dnsmasq \
		--conf-file=/dev/null \
		--interface="${IFACE}" \
		--bind-dynamic \
		--port=0 \
		--dhcp-authoritative \
		--dhcp-range="${DHCP_RANGE_START},${DHCP_RANGE_END},${DHCP_NETMASK},12h" \
		--dhcp-option=3,172.31.42.2 \
		--dhcp-option=6,172.31.42.2 \
		--pid-file="${DNSMASQ_PID}" \
		--leasefile-ro \
		--log-facility="${DNSMASQ_LOG}"
}

start() {
	local udc=""

	if [ ! -d /sys/class/udc ]; then
		log "no /sys/class/udc; USB gadget fallback unavailable on this kernel"
		return 0
	fi

	if ! udc=$(wait_for_udc); then
		log "no USB device controller appeared; skipping USB gadget fallback"
		return 0
	fi

	log "using USB device controller ${udc}"

	if ! modprobe g_ether dev_addr="${DEV_ADDR}" host_addr="${HOST_ADDR}" 2>/dev/null; then
		log "modprobe g_ether failed; skipping USB gadget fallback"
		return 0
	fi

	if ! wait_for_interface; then
		log "${IFACE} did not appear after g_ether load"
		return 0
	fi

	configure_interface
	start_dhcp
	log "${IFACE} ready at ${DEVICE_IP}; host should receive ${DHCP_RANGE_START}-${DHCP_RANGE_END}"
}

stop() {
	if [ -s "${DNSMASQ_PID}" ]; then
		kill "$(cat "${DNSMASQ_PID}")" 2>/dev/null || true
		rm -f "${DNSMASQ_PID}"
	fi

	if command -v nmcli >/dev/null 2>&1; then
		nmcli connection down "${CONNECTION}" >/dev/null 2>&1 || true
	fi

	modprobe -r g_ether 2>/dev/null || true
	log "stopped"
}

case "${1:-start}" in
	start)
		start
		;;
	stop)
		stop
		;;
	*)
		echo "Usage: $0 {start|stop}" >&2
		exit 2
		;;
esac
