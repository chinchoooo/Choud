#!/usr/bin/env bash
# Install the backup client for the current user (Linux or macOS). Needs Python 3.9+.
#
#   bash client/install.sh
#   cloudsync login --mode backup --server http://100.x.y.z --email you@example.com \
#       --folder ~/Documents --folder ~/Pictures
#   cloudsync install-service
#
# Nothing here needs sudo: the program goes in ~/.local/share/cloudsync and a link in ~/.local/bin.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home="${XDG_DATA_HOME:-$HOME/.local/share}/cloudsync"
bin="$HOME/.local/bin"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "Python 3.9 or newer is required (install python3 first)." >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 or newer is required; found $("$PY" --version 2>&1)." >&2
  exit 1
fi

mkdir -p "$home" "$bin"
"$PY" -m venv "$home/venv"
"$home/venv/bin/pip" install --quiet --upgrade pip
"$home/venv/bin/pip" install --quiet "$here"
ln -sf "$home/venv/bin/cloudsync" "$bin/cloudsync"

echo "Installed. Make sure $bin is on your PATH, then run:"
echo "  cloudsync login --mode backup --server http://<server tailscale address> \\"
echo "      --email <you> --folder ~/Documents"
echo "  cloudsync install-service"
