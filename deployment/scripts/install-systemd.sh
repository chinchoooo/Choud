#!/usr/bin/env bash
# Install the systemd units (start on boot, nightly backup, health check) for
# the checkout this script lives in. Run as root:
#
#   sudo deployment/scripts/install-systemd.sh
#
# The units are templates; @INSTALL_DIR@ is replaced with this checkout's
# absolute path, so the repo can live anywhere (e.g. /opt/personal-cloud or
# ~/Choud).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo $0" >&2
    exit 1
fi

install_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
unit_dir="/etc/systemd/system"

[ -f "${install_dir}/.env" ] || { echo "No ${install_dir}/.env - run scripts/setup.sh first." >&2; exit 1; }

for unit in personal-cloud.service personal-cloud-backup.service personal-cloud-backup.timer \
            personal-cloud-health.service personal-cloud-health.timer; do
    sed "s|@INSTALL_DIR@|${install_dir}|g" "${install_dir}/deployment/systemd/${unit}" > "${unit_dir}/${unit}"
    echo "installed ${unit_dir}/${unit}"
done

systemctl daemon-reload
systemctl enable --now personal-cloud.service
systemctl enable --now personal-cloud-backup.timer
systemctl enable --now personal-cloud-health.timer

echo
echo "Done. Useful commands:"
echo "  systemctl status personal-cloud            # is the stack up?"
echo "  systemctl list-timers 'personal-cloud*'    # next backup / health check"
echo "  sudo systemctl start personal-cloud-backup # back up right now"
echo "  journalctl -u personal-cloud-health -n 20  # recent health results"
