# status.vyoh.gg

One page that says whether each public site on the shared VPS answers, plus a Discord ping when one changes state.

- **Live:** <https://status.vyoh.gg> (GitHub Pages).
- **Prober:** GitHub Actions scheduled workflow, every ~5 minutes. No infrastructure on the box being watched.
- **Alerts:** [notify.vyoh.gg](https://github.com/sergeantjonas/notify.vyoh.gg) on state transitions. If the hub is unreachable (box down), the workflow exits non-zero and GitHub's workflow-failure email covers the gap.

Pure static HTML and JS, no build step. `probe.py` walks `targets.toml`, writes `status.json`, and the Action deploys it to Pages. Editing `targets.toml` is the whole workflow for adding or removing monitored sites.

Planning and decisions live under [docs/working-notes/](docs/working-notes/). The cross-project constraint ("the box cannot watch itself") lives in [commonplace](https://github.com/sergeantjonas/commonplace/blob/main/status-page.md), since the same rule applies to anything else that reports on the box.
