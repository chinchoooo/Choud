#!/usr/bin/env bash
# Is this machine a good server for a phone? Checks the things that make photos slow to load.
#
# Run it on the server (the laptop):   scripts/netcheck.sh [tailscale-name-or-ip-of-your-phone]
#
# What it looks at:
#   - Wi-Fi power saving (the usual reason a same-room ping is 90 ms instead of 3 ms)
#   - whether Tailscale reaches the phone directly or through a relay (relays add 50-200 ms)
#   - a round-trip time to the phone, if you give it
set -uo pipefail

say()  { printf '%s\n' "$*"; }
ok()   { printf '  [ ok ] %s\n' "$1"; }
warn() { printf '  [warn] %s\n' "$1"; }

say "Network check"

# --- Wi-Fi power saving ----------------------------------------------------------------------------
found_wifi=0
if command -v iw >/dev/null 2>&1; then
    for dev in $(iw dev 2>/dev/null | awk '$1=="Interface"{print $2}'); do
        found_wifi=1
        state="$(iw dev "$dev" get power_save 2>/dev/null | awk '{print $NF}')"
        if [ "$state" = "on" ]; then
            warn "Wi-Fi power saving is ON for $dev. It makes every reply wait for the radio to wake up (tens of ms, and a slow first byte)."
            say  "         Turn it off now:    sudo iw dev $dev set power_save off"
            say  "         Keep it off:        printf '[connection]\nwifi.powersave = 2\n' | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf && sudo systemctl restart NetworkManager"
            say  "         Or plug in Ethernet, which also avoids the problem."
        else
            ok "Wi-Fi power saving is off for $dev"
        fi
    done
fi
[ "$found_wifi" = 1 ] || ok "no Wi-Fi interface found (a wired connection has no power-save problem)"

# --- Tailscale path ----------------------------------------------------------------------------------
if command -v tailscale >/dev/null 2>&1; then
    peer="${1:-}"
    if [ -n "$peer" ]; then
        say "  tailscale ping $peer (a few tries):"
        tailscale ping --c 4 "$peer" 2>&1 | sed 's/^/      /'
        say "  'via DERP' means a relay, 'direct' means a straight connection. Direct from the same room should be under 10 ms."
    else
        say "  tip: pass your phone's Tailscale name to measure it:  scripts/netcheck.sh my-phone"
    fi
    say "  tailscale netcheck (does this network allow direct connections?):"
    tailscale netcheck 2>&1 | sed -n '1,14p' | sed 's/^/      /'
else
    warn "tailscale is not installed here (fine if you only use a LAN address)"
fi
