# Status page

**Status:** Active — off-box prober landed 2026-10-09; wired to notify.vyoh.gg 2026-10-10; Pages/DNS setup next, awaiting notify-hub to go live.

One page that says whether each public site on the shared VPS answers. Watches every tenant and belongs to none of them.

Cross-project reasoning (why hosting off-box, why alerting off-box) lives in [`~/dev/commonplace/status-page.md`](https://github.com/sergeantjonas/commonplace/blob/main/status-page.md) — this note holds the implementation.

## Shape

Everything runs on GitHub-owned infrastructure. No tenant on the netcup box, no self-hosted monitoring box, no SaaS account.

- **Prober:** `.github/workflows/probe.yml` — scheduled Actions workflow, every 15 min nominally (plus `workflow_dispatch` and `push`). GitHub Actions scheduled runs on public free-tier repos are routinely delayed or dropped under load — observed cadence can slip to one run per few hours. Accepted as the trade-off for not standing up external infrastructure (a Cloudflare Worker to poke `workflow_dispatch` would solve it; deferred until the slippage actually hurts). Runs [`probe.py`](../../probe.py) against the targets in [`targets.toml`](../../targets.toml), writes `status.json`, POSTs state transitions to notify.vyoh.gg, deploys the whole thing to Pages. The Pages deploy steps run with `if: !cancelled()` so the page keeps updating even when the probe step failed delivery.
- **Page:** [`index.html`](../../index.html) in the repo root. Fetches `status.json` and renders a hero headline + grouped host rows with per-row uptime % and current streak. Vanilla JS, no build step. One self-hosted font ([`fonts/inter.woff2`](../../fonts/inter.woff2), ~48 KB) carries the typography; favicon is a state-coloured rounded badge generated inline. Deliberate accent (indigo `#4f46e5` light / `#818cf8` dark) picked to sit outside the status palette so brand doesn't fight state.
- **Alerting (two layers):** routine transitions `POST` to `https://notify.vyoh.gg/messages` per the hub's contract (`key`/`title`/`body`/`url`, bearer auth; no `source` in the body — the hub infers it from the secret). Credentials come from repo secrets `NOTIFY_HUB_URL` + `NOTIFY_HUB_SECRET` (scoped per-source — a leak lets an attacker post status-page alerts, nothing more). When the hub is unreachable — overwhelmingly because the netcup box it runs on is down — the POST fails, `probe.py` exits non-zero, the workflow goes red, and GitHub emails the workflow-failure. That email **is** the box-down alert. No Discord webhook URL ever lives in this repo.
- **State store:** `status.json` on Pages itself. The workflow fetches the previous `status.json` from `https://status.vyoh.gg/status.json` at the start of each run, so transitions survive across runs without committing anything back to git.

Decided against the earlier on-box-prober + healthchecks.io shape (2026-10-07..08 history) on simplicity grounds: moving the prober off-box deletes the need for silence-detection entirely, which was healthchecks.io's whole job here. Backups still use healthchecks.io; the status page doesn't.

Decided 2026-10-10 to route alerts via notify.vyoh.gg rather than directly to a Discord webhook. The webhook URL stays in notify-hub where it belongs (per the hub's own contract: one credential, one holder). The box-down case notify-hub cannot carry is handled by workflow-failure email instead, which needs no secret.

## Targets

Edit `targets.toml` to add or remove. Each `[[target]]` block carries:

| Field | Default | Notes |
|---|---|---|
| `host` | required | Public hostname, probed over HTTPS. |
| `path` | `/` | URL path. API hostnames probe their health route. |
| `expected` | `[200, 301, 302]` | Acceptable response codes. |
| `group` | `"other"` | Display grouping on the page. `critical` renders first; other groups follow alphabetically. |

Current set:
- **critical** — `vyoh.gg`, `api.vyoh.gg` (`/health`), `engram.vyoh.gg`, `api.engram.vyoh.gg` (`/ready`), `www.vyoh.gg`.
- **bytesized** — `plex`, `sonarr`, `radarr`, `bazarr`, `hydra`, `nzb`, `deluge`, `tautulli`, `files`. All reverse-proxied through netcup's `byte-proxy.conf` vhost; the auth gateway in front of each returns 302 which the default `expected` codes cover.
- **not yet added:** `notify.vyoh.gg` — the nginx vhost exists but the hub itself returns 404 (nothing bound upstream). Add once the hub is live.

Discovery is manual: `ssh vyoh 'grep -h server_name /etc/nginx/sites-enabled/*.conf | awk "{for(i=2;i<=NF;i++)print \$i}" | tr -d ";" | grep -v "^_$" | sort -u'` lists every hostname nginx answers for. Diff against `targets.toml` to see what's missing.

## States and alerting

Two states only:

- **up** — probe returned an expected status code.
- **down** — probe failed or returned an unexpected code. The row shows the code or error.

Transitions POST one envelope each to notify.vyoh.gg. Keys include the probe cycle's timestamp (`{host}:{state}:{checked_at}`), so a down→up→down→up sequence delivers four distinct alerts rather than being deduped. Already-down hosts don't re-notify every tick; only transitions do.

The page detects the third case itself: if `status.json`'s `generated_at` is older than 90 minutes, a yellow banner says "prober may be delayed." The 90-min threshold is deliberately generous — Actions scheduled runs on free-tier public repos routinely slip 30–60 min, and we don't want to cry wolf on normal GitHub flakiness. No alerts fire for staleness.

## Known gaps

- **IPv6 untested.** GitHub-hosted runners are IPv4-only. If v6 coverage ever matters, swap the workflow to Cloudflare Workers (1-min cadence, v6-capable) or add a second cadence from a v6-capable runner. Both are off-box, both post to the same shape.
- **Freshness, not instant.** Actions scheduled runs can slip to 10-15 min under GitHub-wide load. Acceptable for status-page use; not an incident pager.
- **Watch-the-watcher at the Actions level.** If GitHub Actions itself is down, nothing probes. Visible on GitHub's own status page; the staleness banner catches the subset that affects us.

## Next action

1. **GitHub Pages:** repo settings → Pages → Source: "GitHub Actions". First `workflow_dispatch` run of `probe.yml` publishes the site.
2. **DNS:** CNAME `status` → `sergeantjonas.github.io`. Verify with `dig +short status.vyoh.gg`.
3. **TLS:** GitHub auto-provisions once DNS resolves. Can take minutes.
4. **GitHub failure email:** github.com → Settings → Notifications → confirm "Send notifications for failed workflows only" (or equivalent) is on. This is the box-down alert path; without it, the fallback is silent.
5. **Add a `status` source to notify.vyoh.gg.** On the box, append `SOURCE_STATUS_SECRET=…` and `SOURCE_STATUS_DISCORD_URL=https://discord.com/api/webhooks/…` to `/srv/notify/.env`, then redeploy the stack so the env is read. The secret must be ≥32 printable-ASCII chars.
6. **Add repo secrets:** Settings → Secrets and variables → Actions → add `NOTIFY_HUB_URL=https://notify.vyoh.gg/messages` and `NOTIFY_HUB_SECRET=<the status source secret>`.
7. **Drill:** `gh workflow run probe` from the laptop. First run after secrets land → no transitions → exit 0. Then edit `targets.toml` to add a bogus host like `broken.vyoh.gg`, push, confirm the Discord message arrives via the hub on the next scheduled run. Also `pnpm discord:test status` on the hub box to confirm the webhook routes correctly before relying on it.
8. **Add Bytesized hostnames** to `targets.toml` as their nginx vhosts land on netcup. (Done 2026-10-10 for the initial sweep.)

## History

Per-target per-probe history lives inside `status.json` itself. Shape: a list of `[unix_ts, state]` pairs per target, chronological oldest-first, capped at 288 entries (≈ 24h at the current 5-min cadence). The probe appends one entry per run and rolls off the oldest once the cap is hit.

Decided 2026-10-10 to go per-probe rather than per-day worst-wins (the first implementation that same day). Per-day rollup made a single 5-min outage paint a whole 24h bar red, which was wrong for a page where you'd want to see "mostly up, one blip at 03:42" at a glance. Per-probe shows exactly that pattern — one red tick in a strip of green — and matches the user's actual mental model ("every previous ping").

Window chosen is 24h because 288 bars already pushes layout density; longer windows would need either narrower bars (approaching invisible) or a horizontal scroll. Hour-level or day-level aggregation for a *longer* window is an open option if 24h ever feels too short.

Fresh targets start with just the latest entry; the page pads the left with "no data" bars so every host shows a fixed-width 288-bar strip. Within a day of continuous runs the pad disappears and the strip is live.

Why in `status.json` and not a separate `history.json`: fourteen hosts × 288 entries × ~25 bytes ≈ 100 KB; one file, one fetch, one deploy step. If storage ever becomes a concern we can compact (state as single char, timestamps as deltas from `generated_at`), but it isn't close yet.

## Open

- **Backups on the page.** Healthchecks.io still runs the backup checks for vyoh/engram. Those badges could live on this page too, but it would mix "is the public site up" with "did last night's backup run." Deferred until the question matters.
- **Certificate expiry.** A probe could fail its check when the served certificate comes within N days of expiry, catching a silent Certbot failure. Not wired yet.
- **Longer-than-24h view.** The per-probe strip only covers the last 24h. A longer window (e.g., 7-day or 90-day) would need either per-hour / per-day aggregation (coarser but more history) or a scrollable strip. Deferred until the 24h window actually feels too short — right now the question "did it break today?" is what the page needs to answer.
