# Status page

**Status:** Active — off-box prober landed 2026-10-09; Pages/DNS/webhook setup next.

One page that says whether each public site on the shared VPS answers. Watches every tenant and belongs to none of them.

Cross-project reasoning (why hosting off-box, why alerting off-box) lives in [`~/dev/commonplace/status-page.md`](https://github.com/sergeantjonas/commonplace/blob/main/status-page.md) — this note holds the implementation.

## Shape

Everything runs on GitHub-owned infrastructure. No tenant on the netcup box, no self-hosted monitoring box, no SaaS account.

- **Prober:** `.github/workflows/probe.yml` — scheduled Actions workflow, every 5 min (plus `workflow_dispatch` and `push`). Runs [`probe.py`](../../probe.py) against the targets in [`targets.toml`](../../targets.toml), writes `status.json`, posts to Discord on state transitions, deploys the whole thing to Pages.
- **Page:** [`index.html`](../../index.html) in the repo root. Fetches `status.json`, renders group → host rows with up/down pills. Vanilla JS, no build step.
- **Alerts:** Discord webhook URL stored as repo secret `DISCORD_WEBHOOK_URL`, posted directly from the Action.
- **State store:** `status.json` on Pages itself. The workflow fetches the previous `status.json` from `https://status.vyoh.gg/status.json` at the start of each run, so transitions survive across runs without committing anything back to git.

Decided against the earlier on-box-prober + healthchecks.io shape (2026-10-07..08 history) on simplicity grounds: moving the prober off-box deletes the need for silence-detection entirely, which was healthchecks.io's whole job here. Backups still use healthchecks.io; the status page doesn't.

## Targets

Edit `targets.toml` to add or remove. Each `[[target]]` block carries:

| Field | Default | Notes |
|---|---|---|
| `host` | required | Public hostname, probed over HTTPS. |
| `path` | `/` | URL path. API hostnames probe their health route. |
| `expected` | `[200, 301, 302]` | Acceptable response codes. |
| `group` | `"other"` | Display grouping on the page. `critical` renders first; other groups follow alphabetically. |

Starting set: `vyoh.gg`, `api.vyoh.gg` (`/health`), `engram.vyoh.gg`, `api.engram.vyoh.gg` (`/ready`), all tagged `critical`. The Bytesized reverse-proxied `*arr`/plex/etc. go in a `bytesized` group as you add their vhosts to netcup's nginx.

## States and alerting

Two states only:

- **up** — probe returned an expected status code.
- **down** — probe failed or returned an unexpected code. The row shows the code or error.

Transitions trigger a Discord message with host + reason. Already-down hosts don't re-notify every tick; only transitions do.

The page detects the third case itself: if `status.json`'s `generated_at` is older than 20 minutes, a yellow banner says "monitoring looks late." No alerts fire for that — Actions scheduled runs are flaky under load, and we don't want to page on prober flakiness.

## Known gaps

- **IPv6 untested.** GitHub-hosted runners are IPv4-only. If v6 coverage ever matters, swap the workflow to Cloudflare Workers (1-min cadence, v6-capable) or add a second cadence from a v6-capable runner. Both are off-box, both post to the same shape.
- **Freshness, not instant.** Actions scheduled runs can slip to 10-15 min under GitHub-wide load. Acceptable for status-page use; not an incident pager.
- **Watch-the-watcher at the Actions level.** If GitHub Actions itself is down, nothing probes. Visible on GitHub's own status page; the staleness banner catches the subset that affects us.

## Next action

1. **GitHub Pages:** repo settings → Pages → Source: "GitHub Actions". First `workflow_dispatch` run of `probe.yml` publishes the site.
2. **DNS:** CNAME `status` → `sergeantjonas.github.io`. Verify with `dig +short status.vyoh.gg`.
3. **TLS:** GitHub auto-provisions once DNS resolves. Can take minutes.
4. **Discord webhook:** make a channel on your server, add a webhook integration, copy the URL. Repo settings → Secrets and variables → Actions → New secret `DISCORD_WEBHOOK_URL`.
5. **Drill:** `gh workflow run probe` from the laptop. Expect no notifications (first run has no previous state). Edit `targets.toml` to add a bogus host like `broken.vyoh.gg`, push, confirm the Discord message fires on the next scheduled run.
6. **Add Bytesized hostnames** to `targets.toml` as their nginx vhosts land on netcup.

## Open

- **Backups on the page.** Healthchecks.io still runs the backup checks for vyoh/engram. Those badges could live on this page too, but it would mix "is the public site up" with "did last night's backup run." Deferred until the question matters.
- **Certificate expiry.** A probe could fail its check when the served certificate comes within N days of expiry, catching a silent Certbot failure. Not wired yet.
- **History.** `status.json` only holds the current state. If we want a day/week view, we'd persist a `history.json` or write append-only snapshots. Deferred until useful.
