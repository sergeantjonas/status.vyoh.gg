# Prober

Runs on the shared VPS as a systemd timer. Every ~3 minutes it requests each public hostname over IPv4 and IPv6 and pings that hostname's healthchecks.io check with success or `/fail`. A timer that never fires, or a box that is down, becomes silence — healthchecks.io alerts on that too.

Follows the heartbeat pattern codified in the `shared-vps` skill: the key in an env file read via `EnvironmentFile=-`, piped to `curl -K -` so the ping URL never reaches argv, and a script that always exits 0.

## What's here

| File | What it is |
|---|---|
| `probe.sh` | The probe. Walks the target list, probes each over IPv4 and IPv6, pings each hostname's check. |
| `status-probe.service` | Oneshot systemd unit that runs the probe with `probe.env` loaded. |
| `status-probe.timer` | 3-minute cadence with 30s jitter, `Persistent=true`. |
| `probe.env.example` | Placeholder env file; `install.sh` copies it on first run. |
| `install.sh` | Idempotent install/update. Lays down the script and units in `/usr/local/bin` and `/etc/systemd/system`, seeds `/etc/status-page/probe.env` from the example on first run. |

The target list — hostnames, health routes, expected status codes — lives at the top of `probe.sh`. Add a tenant there, add a `PING_<slug>` to the env file, and the next run picks it up.

## Installing

On the VPS (`vyoh` in `~/.ssh/config`):

```sh
# From a working copy of this repo on your laptop:
rsync -av --delete prober/ vyoh:/tmp/status-probe/
ssh vyoh "cd /tmp/status-probe && sudo bash install.sh"
```

First run drops `/etc/status-page/probe.env` from the example and stops. Edit the file to add the real ping URLs, then enable the timer:

```sh
ssh vyoh "sudo -e /etc/status-page/probe.env"
ssh vyoh "sudo systemctl enable --now status-probe.timer"
```

## healthchecks.io setup

Make the checks **by hand** — auto-creating on first ping hides a typo'd slug.

- One healthchecks.io project of its own; this project is not the tenants' backup project.
- One check per hostname. Slug matches the hostname (`vyoh.gg`, `api.vyoh.gg`, `engram.vyoh.gg`, `api.engram.vyoh.gg`). Tag each check with the hostname too; that's what the status page reads badges by.
- Schedule: `*/3 * * * *` Europe/Brussels; grace 2 minutes (covers 30s timer jitter + up to ~90s probe time + buffer).

Copy each check's **Ping URL** into `/etc/status-page/probe.env`. The key field is the UUID path segment, so a short-form `https://hc-ping.com/<uuid>` works.

Verify the file: `awk -F= '{ print $1, length($2) }' /etc/status-page/probe.env`. A stray space adds a character.

## Drilling

Fire the service once and check the healthchecks.io dashboard reports a ping:

```sh
sudo systemctl start status-probe.service
journalctl -u status-probe.service -n 50
```

Then force an alert by posting a `/fail` with the real key, exactly as the script would:

```sh
curl -K - <<'K'
url "https://hc-ping.com/<uuid>/fail"
data-binary "drill from $(hostname)"
K
```

Confirm the DOWN notification arrives in the configured integration channel, then let the next scheduled run restore the check to up.

## Blind spot

The box resolves its own public hostnames to its `eth0` addresses, so a probe to `vyoh.gg` from the box itself never leaves the box. The firewall and upstream routing go untested. If this blind spot ever bites, a second prober off the box (GitHub Actions cron, Cloudflare Worker) is sketched in [`../docs/working-notes/status-page.md` § Open](../docs/working-notes/status-page.md#open).
