#!/usr/bin/env bash
# Install (or update) the status-page prober on this host.
# Idempotent: safe to rerun after editing the script or the units.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
	echo "Run as root (needs /etc, /usr/local/bin, systemctl)." >&2
	exit 1
fi

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ETC=/etc/status-page
SCRIPT=/usr/local/bin/status-probe
UNITS=/etc/systemd/system

install -d -m 755 "$ETC"
install -m 755 "$HERE/probe.sh" "$SCRIPT"
install -m 644 "$HERE/status-probe.service" "$UNITS/status-probe.service"
install -m 644 "$HERE/status-probe.timer" "$UNITS/status-probe.timer"

env_needs_edit=0
if [[ ! -f "$ETC/probe.env" ]]; then
	install -m 600 -o root -g root "$HERE/probe.env.example" "$ETC/probe.env"
	env_needs_edit=1
fi

systemctl daemon-reload

if [[ $env_needs_edit -eq 1 ]]; then
	cat <<-EOF

	Dropped $ETC/probe.env from the example. The timer is NOT enabled yet.
	Edit the file to add the real ping URLs, then:

	  sudo systemctl enable --now status-probe.timer
	  sudo systemctl start status-probe.service   # one-shot drill
	  journalctl -u status-probe.service -n 50

	Then flip one check to /fail by hand to confirm the alert path:

	  curl -K - <<'K'
	  url "https://hc-ping.com/<uuid>/fail"
	  data-binary "drill from \$(hostname)"
	  K
	EOF
	exit 0
fi

systemctl enable --now status-probe.timer
echo
systemctl list-timers status-probe.timer --no-pager
