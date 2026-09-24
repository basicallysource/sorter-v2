#!/usr/bin/env bash
# Wi-Fi scenarios for sorteros-network, run as root inside a QEMU boot of the
# image (./check.py wifi copies and runs this). mac80211_hwsim gives the VM
# three simulated radios: the Pi's own Wi-Fi (NetworkManager's), a home router
# (hostapd + dnsmasq) and a phone, the last two in their own network
# namespaces so their traffic really crosses the simulated air. The router
# reaches the internet through the VM's own connection (a veth and NAT), so
# "online" means here what it means in a house: the internet answers. The
# VM's Ethernet stays up for ssh but stops being a way online (never-default)
# unless a scenario plugs the cable in.
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

# ── radios and kernel modules ─────────────────────────────────────────────
KVER=$(uname -r)
POOL=https://ports.ubuntu.com/pool/main/l/linux
if [ ! -d "$W/root/lib/modules/$KVER" ]; then
    step "fetching the modules the VM's kernel lacks, for $KVER"
    index=$(curl -fsSL "$POOL/")
    for pkg in linux-modules linux-modules-extra; do
        deb=$(grep -o "${pkg}-${KVER}_[^\"]*_arm64.deb" <<<"$index" | head -1)
        [ -n "$deb" ] || { echo "FAIL no $pkg package for $KVER"; exit 1; }
        [ -f "$W/$deb" ] || curl -fsSL -o "$W/$deb" "$POOL/$deb"
        dpkg-deb -x "$W/$deb" "$W/root"
    done
    depmod -b "$W/root" "$KVER"
fi
# Two channels: the simulated radio may broadcast on one while it joins on
# another. (The AP6275P moves its setup network to the joined network's
# channel instead; either way the phone keeps the page.)
lsmod | grep -q mac80211_hwsim || { modprobe -d "$W/root" mac80211_hwsim radios=3 channels=2 && sleep 2; } ||
    { echo "FAIL could not load mac80211_hwsim"; exit 1; }
# The setup network's fence, its port 80 redirect, and the router's NAT.
for m in nf_tables nft_counter nft_compat nf_conntrack xt_conntrack xt_tcpudp nf_nat nft_chain_nat \
    xt_REDIRECT xt_MASQUERADE xt_nat veth; do
    lsmod | grep -q "^$m " || modprobe -d "$W/root" "$m" 2>/dev/null || modprobe "$m" 2>/dev/null || true
done
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
mkdir -p /etc/netns/phone && echo "nameserver 10.42.0.1" >/etc/netns/phone/resolv.conf  # the phone asks the setup network
R() { ip netns exec router "$@"; }
P() { ip netns exec phone "$@"; }
RIF=$(R ls /sys/class/net | grep '^wlan' | head -1)
PIF=$(P ls /sys/class/net | grep '^wlan' | head -1)

ETH=$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2 == "ethernet" { print $1; exit }')
ETHCON=$(nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v d="$ETH" '$2 == d { print $1; exit }')
ETHGW=$(ip -4 route show default dev "$ETH" | awk '{ print $3; exit }')
ETHGW=${ETHGW:-10.0.2.2}
eth_default() { # yes|no: the cable is a way online, or only for ssh
    local never=yes; [ "$1" = yes ] && never=no
    nmcli connection modify "$ETHCON" ipv4.never-default "$never" ipv6.never-default "$never"
    nmcli device reapply "$ETH" >/dev/null
    router_uplink  # a reapply drops every route on the device NetworkManager didn't make
}
router_uplink() { ip route replace default via "$ETHGW" dev "$ETH" table 100; }
cable_internet() { # yes|no: the cable's own traffic (not the router's) reaches the internet
    iptables -D OUTPUT -o "$ETH" -p tcp --dport 80 -j REJECT 2>/dev/null
    [ "$1" = no ] && iptables -I OUTPUT -o "$ETH" -p tcp --dport 80 -j REJECT
    nmcli networking connectivity check >/dev/null
}

# The router's uplink: a veth into the VM, NAT out of the VM's own
# connection, routed by the router's traffic's source so it never loops back
# through the Pi's Wi-Fi.
if ! ip link show rtr0 >/dev/null 2>&1; then
    ip link add rtr0 type veth peer name rtr1
    nmcli device set rtr0 managed no 2>/dev/null
    ip link set rtr1 netns router
    ip addr add 10.99.0.1/24 dev rtr0
    ip link set rtr0 up
    R ip addr add 10.99.0.2/24 dev rtr1
    R ip link set rtr1 up
    R ip link set lo up
    sysctl -qw net.ipv4.ip_forward=1
    R sysctl -qw net.ipv4.ip_forward=1
    ip rule add iif rtr0 lookup 100 pref 100
    router_uplink
    iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o "$ETH" -j MASQUERADE
    R iptables -t nat -A POSTROUTING -s 192.168.77.0/24 -o rtr1 -j MASQUERADE
fi

# ── the home router ───────────────────────────────────────────────────────
router_up() { # [ssid] [password] [wpa2|open|sae|mixed]; HIDDEN=1 hides it, NO_DHCP=1 gives no addresses, NO_INTERNET=1 no uplink
    local ssid=${1:-HomeNet} pw=${2:-right-password} mode=${3:-wpa2} hex psk
    hex=$(python3 -c 'import sys; print(sys.argv[1].encode().hex())' "$ssid")
    psk=$(python3 -c 'import hashlib, sys; print(hashlib.pbkdf2_hmac("sha1", sys.argv[2].encode(), sys.argv[1].encode(), 4096, 32).hex())' "$ssid" "$pw")
    R ip link set "$RIF" up
    R ip addr replace 192.168.77.1/24 dev "$RIF"
    R ip route del default 2>/dev/null
    [ "${NO_INTERNET:-0}" = 1 ] || R ip route add default via 10.99.0.1
    case "$mode" in
        wpa2 | open)
            {
                echo "interface=$RIF"
                echo "driver=nl80211"
                echo "ssid2=$hex"  # hex, so any bytes survive
                echo "hw_mode=g"
                echo "channel=1"
                [ "${HIDDEN:-0}" = 1 ] && echo "ignore_broadcast_ssid=1"
                [ "$mode" = wpa2 ] && printf 'wpa=2\nwpa_psk=%s\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n' "$psk"
            } >"$W/hostapd.conf"
            R hostapd -B -P "$W/router.pid" "$W/hostapd.conf" >/dev/null ;;
        sae | mixed)
            # Ubuntu's hostapd is built without SAE; its wpa_supplicant has it and can be the access point.
            {
                echo "network={"
                echo " ssid=$hex"
                echo " mode=2"
                echo " frequency=2412"
                echo " proto=RSN"
                echo " pairwise=CCMP"
                echo " group=CCMP"
                echo " sae_password=\"$pw\""
                if [ "$mode" = sae ]; then echo " key_mgmt=SAE"; echo " ieee80211w=2"
                else echo " key_mgmt=WPA-PSK SAE"; echo " psk=$psk"; echo " ieee80211w=1"; fi
                echo "}"
            } >"$W/ap-supplicant.conf"
            R wpa_supplicant -B -i "$RIF" -D nl80211 -c "$W/ap-supplicant.conf" -P "$W/router.pid" -f "$W/ap-supplicant.log" ;;
    esac
    [ "${NO_DHCP:-0}" = 1 ] && return
    R dnsmasq --interface="$RIF" --bind-interfaces --no-resolv --server=10.0.2.3 \
        --dhcp-range=192.168.77.50,192.168.77.99,1h --dhcp-option=3,192.168.77.1 --dhcp-option=6,192.168.77.1 \
        --pid-file="$W/dnsmasq.pid" --dhcp-leasefile="$W/leases"
}
router_down() {
    for f in "$W/router.pid" "$W/dnsmasq.pid"; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
    sleep 1
}

# ── the phone ─────────────────────────────────────────────────────────────
# "scan flush": the radio's BSS cache keeps a network that went away for about 30 s
setup_ssid() { P ip link set "$PIF" up; P iw dev "$PIF" scan flush 2>/dev/null | awk -F': ' '/SSID: SorterOS-Setup-/ { print $2; exit }'; }
setup_visible() { [ -n "$(setup_ssid)" ]; }
setup_gone() { ! setup_visible; }
page() { P curl -s -m 15 "$@"; }
state() { page http://10.42.0.1/api/state; }
phone_join() { # until the phone has the setup page (a scan can come back empty)
    local ssid start=$SECONDS
    while ((SECONDS - start < 90)); do
        ssid=$(setup_ssid)
        if [ -n "$ssid" ]; then
            P iw dev "$PIF" disconnect 2>/dev/null
            P iw dev "$PIF" connect "$ssid" && sleep 3 && P ip addr replace 10.42.0.77/24 dev "$PIF" &&
                state >/dev/null && return 0
        fi
        sleep 3
    done
    echo "     (the phone couldn't reach the setup page)"
    return 1
}
phone_leave() { P iw dev "$PIF" disconnect 2>/dev/null; P ip addr flush dev "$PIF"; }
phone_on_setup() { P iw dev "$PIF" link | grep -q "SSID: SorterOS-Setup-"; }
join() { # ssid password [more JSON fields, e.g. '{"hidden": true}']
    local more=${3:-}
    [ -n "$more" ] || more='{}'
    page -X POST -H 'Content-Type: application/json' \
        -d "$(python3 -c 'import json, sys; print(json.dumps({"ssid": sys.argv[1], "password": sys.argv[2], **json.loads(sys.argv[3])}))' "$1" "$2" "$more")" \
        http://10.42.0.1/api/join
}
join_is() { # state [reason]: what the page shows for the last join
    state | python3 -c 'import json, sys
j = json.load(sys.stdin).get("join") or {}
sys.exit(0 if j.get("state") == sys.argv[1] and (len(sys.argv) < 3 or j.get("reason") == sys.argv[2]) else 1)' "$@"
}
joined_with_internet() { # the page shows the Sorter's address, and the internet answers through it
    state | python3 -c 'import json, sys
j = json.load(sys.stdin).get("join") or {}
sys.exit(0 if j.get("state") == "joined" and j.get("address", "").startswith("192.168.77.") and j.get("internet") else 1)'
}
done_() { page -X POST -H 'Content-Type: application/json' -d '{}' http://10.42.0.1/api/done >/dev/null; }
reach() { P timeout 4 bash -c "</dev/tcp/10.42.0.1/$1" 2>/dev/null; }  # port, from the phone
cant_reach() { ! reach "$1"; }

# ── the Pi ────────────────────────────────────────────────────────────────
pi_reset() { # config text
    systemctl stop sorteros-network
    nmcli connection down sorteros-ap >/dev/null 2>&1
    eth_default no
    cable_internet yes
    nmcli -t -f UUID,TYPE connection show | awk -F: '$2 == "802-11-wireless" { print $1 }' |
        while read -r u; do nmcli connection delete uuid "$u" >/dev/null; done  # names can end in a space
    rm -f /var/lib/sorteros/wifi-imported /var/lib/sorteros/join.json /var/lib/sorteros/ip-announce.json
    printf '%b' "$1" >/etc/sorteros-config.toml
    phone_leave
}
net_start() { systemctl reset-failed sorteros-network 2>/dev/null; systemctl start sorteros-network; SINCE=$(date '+%F %T'); }
on_wifi() { nmcli -t -f GENERAL.IP4-CONNECTIVITY device show "$PI" | grep -q full; }
online() { [ "$(nmcli networking connectivity check)" = full ]; }
net_said() { journalctl -u sorteros-network --since "$SINCE" --no-pager | grep -q "$1"; }
saved_psk() { # ssid → the password NetworkManager holds for it
    local u
    for u in $(nmcli -t -f UUID,TYPE connection show | awk -F: '$2 == "802-11-wireless" { print $1 }'); do
        [ "$(nmcli --escape no -g 802-11-wireless.ssid connection show uuid "$u")" = "$1" ] &&
            nmcli --escape no -s -g 802-11-wireless-security.psk connection show uuid "$u"
    done
}
psk_is() { [ "$(saved_psk "$1")" = "$2" ]; }
never_broadcast() { ! net_said "Opened the setup network"; }

WIFI_OK='[wifi]\nssid = "HomeNet"\npassword = "right-password"\n'
want() { [ -z "${ONLY:-}" ] || [[ " $ONLY " == *" $1 "* ]]; } # ONLY="3 6" runs just those

if want 1; then
step "1. setup site Wi-Fi, right password"
router_down
router_up
pi_reset "$WIFI_OK"
net_start
check "joins the network from the setup site, with internet" wait_for 120 on_wifi
echo "     online after ${WAITED}s"
sleep 60
check "setup network never opened" never_broadcast
fi

if want 2; then
step "2. setup site Wi-Fi, wrong password; the phone fixes it"
router_down
router_up
pi_reset '[wifi]\nssid = "HomeNet"\npassword = "wrong-password"\n\n[tailscale]\nauth_key = "tskey-sim"\n'
net_start
check "setup network opens" wait_for 120 setup_visible
echo "     setup network after ${WAITED}s"
phone_join
check "the page says the setup site's password was wrong" join_is failed password
join HomeNet right-password '{"timezone": "Europe/Berlin"}' >/dev/null
check "joins while the phone watches" wait_for 60 joined_with_internet
check "the phone is still on the setup network" phone_on_setup
check "NetworkManager has the new password, and only it" psk_is HomeNet right-password
check "config kept the setup site's Tailscale key" grep -q 'tskey-sim' /etc/sorteros-config.toml
check "config has the phone's time zone" grep -q 'Europe/Berlin' /etc/sorteros-config.toml
check "the Wi-Fi country follows it" grep -qx 'ccode=DE' /lib/firmware/ap6275p/config.txt
phone_leave
check "setup network closes once the phone has left" wait_for 420 setup_gone
fi

if want 3; then
step "3. nothing given; the phone types a wrong password, then the right one"
router_down
router_up
pi_reset ''
net_start
check "setup network opens with nothing configured" wait_for 90 setup_visible
echo "     setup network after ${WAITED}s"
phone_join
check "the phone reaches the setup page on port 80" reach 80
check "but not SSH (the setup network is open)" cant_reach 22
check "nor the Sorter backend" cant_reach 8000
check "any name the phone looks up is the setup page (so it pops up)" \
    bash -c "ip netns exec phone getent ahostsv4 connectivitycheck.gstatic.com | grep -q '^10.42.0.1 '"
check "Android's check is sent to the page" \
    bash -c "ip netns exec phone curl -s -o /dev/null -w '%{http_code}' http://connectivitycheck.gstatic.com/generate_204 | grep -q '^30'"
check "Apple's check is sent to the page" \
    bash -c "ip netns exec phone curl -s -o /dev/null -w '%{http_code}' http://captive.apple.com/hotspot-detect.html | grep -q '^30'"
check "the page has the networks it scanned" bash -c "ip netns exec phone curl -s -m 15 http://10.42.0.1/api/state | grep -q '\"ssid\": \"HomeNet\"'"
join HomeNet wrong-password >/dev/null
check "the page says the password was wrong" wait_for 60 join_is failed password
echo "     answer after ${WAITED}s"
check "the phone never lost the setup network" phone_on_setup
join HomeNet right-password >/dev/null
check "then joins with the right one, and the page shows the address" wait_for 60 joined_with_internet
echo "     joined after ${WAITED}s"
check "the phone is still on the setup network" phone_on_setup
check "the Sorter UI's port 80 is untouched on its own network" bash -c "! iptables -t nat -S PREROUTING | grep -- '-i $PI '"
done_
check "Done closes the setup network in seconds" wait_for 30 setup_gone
fi

if want 4; then
step "4. router slower than the Pi after a power cut"
router_down
pi_reset "$WIFI_OK"
net_start
check "setup network opens while the router is down" wait_for 150 setup_visible
router_up
check "rejoins when the router comes back, by itself" wait_for 300 on_wifi
echo "     rejoined ${WAITED}s after the router came back"
check "setup network closes (nobody on it)" wait_for 120 setup_gone
fi

if want 5; then
step "5. cable plugged in during setup"
router_down
pi_reset ''
net_start
check "setup network opens" wait_for 90 setup_visible
eth_default yes
check "online by cable" wait_for 60 net_said "Online by cable"
check "setup network closes" wait_for 120 setup_gone
fi

if want 6; then
step "6. an odd network name and password from the phone"
router_down
ODD_SSID='Café Net/2 '
ODD_PSK=' back\slash pass'
router_up "$ODD_SSID" "$ODD_PSK"
pi_reset ''
net_start
check "setup network opens" wait_for 90 setup_visible
phone_join
join "$ODD_SSID" "$ODD_PSK" >/dev/null
check "joins it" wait_for 60 joined_with_internet
check "NetworkManager holds the name and password exactly" psk_is "$ODD_SSID" "$ODD_PSK"
fi

phone_joins() { # scenario title, router args, join args...: the phone gives it and the Pi joins
    local ssid=$2 pw=$3 mode=$4 extra=${5:-}
    step "$1"
    router_down
    router_up "$ssid" "$pw" "$mode"
    pi_reset ''
    net_start
    check "setup network opens" wait_for 90 setup_visible
    phone_join
    join "$ssid" "$pw" "$extra" >/dev/null
    check "joins it, and the page shows the address" wait_for 90 joined_with_internet
}
want 7 && phone_joins "7. an open network" OpenCafe "" open
want 8 && HIDDEN=1 phone_joins "8. a hidden network, typed on the phone" Hideaway hidden-password wpa2 '{"hidden": true}'
want 9 && phone_joins "9. a WPA3-only network" Wpa3Only wpa3-password sae
want 10 && phone_joins "10. a WPA2/WPA3 mixed network" Mixed mixed-password mixed

if want 11; then
step "11. a router that gives no address"
router_down
NO_DHCP=1 router_up HomeNet right-password
pi_reset ''
net_start
check "setup network opens" wait_for 90 setup_visible
phone_join
join HomeNet right-password >/dev/null
check "the page says it got no address" wait_for 120 join_is failed no_address
check "the phone never lost the setup network" phone_on_setup
fi

if want 12; then
step "12. a network with no internet"
router_down
NO_INTERNET=1 router_up HomeNet right-password
pi_reset ''
net_start
check "setup network opens" wait_for 90 setup_visible
phone_join
join HomeNet right-password >/dev/null
check "joins it" wait_for 60 join_is joined
check "and the page says there's no internet through it" bash -c "ip netns exec phone curl -s -m 15 http://10.42.0.1/api/state | grep -q '\"internet\": false'"
done_
check "Done closes the setup network" wait_for 30 setup_gone
sleep 90
check "and it stays closed while the Pi is on that network" setup_gone
fi

if want 13; then
step "13. a cable with no internet doesn't hide a Wi-Fi that works"
router_down
router_up
pi_reset ''
eth_default yes
cable_internet no
net_start
check "setup network opens despite the cable" wait_for 120 setup_visible
check "the Pi says the cable has no internet" net_said "Connected by cable at .*, but no internet"
phone_join
join HomeNet right-password >/dev/null
check "joins Wi-Fi, and the page shows the internet answers through it" wait_for 60 joined_with_internet
check "the Pi's own traffic goes over the Wi-Fi" wait_for 90 online
check "the cable's route was moved below the Wi-Fi's" bash -c "ip -4 route show default | head -1 | grep -q ' dev $PI '"
cable_internet yes
fi

eth_default yes
cable_internet yes
router_down
echo "DONE pass=$pass fail=$fail"
