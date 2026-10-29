# Status page

**Status:** Active — off-box prober landed 2026-10-09; wired to notify.vyoh.gg 2026-10-10; Cloudflare Worker trigger deployed 2026-10-12; history strip moved to fixed 15-min slots over 24h 2026-10-12; alerts gated on in-run retries and two consecutive failed cycles 2026-10-29. Next action 5 and 7 not yet confirmed done. 4 confirmed on 2026-10-29, yet the failed 2026-10-29 03:31 run (actor `sergeantjonas`) produced no email the owner saw — check where GitHub routes notification email.

One page that says whether each public site on the shared VPS answers. Watches every tenant and belongs to none of them.

Cross-project reasoning (why hosting off-box, why alerting off-box) lives in [`~/dev/commonplace/status-page.md`](https://github.com/sergeantjonas/commonplace/blob/main/status-page.md) — this note holds the implementation.

## Shape

Everything runs off the netcup box: GitHub Actions + Pages, plus one cron-only Cloudflare Worker. No tenant on the box, no self-hosted monitoring box.

- **Prober:** `.github/workflows/probe.yml` — Actions workflow, every 15 min. The primary trigger is [`worker/`](../../worker/), a cron-only Cloudflare Worker that calls `workflow_dispatch` every 15 min; the workflow's own `schedule` stays as an hourly backup at `:37` (off the hour, where GitHub sheds load hardest), plus `push`. Runs [`probe.py`](../../probe.py) against the targets in [`targets.toml`](../../targets.toml), writes `status.json`, POSTs state transitions to notify.vyoh.gg, deploys the whole thing to Pages. The Pages deploy steps run with `if: !cancelled()` so the page keeps updating even when the probe step failed delivery.
- **Page:** [`index.html`](../../index.html) in the repo root. Fetches `status.json` and renders a hero headline + grouped host rows with per-row uptime % and current streak. Vanilla JS, no build step. One self-hosted font ([`fonts/inter.woff2`](../../fonts/inter.woff2), ~48 KB) carries the typography; favicon is a state-coloured rounded badge generated inline. Deliberate accent (indigo `#4f46e5` light / `#818cf8` dark) picked to sit outside the status palette so brand doesn't fight state.
- **Alerting (two layers):** routine transitions `POST` to `https://notify.vyoh.gg/messages` per the hub's contract (`key`/`title`/`body`/`url`, bearer auth; no `source` in the body — the hub infers it from the secret). Credentials come from repo secrets `NOTIFY_HUB_URL` + `NOTIFY_HUB_SECRET` (scoped per-source — a leak lets an attacker post status-page alerts, nothing more). When the hub is unreachable — overwhelmingly because the netcup box it runs on is down — the POST fails, `probe.py` exits non-zero, the workflow goes red, and GitHub emails the workflow-failure. That email **is** the box-down alert. No Discord webhook URL ever lives in this repo.
- **State store:** `status.json` on Pages itself. The workflow fetches the previous `status.json` from `https://status.vyoh.gg/status.json` at the start of each run, so transitions survive across runs without committing anything back to git.

Decided against the earlier on-box-prober + healthchecks.io shape (2026-10-07..08 history) on simplicity grounds: moving the prober off-box deletes the need for silence-detection entirely, which was healthchecks.io's whole job here. Backups still use healthchecks.io; the status page doesn't.

Decided 2026-10-10 to route alerts via notify.vyoh.gg rather than directly to a Discord webhook. The webhook URL stays in notify-hub where it belongs (per the hub's own contract: one credential, one holder). The box-down case notify-hub cannot carry is handled by workflow-failure email instead, which needs no secret.

Decided 2026-10-12 to add the Worker trigger. GitHub's `schedule` on this free-tier public repo delivered one run per 3–7h against the 90-min stale threshold, so the banner was up most of the time and outages surfaced hours late. The Worker only triggers; probing stays in Actions, so `probe.py` and the failure-email fallback are untouched. Triggering from the netcup box instead was rejected: it would stop probing exactly when the box is down. The token is a fine-grained PAT scoped to this repo with Actions: write and no expiry, stored only as the Worker secret `GITHUB_TOKEN`. Wrangler is pinned via `npx wrangler@4.142.0`; no `package.json`.

## Targets

Edit `targets.toml` to add or remove. Each `[[target]]` block carries:

| Field | Default | Notes |
|---|---|---|
| `host` | required | Public hostname, probed over HTTPS. |
| `path` | `/` | URL path. API hostnames probe their health route. |
| `expected` | `[200, 301, 302]` | Acceptable response codes. |
| `group` | `"other"` | Display grouping on the page. `critical` renders first; other groups follow alphabetically. |

Current set:
- **critical** — `vyoh.gg`, `api.vyoh.gg` (`/health`), `engram.vyoh.gg`, `api.engram.vyoh.gg` (`/ready`), `www.vyoh.gg`, `notify.vyoh.gg` (`/health`).
- **bytesized** — `plex`, `sonarr`, `radarr`, `bazarr`, `hydra`, `nzb`, `deluge`, `tautulli`, `files`. All reverse-proxied through netcup's `byte-proxy.conf` vhost; the auth gateway in front of each returns 302 which the default `expected` codes cover.

Monitoring `notify.vyoh.gg` is the only way to catch "hub is down but box is up" — a case the workflow-failure-email fallback does not cover (probes to everything else succeed, nothing exits 1, no email).

Discovery is manual: `ssh vyoh 'grep -h server_name /etc/nginx/sites-enabled/*.conf | awk "{for(i=2;i<=NF;i++)print \$i}" | tr -d ";" | grep -v "^_$" | sort -u'` lists every hostname nginx answers for. Diff against `targets.toml` to see what's missing.

## States and alerting

Two states only:

- **up** — probe returned an expected status code.
- **down** — every attempt in the cycle failed or returned an unexpected code. The row shows the code or error.

Each cycle tries a host up to three times, 5 s apart, and only calls it down if all three fail. Hosts are probed concurrently so a dead box costs one host's worth of timeouts, not fifteen. Every host's outcome goes to the Actions log (kept 90 days), including the failed attempts a retry absorbed — the deployed `status.json` artifacts expire after a day and only keep the last cycle's code.

Alerts are gated on two fields `status.json` carries per host: `fail_streak` (consecutive down cycles) and `alerted` (a down alert has gone out for the current outage). A down alert fires when `fail_streak` reaches 2 (`CONFIRM_CYCLES`); a recovery alert fires only when `alerted` is set, so a one-cycle blip still paints a red tick on the strip but sends nothing. `alerted` is set when the alert is attempted, not delivered — an undelivered alert fails the workflow and the failure email stands in for it, which keeps a box-down outage to one email rather than one per cycle. Once one POST fails (after its own retries on network errors and 5xx), the remaining alerts in that run are skipped and logged: the hub is almost certainly down with the box.

Keys include the probe cycle's timestamp (`{host}:{state}:{checked_at}`), so a down→up→down→up sequence that clears the gate each time delivers four distinct alerts rather than being deduped. Retries within one run reuse the key, so the hub dedupes a POST that landed but lost its response.

Decided 2026-10-29 to gate alerts. Over the 24h before, 10 hosts went down for exactly one probe and were up on the next; each sent a down and a recovered message. Nine of the ten were bytesized hosts. Two causes showed in the logs: runner-side network failure (03:31 — three hosts down and the notify POST itself failed with `Errno 101 Network is unreachable`, which also failed the workflow as a false box-down) and momentary 502s from the netcup → bytesized proxy (radarr 14:31). Retries cover the first; the two-cycle gate covers anything that clears before the next run (15 min at the Worker cadence; an hourly-backup or push run landing in between shortens that). Cost: a real outage alerts 15–30 min after it starts rather than within 15.

The page detects the third case itself: if `status.json`'s `generated_at` is older than 90 minutes, a yellow banner says "prober may be delayed." The 90-min threshold means several consecutive Worker triggers failed, so it doesn't cry wolf on one missed tick. The hourly GitHub backup alone routinely overshoots it (its scheduled runs slip by hours), so the banner showing is the signal that the Worker has stopped. No alerts fire for staleness.

## Known gaps

- **IPv6 untested.** GitHub-hosted runners are IPv4-only. If v6 coverage ever matters, swap the workflow to Cloudflare Workers (1-min cadence, v6-capable) or add a second cadence from a v6-capable runner. Both are off-box, both post to the same shape.
- **Freshness, not instant.** ~15-min cadence from the Worker, and a down alert needs two consecutive failed cycles, so it lands 15–30 min after an outage starts. Acceptable for status-page use; not an incident pager.
- **Trigger failure is quiet.** If the Worker's dispatch fails (token revoked, Cloudflare cron outage), the failure only shows in the Worker's cron event log. The page degrades to the hourly GitHub schedule (which itself slips by hours) and the stale banner shows; no alert fires.
- **Watch-the-watcher at the Actions level.** If GitHub Actions itself is down, nothing probes. Visible on GitHub's own status page; the staleness banner catches the subset that affects us.

## Next action

1. **GitHub Pages:** repo settings → Pages → Source: "GitHub Actions". First `workflow_dispatch` run of `probe.yml` publishes the site. (Done.)
2. **DNS:** CNAME `status` → `sergeantjonas.github.io`. Verify with `dig +short status.vyoh.gg`. (Done.)
3. **TLS:** GitHub auto-provisions once DNS resolves. Can take minutes. (Done.)
4. **GitHub failure email:** github.com → Settings → Notifications → confirm "Send notifications for failed workflows only" (or equivalent) is on. This is the box-down alert path; without it, the fallback is silent. (Confirmed on 2026-10-29.)
5. **Add a `status` source to notify.vyoh.gg.** On the box, append `SOURCE_STATUS_SECRET=…` and `SOURCE_STATUS_DISCORD_URL=https://discord.com/api/webhooks/…` to `/srv/notify/.env`, then redeploy the stack so the env is read. The secret must be ≥32 printable-ASCII chars.
6. **Add repo secrets:** Settings → Secrets and variables → Actions → add `NOTIFY_HUB_URL=https://notify.vyoh.gg/messages` and `NOTIFY_HUB_SECRET=<the status source secret>`. (Done 2026-10-10.)
7. **Drill:** `gh workflow run probe` from the laptop. First run after secrets land → no transitions → exit 0. Then edit `targets.toml` to add a bogus host like `broken.vyoh.gg`, push, confirm the Discord message arrives via the hub on the next scheduled run. Also `pnpm discord:test status` on the hub box to confirm the webhook routes correctly before relying on it.
8. **Add Bytesized hostnames** to `targets.toml` as their nginx vhosts land on netcup. (Done 2026-10-10 for the initial sweep.)
9. **Deploy the trigger Worker.** From `worker/`: `npx wrangler@4.142.0 login` (once per machine), `npx wrangler@4.142.0 secret put GITHUB_TOKEN` (paste the PAT; confirm creating the Worker if asked), `npx wrangler@4.142.0 deploy`. A fresh Cloudflare account must have a workers.dev subdomain before cron triggers will register, even with `workers_dev: false` — opening Workers & Pages in the dashboard once creates it. Verify: `gh run list --event workflow_dispatch` shows a run within 15 min. (Done 2026-10-12.)

## History

Per-target per-probe history lives inside `status.json` itself. Shape: a list of `[unix_ts, state]` pairs per target, chronological oldest-first, pruned to the last 24h by timestamp. The probe appends one entry per run and drops anything older. Pruned by age rather than count because the cadence varies with which trigger fires (Worker, hourly backup, push); a count cap silently meant 72h at 15-min cadence.

The page draws the strip as 96 fixed wall-clock slots of 15 min, the last being the slot that contains `generated_at`, not one bar per probe. A slot is down if any probe in it was down, up if it had only up probes, and "no data" if no probe landed — so a missed run shows as a gap rather than stretching the window.

Decided 2026-10-10 to go per-probe rather than per-day worst-wins (the first implementation that same day). Per-day rollup made a single 5-min outage paint a whole 24h bar red, which was wrong for a page where you'd want to see "mostly up, one blip at 03:42" at a glance. Per-probe shows exactly that pattern — one red tick in a strip of green — and matches the user's actual mental model ("every previous ping"). Display moved to 15-min slots on 2026-10-12 so the strip spans 24h whatever the cadence; storage stays per probe, and at the 15-min Worker cadence a slot is effectively one probe.

Window chosen is 24h because a per-probe strip at the original 5-min cadence (288 bars) already pushed layout density; longer windows would need either narrower bars (approaching invisible) or a horizontal scroll. Hour-level or day-level aggregation for a *longer* window is an open option if 24h ever feels too short.

Fresh targets start with just the latest entry, so every slot before it shows "no data". Within a day of continuous runs the strip fills.

Why in `status.json` and not a separate `history.json`: fifteen hosts × ~96–120 entries a day (Worker plus hourly backup) × ~25 bytes ≈ 45 KB; one file, one fetch, one deploy step. If storage ever becomes a concern we can compact (state as single char, timestamps as deltas from `generated_at`), but it isn't close yet.

## Open

- **Backups on the page.** Healthchecks.io still runs the backup checks for vyoh/engram. Those badges could live on this page too, but it would mix "is the public site up" with "did last night's backup run." Deferred until the question matters.
- **Certificate expiry.** A probe could fail its check when the served certificate comes within N days of expiry, catching a silent Certbot failure. Not wired yet.
- **Longer-than-24h view.** The strip only covers the last 24h. A longer window (e.g., 7-day or 90-day) would need either per-hour / per-day aggregation (coarser but more history) or a scrollable strip. Deferred until the 24h window actually feels too short — right now the question "did it break today?" is what the page needs to answer.
