#!/usr/bin/env bash
# Make share links work for people OUTSIDE your network, in one command.
#
#   scripts/enable-public-links.sh                       Tailscale Funnel (default, free, no domain)
#   scripts/enable-public-links.sh --cloudflare HOST     a named Cloudflare Tunnel on your own domain
#   scripts/enable-public-links.sh --cloudflare-quick    a throwaway trycloudflare.com address
#   scripts/enable-public-links.sh --status              show what is on, change nothing
#   scripts/enable-public-links.sh --off                 turn it off again (links fall back to private)
#   add --dry-run to any of them to print what would happen without doing it
#
# What becomes reachable from the internet: ONLY /s/* (the share pages). The app, the API and the login
# stay private (the "public door" answers 404 for everything else; see docs/deployment.md).
#
# Exit codes: 0 done, 1 failed, 2 needs one manual step (the message says which).
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

MODE=tailscale
HOST=""
DRY=0
ACTION=enable
while [ $# -gt 0 ]; do
    case "$1" in
        --tailscale) MODE=tailscale ;;
        --cloudflare) MODE=cloudflare; HOST="${2:-}"; shift ;;
        --cloudflare-quick) MODE=cloudflare-quick ;;
        --off) ACTION=off ;;
        --status) ACTION=status ;;
        --dry-run) DRY=1 ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 1 ;;
    esac
    shift
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
manual() { printf '\nNEEDS ONE MANUAL STEP: %s\n' "$*" >&2; exit 2; }

# Run a command, or only show it with --dry-run.
run() {
    if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; return 0; fi
    "$@"
}

# sudo only when needed and available (ENABLE_PUBLIC_SUDO overrides: set it empty to never use sudo).
if [ "${ENABLE_PUBLIC_SUDO+set}" = set ]; then
    SUDO="$ENABLE_PUBLIC_SUDO"
elif [ "$(id -u)" = 0 ] || ! command -v sudo >/dev/null 2>&1; then
    SUDO=""
else
    SUDO="sudo"
fi

[ -f .env ] || die ".env not found. Run this from the repository folder of a deployed Choud (scripts/setup.sh creates .env)."
command -v docker >/dev/null 2>&1 || die "docker is not installed."

PUBLIC_PORT="$(grep -E '^PUBLIC_PORT=' .env | tail -n1 | cut -d= -f2- | tr -d '"' || true)"
PUBLIC_PORT="${PUBLIC_PORT:-8081}"
LOCAL="http://127.0.0.1:${PUBLIC_PORT}"

# A python that actually runs (some systems have a python3 that is only a stub).
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import json' >/dev/null 2>&1; then PY="$candidate"; break; fi
done

# env_set KEY VALUE: set or replace one line in .env, keeping a private backup.
env_set() {
    local key="$1" value="$2"
    if [ "$DRY" = 1 ]; then printf '   [dry-run] set %s=%s in .env\n' "$key" "$value"; return 0; fi
    cp -p .env .env.bak && chmod 600 .env.bak
    if grep -qE "^${key}=" .env; then
        local tmp; tmp="$(mktemp)"
        while IFS= read -r line || [ -n "$line" ]; do
            case "$line" in "${key}="*) printf '%s=%s\n' "$key" "$value" ;; *) printf '%s\n' "$line" ;; esac
        done < .env > "$tmp"
        cat "$tmp" > .env && rm -f "$tmp"
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

current_url() { grep -E '^PUBLIC_BASE_URL=' .env | tail -n1 | cut -d= -f2- | tr -d '"' || true; }

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@" 2>/dev/null || echo 000; }

restart_backend() {
    step "Restarting the backend so it hands out the new address (the proxy and the engine stay up)"
    run docker compose up -d --no-deps backend || die "could not restart the backend; run: docker compose up -d --no-deps backend"
}

check_local_door() {
    step "Checking the public door on this machine ($LOCAL)"
    local code; code="$(http_code "$LOCAL/s/_health")"
    [ "$code" = 200 ] || die "the public door did not answer on $LOCAL/s/_health (got $code). Is the stack running? Try: docker compose up -d"
    code="$(http_code "$LOCAL/api/health")"
    if [ "$code" != 404 ]; then
        die "the public door answers $code for /api/health. It should be 404 so the app stays private. Is PUBLIC_DOOR_MODE=shares in .env?"
    fi
    say "   ok: share pages are served, everything else is 404"
}

verify_public() {
    local url="$1"
    step "Checking $url from this machine"
    local ok=0 i
    for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
        if [ "$(http_code "$url/s/_health")" = 200 ]; then ok=1; break; fi
        say "   not reachable yet, waiting ($i/12; new addresses can take a minute)"
        [ "$DRY" = 1 ] && { ok=1; break; }
        sleep 5
    done
    [ "$ok" = 1 ] || die "$url did not answer. The link was NOT switched on for the app; see docs/deployment.md 'Making share links public'."
    local body; body="$(curl -s --max-time 10 "$url/s/_health" 2>/dev/null || true)"
    case "$body" in *'"door":"public"'*) say "   ok: the request came in through the public door" ;; *) say "   note: it answered, but not marked as the public door yet" ;; esac
    case "$body" in
        *'"client_ip":"127.'*|*'"client_ip":"172.'*|*'"client_ip":"10.'*)
            say "   warning: the server sees visitors as a local address, so per-visitor rate limits would share one bucket." ;;
    esac
    if [ "$(http_code "$url/api/health")" = 404 ]; then say "   ok: the app and the API are NOT reachable from there"; else say "   warning: $url/api/health did not answer 404, check PUBLIC_DOOR_MODE=shares"; fi
    say "   This check ran on this machine. Also open a link from a phone on mobile data to be sure."
}

# --------------------------------------------------------------------------------------- status
if [ "$ACTION" = status ]; then
    step "Public share links"
    say "PUBLIC_BASE_URL: $(current_url)"
    [ -n "$(current_url)" ] || say "   (not set: links only work on your private network)"
    code="$(http_code "$LOCAL/s/_health")"
    say "public door on this machine: $code (200 is good)"
    if command -v tailscale >/dev/null 2>&1; then say "--- tailscale funnel ---"; tailscale funnel status 2>&1 | sed 's/^/   /' || true; fi
    if [ -n "$(current_url)" ]; then say "from here: $(http_code "$(current_url)/s/_health") at $(current_url)/s/_health"; fi
    exit 0
fi

# ------------------------------------------------------------------------------------------ off
if [ "$ACTION" = off ]; then
    step "Turning public links off"
    if command -v tailscale >/dev/null 2>&1; then run $SUDO tailscale funnel --https=443 off || say "   (no Tailscale funnel was running)"; fi
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet cloudflared 2>/dev/null; then
        run $SUDO systemctl stop cloudflared || true
    fi
    env_set PUBLIC_BASE_URL ""
    restart_backend
    say
    say "Done. New links are private-network links again. Existing links stay valid on your private address."
    say "To also stop every link that was ever shared: use 'Revoke all links' in the app (Server page), or More > Sharing."
    exit 0
fi

# ---------------------------------------------------------------------------------------- enable
check_local_door
URL=""

case "$MODE" in
tailscale)
    step "Tailscale Funnel"
    command -v tailscale >/dev/null 2>&1 || manual "Tailscale is not installed. Install it (https://tailscale.com/download), run 'sudo tailscale up', then run this again."
    [ -n "$PY" ] || manual "Python 3 is needed to read Tailscale's status (sudo apt install python3), then run this again."
    STATUS_JSON="$(tailscale status --json 2>/dev/null || true)"
    [ -n "$STATUS_JSON" ] || manual "Tailscale is not running. Run 'sudo tailscale up' and then this script again."
    NAME="$(printf '%s' "$STATUS_JSON" | "$PY" -c 'import json,sys
d=json.load(sys.stdin)
print((d.get("Self",{}).get("DNSName") or "").rstrip("."))' 2>/dev/null || true)"
    [ -n "$NAME" ] || manual "Could not read this machine's Tailscale name. Is MagicDNS on? Check https://login.tailscale.com/admin/dns"
    CERTS="$(printf '%s' "$STATUS_JSON" | "$PY" -c 'import json,sys
d=json.load(sys.stdin)
print(len(d.get("CertDomains") or []))' 2>/dev/null || echo 0)"
    [ "$CERTS" != 0 ] || manual "HTTPS certificates are off for your tailnet. Turn on 'HTTPS Certificates' at https://login.tailscale.com/admin/dns and run this again."
    say "   this machine is $NAME"
    if ! run $SUDO tailscale funnel --bg --https=443 "$LOCAL"; then
        manual "Tailscale refused to start Funnel. Allow it for this machine in your access controls (the 'funnel' node attribute): https://login.tailscale.com/admin/acls , then run this again."
    fi
    URL="https://${NAME}"
    ;;
cloudflare)
    step "Cloudflare Tunnel on ${HOST:-?}"
    [ -n "$HOST" ] || die "--cloudflare needs a hostname, e.g. --cloudflare links.example.com"
    command -v cloudflared >/dev/null 2>&1 || manual "cloudflared is not installed. Install it (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) and run 'cloudflared tunnel login', then run this again."
    [ -f "$HOME/.cloudflared/cert.pem" ] || manual "Run 'cloudflared tunnel login' once (it opens a browser) and then run this again."
    run cloudflared tunnel create choud 2>/dev/null || say "   (tunnel 'choud' already exists)"
    run cloudflared tunnel route dns choud "$HOST" || say "   (DNS record may already exist)"
    if [ "$DRY" = 0 ]; then
        mkdir -p "$HOME/.cloudflared"
        {
            echo "tunnel: choud"
            echo "ingress:"
            echo "  - hostname: $HOST"
            echo "    service: $LOCAL"
            echo "  - service: http_status:404"
        } > "$HOME/.cloudflared/config.yml"
    else
        say "   [dry-run] write ~/.cloudflared/config.yml (hostname $HOST -> $LOCAL, catch-all 404)"
    fi
    run $SUDO cloudflared service install 2>/dev/null || say "   (cloudflared service may already be installed)"
    URL="https://${HOST}"
    ;;
cloudflare-quick)
    step "Cloudflare quick tunnel (the address changes every time it restarts)"
    command -v cloudflared >/dev/null 2>&1 || manual "cloudflared is not installed. Install it first (see --help)."
    LOG="$(mktemp)"
    if [ "$DRY" = 1 ]; then
        say "   [dry-run] cloudflared tunnel --url $LOCAL"
        URL="https://example.trycloudflare.com"
    else
        nohup cloudflared tunnel --url "$LOCAL" > "$LOG" 2>&1 &
        for _ in $(seq 1 20); do
            URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -n1 || true)"
            [ -n "$URL" ] && break
            sleep 1
        done
        [ -n "$URL" ] || die "cloudflared did not print an address; see $LOG"
        say "   warning: this address stops working when cloudflared stops or the machine restarts."
    fi
    ;;
esac

verify_public "$URL"
env_set PUBLIC_BASE_URL "$URL"
restart_backend

say
say "Done. Share links are now: $URL/s/..."
say "  Reachable from the internet: only the share pages. The app, API and login are not."
say "  Pause or resume at any time: in the app (Server page, or More > Sharing)."
say "  Turn it off completely:      scripts/enable-public-links.sh --off"
