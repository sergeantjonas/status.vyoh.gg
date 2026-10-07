# Status page

**Status:** Active — scaffold and prober landed 2026-10-07; checks + install on the box next, then the page.

One page that says whether each public site on the shared VPS answers, plus an alert when one stops. Watches every tenant and belongs to none of them.

Cross-project reasoning (why hosting off-box, why healthchecks.io, why silence counts as a failure) lives in [`~/dev/commonplace/status-page.md`](https://github.com/sergeantjonas/commonplace/blob/main/status-page.md) — this note holds the implementation.

## Hostnames

Each public hostname gets one healthchecks.io check, in a project of its own apart from the tenants' backup checks. Each check carries a tag matching the hostname, so the page can fetch per-hostname badge JSON.

| Host | Path | Expected | Why that path |
|---|---|---|---|
| `vyoh.gg` | `/` | 200 | Web root. |
| `api.vyoh.gg` | `/health` | 200 | Named route; a process with an unreachable database should count as down. |
| `engram.vyoh.gg` | `/` | 200 | Web root. |
| `api.engram.vyoh.gg` | `/ready` | 200 | Answers 503 when the database is unreachable, which is what we want. |

Each probe runs separately over IPv4 and IPv6. A wrong A record and a right AAAA serves nothing over IPv4 but still passes a single-family check — that was the shape of vyoh's own smoke-test miss on 2026-09-17 (see vyoh's `ops/post-launch-ops.md`), and this prober exists partly so the same miss cannot repeat.

## States

Three words, three colours:

- **up** — most recent probe succeeded on both address families.
- **late** — healthchecks.io has not heard from the prober since the schedule plus grace, so we do not know.
- **down** — most recent probe failed, or any single-family probe failed.

"late" is the state healthchecks.io assigns to a quiet check; the page shows the same word.

## Prober

Lives in [`prober/`](../../prober/). Runs on the shared box as a systemd timer, following the heartbeat pattern from the `shared-vps` skill:

- `probe.sh` walks the target list (hostnames, paths, expected codes) at the top of the file. Add a tenant there, add its `PING_<slug>` to the env file.
- `status-probe.service` runs the script as a oneshot with `/etc/status-page/probe.env` loaded via `EnvironmentFile=-`. Ping URLs reach curl on stdin via `-K -` so they never appear in argv.
- `status-probe.timer` fires every 3 minutes with 30s jitter, `Persistent=true`.
- The script always exits 0 — a missing key or unreachable healthchecks.io becomes silence, which the check turns into an alert on its own after grace.
- Service is hardened via systemd directives (`ProtectSystem=strict`, `RestrictAddressFamilies=AF_INET AF_INET6`, syscall filter).

Checks are made by hand on healthchecks.io, slug = hostname, `*/3 * * * *` Europe/Brussels, grace 2 minutes. See [`prober/README.md`](../../prober/README.md) for the install flow and the drill step.

Blind spot: the box resolves its own hostnames to its public IPs on `eth0`, so a request to its own hostname never leaves the box. The netcup firewall and upstream routing go untested. Second-prober options are in `## Open` below.

## Page

Static HTML and JS in this repo's root. GitHub Pages serves the built content directly from the default branch; no action, no build step. CNAME file carries `status.vyoh.gg`.

Per hostname, the page fetches `https://healthchecks.io/badge/<project-badge-key>/<tag>.json`, reads the `status` field, renders the word and the colour. Badge URLs are read-only and reveal only the status.

The page refetches on an interval (every 60s is enough; healthchecks.io updates at its own cadence). The page never calls out to the box.

## Next action

1. Create the healthchecks.io project and the four checks (slug = hostname, tag = hostname, `*/3 * * * *` Europe/Brussels, grace 2 minutes).
2. Install on the box: `rsync -av --delete prober/ vyoh:/tmp/status-probe/` → `ssh vyoh "cd /tmp/status-probe && sudo bash install.sh"`, fill `/etc/status-page/probe.env`, enable the timer.
3. Drill one `/fail` through the real script and key file, confirm the alert.
4. Wire the page: fetch badge JSON per tag, render the three states.
5. GitHub Pages + CNAME DNS + cert.
6. Smoke the live page over IPv4 and IPv6.

## Open

- **A second prober off the box.** The on-box prober's blind spot is everything between the box and the public internet. A scheduled GitHub Actions workflow or a Cloudflare Worker cron trigger covers it, at the cost of a second thing to keep running. Actions is late and sometimes dropped, so its grace needs to be wide. Deferred until the blind spot bites.
- **Certificate expiry.** Certbot renews unattended, but a silently-failing renewal would currently show green here. A probe could fail its check when the served certificate comes within N days of expiry.
- **Backups on the page.** The nightly backup checks are already in healthchecks.io but their badges sit in each tenant's own project. A public page that lists backup state says more than whether a site answers, so this stays open until the tradeoff is settled.
- **Build or adopt.** Uptime Kuma, Gatus, UptimeRobot, Better Stack and Upptime all replace parts of this plan. None reuses the healthchecks.io account that already alerts on backups, and all cost either a second machine or a second account. Committed to building for now.
