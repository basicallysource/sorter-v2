#!/usr/bin/env bash
# Restore user homes that Armbian intentionally omits while packing images.

set -euo pipefail

KEYS=/etc/sorteros/bootstrap_authorized_keys
DEFAULT_PASSWORD=${SORTEROS_DEFAULT_PASSWORD:-sorteros}

set_login_password() {
    local user=$1
    local password=$2
    [ -n "$password" ] || return 0
    printf '%s:%s\n' "$user" "$password" | chpasswd
}

getent group plugdev >/dev/null || groupadd --system plugdev
getent group video >/dev/null || groupadd --system video
getent group render >/dev/null || groupadd --system render

if ! id -u orangepi >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash --groups sudo,plugdev,video,render orangepi
fi

usermod -aG sudo,plugdev,video,render orangepi
install -d -m 0750 -o orangepi -g orangepi /home/orangepi

set_login_password root "${SORTEROS_ROOT_PASSWORD:-$DEFAULT_PASSWORD}"
set_login_password orangepi "${SORTEROS_ORANGEPI_PASSWORD:-$DEFAULT_PASSWORD}"
rm -f /root/.not_logged_in_yet
rm -f /etc/profile.d/armbian-check-first-login.sh
rm -f /etc/profile.d/armbian-check-first-login-reboot.sh

if [ -s "$KEYS" ]; then
    install -d -m 0700 -o orangepi -g orangepi /home/orangepi/.ssh
    cat "$KEYS" >>/home/orangepi/.ssh/authorized_keys
    sort -u /home/orangepi/.ssh/authorized_keys -o /home/orangepi/.ssh/authorized_keys
    chmod 0600 /home/orangepi/.ssh/authorized_keys
    chown orangepi:orangepi /home/orangepi/.ssh/authorized_keys
fi
