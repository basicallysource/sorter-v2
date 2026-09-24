#!/usr/bin/env bash
# Wi-Fi scenarios for sorteros-network, run as root inside a QEMU boot of the
# image (./check.py wifi copies and runs this). mac80211_hwsim gives the VM
# three simulated radios: the Pi's own Wi-Fi (NetworkManager's), a home router
# (hostapd + dnsmasq) and a phone, the last two in their own network
# namespaces so their traffic really crosses the simulated air. Ethernet stays
# up for ssh but stops being a way online (never-default), so the Pi has to
# get online over Wi-Fi. A restart (the setup page joining a network, or the
# service retrying saved ones) restarts sorteros-network here instead of the
# VM, and the retry comes after a minute instead of ten.
set -u
W=/tmp/wifisim
mkdir -p "$W"
pass=0
fail=0
ok() { echo "PASS $*"; pass=$((pass + 1)); }
bad() { echo "FAIL $*"; fail=$((fail + 1)); }
step() { echo "---- $*"; }
check() { local what=$1; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }
wait_for() { # seconds command...  (wall clock: a scan can take seconds)
    local t=$1 start=$SECONDS; shift
    while ((SECONDS - start < t)); do "$@" && { WAITED=$((SECONDS - start)); return 0; }; sleep 1; done
    WAITED=$t
    return 1
}

# ── radios ────────────────────────────────────────────────────────────────
KVER=$(uname -r)
POOL=https://ports.ubuntu.com/pool/main/l/linux
if ! lsmod | grep -q mac80211_hwsim; then
    step "loading mac80211_hwsim for $KVER"
    index=$(curl -fsSL "$POOL/")
    for pkg in linux-modules linux-modules-extra; do
        deb=$(grep -o "${pkg}-${KVER}_[^\"]*_arm64.deb" <<<"$index" | head -1)
        [ -n "$deb" ] || { echo "FAIL no $pkg package for $KVER"; exit 1; }
        [ -f "$W/$deb" ] || curl -fsSL -o "$W/$deb" "$POOL/$deb"
        dpkg-deb -x "$W/$deb" "$W/root"
    done
    depmod -b "$W/root" "$KVER"
    modprobe -d "$W/root" mac80211_hwsim radios=3 || { echo "FAIL could not load mac80211_hwsim"; exit 1; }
    sleep 2
fi
phy_of() { cat "/sys/class/net/$1/phy80211/name"; }
PI=wlan0
if ! ip netns list | grep -q router; then
    ROUTER_PHY=$(phy_of wlan1)
    PHONE_PHY=$(phy_of wlan2)
    ip netns add router
    ip netns add phone
    iw phy "$ROUTER_PHY" set netns name router
    iw phy "$PHONE_PHY" set netns name phone
fi
R() { ip netns exec router "$@"; }
P() { ip netns exec phone "$@"; }
RIF=$(R ls /sys/class/net | grep '^wlan' | head -1)
PIF=$(P ls /sys/class/net | grep '^wlan' | head -1)

ETH=$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2 == "ethernet" { print $1; exit }')
ETHCON=$(nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v d="$ETH" '$2 == d { print $1; exit }')
eth_default() { # yes|no
    local never=yes; [ "$1" = yes ] && never=no
    nmcli connection modify "$ETHCON" ipv4.never-default "$never" ipv6.never-default "$never"
    nmcli device reapply "$ETH" >/dev/null
}

mkdir -p /etc/systemd/system/sorteros-network.service.d
cat >/etc/systemd/system/sorteros-network.service.d/wifi-sim.conf <<'EOF'
[Service]
Environment="SORTEROS_REBOOT_CMD=systemctl restart --no-block sorteros-network" SORTEROS_RETRY_S=60
EOF
systemctl daemon-reload

# ── the home router ───────────────────────────────────────────────────────
router_up() { # [ssid] [password]  (given to hostapd as hex, so any bytes survive)
    local hex psk
    hex=$(python3 -c 'import sys; print(sys.argv[1].encode().hex())' "${1:-HomeNet}")
    psk=$(python3 -c 'import hashlib, sys; print(hashlib.pbkdf2_hmac("sha1", sys.argv[2].encode(), sys.argv[1].encode(), 4096, 32).hex())' "${1:-HomeNet}" "${2:-right-password}")
    cat >"$W/hostapd.conf" <<EOF
interface=$RIF
driver=nl80211
ssid2=$hex
hw_mode=g
channel=1
wpa=2
wpa_psk=$psk
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF
    R ip link set "$RIF" up
    R ip addr replace 192.168.77.1/24 dev "$RIF"
    R hostapd -B -P "$W/hostapd.pid" "$W/hostapd.conf" >/dev/null
    R dnsmasq --interface="$RIF" --bind-interfaces --port=0 --dhcp-range=192.168.77.50,192.168.77.99,1h \
        --dhcp-option=3,192.168.77.1 --pid-file="$W/dnsmasq.pid" --dhcp-leasefile="$W/leases"
}
router_down() {
    for f in "$W/hostapd.pid" "$W/dnsmasq.pid"; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
    sleep 1
}

# ── the phone ─────────────────────────────────────────────────────────────
setup_ssid() { P ip link set "$PIF" up; P iw dev "$PIF" scan 2>/dev/null | awk -F': ' '/SSID: SorterOS-Setup-/ { print $2; exit }'; }
setup_visible() { [ -n "$(setup_ssid)" ]; }
setup_gone() { ! setup_visible; }
phone_join() { # until the phone reaches the setup page (a scan can come back empty)
    local ssid i
    for i in 1 2 3 4 5 6; do
        ssid=$(setup_ssid)
        if [ -n "$ssid" ]; then
            P iw dev "$PIF" disconnect 2>/dev/null
            P iw dev "$PIF" connect "$ssid" && sleep 3 && P ip addr replace 10.42.0.77/24 dev "$PIF" &&
                P curl -s -m 5 -o /dev/null http://10.42.0.1/api/status && return 0
        fi
        sleep 3
    done
    echo "     (the phone couldn't reach the setup page)"
    return 1
}
phone_leave() { P iw dev "$PIF" disconnect 2>/dev/null; P ip addr flush dev "$PIF"; }
page() { P curl -s -m 15 "$@"; }
submit() { # ssid password
    page -X POST -H 'Content-Type: application/json' \
        -d "$(python3 -c 'import json, sys; print(json.dumps({"ssid": sys.argv[1], "password": sys.argv[2]}))' "$1" "$2")" \
        http://10.42.0.1/api/wifi-connect
}

# ── the Pi ────────────────────────────────────────────────────────────────
pi_reset() { # config text
    systemctl stop sorteros-network
    nmcli -t -f NAME,TYPE connection show | awk -F: '$2 == "802-11-wireless" { print $1 }' |
        while read -r n; do nmcli connection delete "$n" >/dev/null; done
    rm -rf /var/lib/sorteros/wifi-imported /var/lib/sorteros/join-pending.json /var/lib/sorteros/join-failed.json \
        /var/lib/sorteros/saved-retry-count /var/lib/sorteros/ip-announce.json /run/sorteros
    printf '%b' "$1" >/etc/sorteros-config.toml
    phone_leave
    wait_for 30 offline || echo "     (still online 30s after reset)"
}
net_start() { systemctl reset-failed sorteros-network 2>/dev/null; systemctl start sorteros-network; SINCE=$(date '+%F %T'); }
on_wifi() { ip -4 route show default | grep -q " dev $PI "; }
offline() { [ -z "$(ip -4 route show default)" ]; }
net_finished() { ! systemctl is-active -q sorteros-network; }
net_said() { journalctl -u sorteros-network --since "$SINCE" --no-pager | grep -q "$1"; }
saved_psk() { # ssid → the password NetworkManager holds for it
    local u
    for u in $(nmcli -t -f UUID,TYPE connection show | awk -F: '$2 == "802-11-wireless" { print $1 }'); do
        [ "$(nmcli --escape no -g 802-11-wireless.ssid connection show uuid "$u")" = "$1" ] &&
            nmcli --escape no -s -g 802-11-wireless-security.psk connection show uuid "$u"
    done
}
psk_is() { [ "$(saved_psk "$1")" = "$2" ]; }
never_broadcast() { ! net_said broadcasting; }

WIFI_OK='[wifi]\nssid = "HomeNet"\npassword = "right-password"\n'
eth_default no

step "1. setup site Wi-Fi, right password"
router_down
router_up
pi_reset "$WIFI_OK"
net_start
check "joins the network from the setup site" wait_for 150 on_wifi
echo "     joined after ${WAITED}s"
check "network service finishes" wait_for 30 net_finished
check "setup network never opened" never_broadcast

step "2. setup site Wi-Fi, wrong password; the phone fixes it"
pi_reset '[wifi]\nssid = "HomeNet"\npassword = "wrong-password"\n\n[tailscale]\nauth_key = "tskey-sim"\n'
net_start
check "setup network opens after the wrong password" wait_for 200 setup_visible
echo "     setup network after ${WAITED}s"
phone_join
check "setup page answers the phone" bash -c "ip netns exec phone curl -s -m 15 http://10.42.0.1/api/status | grep -q suggested_url"
submit HomeNet right-password >/dev/null
check "joins the network the phone gave it" wait_for 120 on_wifi
check "network service finishes" wait_for 30 net_finished
check "setup network closed" wait_for 30 setup_gone
check "NetworkManager has the new password, and only it" psk_is HomeNet right-password
check "config kept the setup site's Tailscale key" grep -q 'tskey-sim' /etc/sorteros-config.toml

step "3. no Wi-Fi given; the phone types a wrong password first"
pi_reset ''
net_start
check "setup network opens with nothing configured" wait_for 120 setup_visible
phone_join
submit HomeNet wrong-password >/dev/null
sleep 15
check "setup network comes back after the wrong password" wait_for 120 setup_visible
phone_join
check "setup page says the password was wrong" bash -c "ip netns exec phone curl -s -m 15 http://10.42.0.1/api/status | grep -q '\"reason\": *\"password\"'"
submit HomeNet right-password >/dev/null
check "then joins with the right one" wait_for 120 on_wifi
check "network service finishes" wait_for 30 net_finished

step "4. router slower than the Pi after a power cut"
router_down
pi_reset "$WIFI_OK"
net_start
check "setup network opens while the router is down" wait_for 200 setup_visible
router_up
check "rejoins when the router comes back (nobody on the setup network)" wait_for 360 on_wifi
echo "     rejoined ${WAITED}s after the router came back"
check "network service finishes" wait_for 30 net_finished

step "5. cable plugged in during setup"
router_down
pi_reset ''
net_start
check "setup network opens" wait_for 120 setup_visible
eth_default yes
check "network service finishes on the cable" wait_for 30 net_finished
check "setup network closed" wait_for 30 setup_gone

step "6. an odd network name and password from the phone"
eth_default no
router_down
ODD_SSID='Café Net/2 '
ODD_PSK=' back\slash pass'
router_up "$ODD_SSID" "$ODD_PSK"
pi_reset ''
net_start
check "setup network opens" wait_for 120 setup_visible
phone_join
submit "$ODD_SSID" "$ODD_PSK" >/dev/null
check "joins it" wait_for 120 on_wifi
check "NetworkManager holds the name and password exactly" psk_is "$ODD_SSID" "$ODD_PSK"

eth_default yes
router_down
rm -rf /etc/systemd/system/sorteros-network.service.d
systemctl daemon-reload
echo "DONE pass=$pass fail=$fail"
