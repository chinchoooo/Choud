#!/usr/bin/env bash
# Check that this machine is ready to run the stack, BEFORE building anything.
# Prints one line per check; exits non-zero if any check FAILs (warnings are
# only advisory).
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
warn() { printf '  [warn] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }

echo "Preflight checks"

# --- Docker -----------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
    ok "docker is installed"
    if docker info >/dev/null 2>&1; then
        ok "docker daemon is reachable"
    else
        bad "docker daemon is not reachable (is it running? is your user in the 'docker' group?)"
    fi
    if docker compose version >/dev/null 2>&1; then
        ok "docker compose v2 plugin is available"
    else
        bad "docker compose v2 plugin is missing (install docker-compose-plugin)"
    fi
else
    bad "docker is not installed - https://docs.docker.com/engine/install/"
fi

# --- .env and secrets -------------------------------------------------------
if [ -f .env ]; then
    ok ".env exists"
    set -a; . ./.env; set +a
    case "${JWT_SECRET:-}" in
        ""|changeme*|dev-only*)
            bad "JWT_SECRET is empty or a placeholder - run scripts/setup.sh on a fresh checkout, or set a real one" ;;
        *)
            if [ "${#JWT_SECRET}" -ge 32 ]; then ok "JWT_SECRET looks strong"; else bad "JWT_SECRET is shorter than 32 characters"; fi ;;
    esac
    case "${POSTGRES_PASSWORD:-}" in
        ""|changeme*|dev-only*) bad "POSTGRES_PASSWORD is empty or a placeholder" ;;
        *) ok "POSTGRES_PASSWORD is set" ;;
    esac
    if [ -n "$(find .env -perm /077 2>/dev/null)" ]; then
        warn ".env is readable by other users (chmod 600 .env)"
    fi
else
    bad ".env is missing - run scripts/setup.sh"
fi

# --- ports ------------------------------------------------------------------
port_in_use() {
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$1\$"
    elif command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
    else
        (exec 3<>/dev/tcp/127.0.0.1/"$1") 2>/dev/null
    fi
}
for port in "${HTTP_PORT:-80}" "${HTTPS_PORT:-443}"; do
    if port_in_use "$port"; then
        warn "port $port is already in use (set HTTP_PORT/HTTPS_PORT in .env, or stop what uses it; ignore if it is this stack already running)"
    else
        ok "port $port is free"
    fi
done

# --- line endings (a Windows checkout can break shell scripts in containers) --
# Counts carriage-return bytes with tr; grep is not used because some builds
# (e.g. Git for Windows) mishandle a bare CR pattern. \015 is a carriage
# return written in octal so it survives any editor or shell quoting.
crlf=""
while IFS= read -r f; do
    if [ "$(tr -cd '\015' < "$f" | wc -c)" -gt 0 ]; then crlf="$crlf $f"; fi
done < <(find . \( -name node_modules -o -name .git \) -prune -o -type f \
            \( -name '*.sh' -o -name Dockerfile -o -name Caddyfile -o -name '*.yml' -o -name '*.conf' \) -print)
if [ -n "$crlf" ]; then
    bad "CRLF line endings found (breaks scripts inside Linux containers):$crlf"
    echo "         fix: git config core.autocrlf input && git rm --cached -r . -q && git reset --hard"
else
    ok "no CRLF line endings in scripts/config"
fi

# --- resources --------------------------------------------------------------
free_gb="$(df -Pk . 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024/1024}')"
if [ -n "${free_gb:-}" ]; then
    if [ "$free_gb" -lt 5 ]; then
        bad "only ${free_gb} GB free on this disk (need at least 5 GB to build)"
    else
        ok "${free_gb} GB free on this disk"
    fi
fi
if [ -r /proc/meminfo ]; then
    mem_mb="$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null)"
    if [ -z "$mem_mb" ]; then
        :  # not a Linux /proc (e.g. Git Bash on Windows): skip the check
    elif [ "$mem_mb" -lt 1500 ]; then
        warn "only ${mem_mb} MB RAM available - the C++ engine build may be slow or be killed"
    else
        ok "${mem_mb} MB RAM available"
    fi
fi

# --- compose file -----------------------------------------------------------
if command -v docker >/dev/null 2>&1 && [ -f .env ]; then
    if docker compose config -q >/dev/null 2>&1; then
        ok "docker-compose.yml is valid"
    else
        bad "'docker compose config' reports an error - run it by hand to see it"
    fi
fi

# --- remote access ----------------------------------------------------------
if command -v tailscale >/dev/null 2>&1; then
    if tailscale status >/dev/null 2>&1; then
        ok "tailscale is installed and connected"
    else
        warn "tailscale is installed but not connected (sudo tailscale up)"
    fi
else
    warn "tailscale is not installed - the server will only be reachable on the local network"
fi

echo
if [ "$fail" -ne 0 ]; then
    echo "Preflight FAILED - fix the [FAIL] items above."
    exit 1
fi
echo "Preflight passed."
